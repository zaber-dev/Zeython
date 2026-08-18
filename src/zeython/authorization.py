"""Authorization: "can this specific user do this specific thing", answered
separately from authentication.

``require_auth()`` (see :mod:`zeython.auth`) only answers "is anyone logged
in" -- a materially different, and much weaker, question than "can the
logged-in user edit *this* post". Almost every mutating endpoint in a real
app needs the second question answered, and there was previously nothing in
the framework that helped with it beyond hand-rolled ``if`` checks scattered
across controllers.

Modeled on Laravel's Gate/Policy split: named closures for one-off checks
(``gate.define(...)``), resource-bound Policy classes (``gate.policy(...)``)
for the common case of many abilities against one model, a global
``gate.before(...)`` hook for cross-cutting rules like "an admin can do
anything", and a light :class:`HasRoles` mixin plus :meth:`Gate.role`/
:meth:`Gate.permission` sugar for role- or permission-gated abilities. All
of it is optional and additive -- a project that only ever needs
``gate.define("delete-post", lambda user, post: ...)`` never has to touch
the rest.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.requests import Request

from zeython.auth import require_auth
from zeython.exceptions import ForbiddenException
from zeython.providers import ServiceProvider

Check = Callable[..., Awaitable[bool] | bool]
BeforeCheck = Callable[..., Awaitable[bool | None] | bool | None]


class Gate:
    """A registry of named authorization checks ("abilities")."""

    def __init__(self) -> None:
        self._abilities: dict[str, Check] = {}
        self._policies: dict[type, Any] = {}
        self._before: list[BeforeCheck] = []

    def define(self, ability: str, check: Check) -> None:
        """Register ``check(user, *args) -> bool`` (sync or async) under ``ability``::

            gate.define("update-post", lambda user, post: post.author_id == user.id)
        """
        self._abilities[ability] = check

    def policy(self, model: type, policy: type | Any) -> None:
        """Register a Policy for ``model``: a plain class with one method per
        ability, e.g. ``def update(self, user, post) -> bool``. ``policy``
        may be the class itself (instantiated once, here) or an existing
        instance::

            class PostPolicy:
                def update(self, user, post) -> bool:
                    return post.author_id == user.id

                def create(self, user) -> bool:
                    return user.is_verified

            gate.policy(Post, PostPolicy)

        An ability not covered by :meth:`define` falls back to the policy
        registered for ``type(args[0])`` (or ``args[0]`` itself, when it's a
        class -- for abilities like ``"create"`` checked before an instance
        exists: ``authorize(request, "create", Post)``). A policy method
        named ``before(self, user, ability)`` runs first if present, and a
        non-``None`` result short-circuits the specific ability method --
        the per-policy equivalent of :meth:`before`.
        """
        self._policies[model] = policy() if isinstance(policy, type) else policy

    def before(self, check: BeforeCheck) -> None:
        """Register a global hook run before every :meth:`allows` check,
        as ``check(user, ability, *args)``. A non-``None`` result
        short-circuits the specific ability/policy check entirely --
        typically used for a blanket bypass::

            gate.before(lambda user, ability, *args: True if getattr(user, "is_admin", False) else None)

        Returning ``None`` (the default for a check that only cares about
        specific abilities) defers to the normal ability/policy lookup.
        """
        self._before.append(check)

    @staticmethod
    def role(*names: str) -> Check:
        """A check requiring the user to have any of ``names``, via
        :class:`HasRoles`::

            gate.define("manage-users", Gate.role("admin"))
        """

        def check(user: Any, *_args: Any) -> bool:
            has_any_role = getattr(user, "has_any_role", None)
            return bool(has_any_role(*names)) if has_any_role is not None else False

        return check

    @staticmethod
    def permission(name: str) -> Check:
        """A check requiring the user to have permission ``name``, via
        :class:`HasRoles`::

            gate.define("delete-post", Gate.permission("posts.delete"))
        """

        def check(user: Any, *_args: Any) -> bool:
            has_permission = getattr(user, "has_permission", None)
            return bool(has_permission(name)) if has_permission is not None else False

        return check

    def _policy_check(self, ability: str, args: tuple[Any, ...]) -> Check | None:
        if not args:
            return None
        resource = args[0]
        resource_type = resource if isinstance(resource, type) else type(resource)
        policy = self._policies.get(resource_type)
        if policy is None:
            return None
        method = getattr(policy, ability, None)
        if method is None:
            return None
        # A class (no instance yet, e.g. authorize(request, "create", Post))
        # is only used to resolve *which* policy applies -- Laravel's own
        # create()-style policy methods don't additionally receive it as an
        # argument, so it's consumed here rather than forwarded.
        forwarded_args = args[1:] if isinstance(resource, type) else args

        async def check(user: Any, *_ignored_args: Any) -> bool:
            before = getattr(policy, "before", None)
            if before is not None:
                before_result = before(user, ability)
                if inspect.isawaitable(before_result):
                    before_result = await before_result
                if before_result is not None:
                    return bool(before_result)
            result = method(user, *forwarded_args)
            if inspect.isawaitable(result):
                result = await result
            return bool(result)

        return check

    async def allows(self, user: Any, ability: str, *args: Any) -> bool:
        """Whether ``user`` passes the ``ability`` check against ``args``.

        Checked in order: any :meth:`before` hook, then a :meth:`define`-d
        closure, then a :meth:`policy` method for ``type(args[0])``.
        Raises ``KeyError`` if none of those resolve -- an authorization
        check for an ability that doesn't exist is a bug in the calling
        code, not a "deny by default" situation to swallow silently.
        """
        for before_check in self._before:
            before_result = before_check(user, ability, *args)
            if inspect.isawaitable(before_result):
                before_result = await before_result
            if before_result is not None:
                return bool(before_result)

        check = self._abilities.get(ability) or self._policy_check(ability, args)
        if check is None:
            raise KeyError(
                f"No ability registered for {ability!r}. Register it with gate.define(...) or gate.policy(...)."
            )
        result = check(user, *args)
        if inspect.isawaitable(result):
            result = await result
        return bool(result)

    async def denies(self, user: Any, ability: str, *args: Any) -> bool:
        return not await self.allows(user, ability, *args)


class HasRoles:
    """Mixin adding role/permission checks to a user model, for
    :meth:`Gate.role`/:meth:`Gate.permission` and for direct use in
    templates/controllers.

    Duck-typed against a ``roles`` relationship of objects with a ``name``
    attribute, each optionally with its own ``permissions`` relationship of
    objects with a ``name`` attribute -- the conventional Role/Permission
    many-to-many shape (a user has roles, a role has permissions), which
    this framework doesn't impose a schema for since it's already just
    regular models and relationships (see docs/authorization.md for the
    table definitions and :mod:`zeython.database.seeder` for seeding them)::

        class User(Model, Authenticatable, HasRoles):
            __tablename__ = "users"
            roles: Mapped[list["Role"]] = relationship(secondary=user_roles, lazy="selectin")

        class Role(Model):
            __tablename__ = "roles"
            name: Mapped[str] = mapped_column(String(50), unique=True)
            permissions: Mapped[list["Permission"]] = relationship(secondary=role_permissions, lazy="selectin")

        class Permission(Model):
            __tablename__ = "permissions"
            name: Mapped[str] = mapped_column(String(100), unique=True)
    """

    roles: Any

    def has_role(self, name: str) -> bool:
        return any(role.name == name for role in self.roles)

    def has_any_role(self, *names: str) -> bool:
        return any(self.has_role(name) for name in names)

    def has_all_roles(self, *names: str) -> bool:
        return all(self.has_role(name) for name in names)

    def has_permission(self, name: str) -> bool:
        return any(permission.name == name for role in self.roles for permission in getattr(role, "permissions", ()))


async def authorize(request: Request, ability: str, *args: Any) -> Any:
    """Require the current user to pass ``ability``, or raise.

    Authorization presupposes authentication: this calls :func:`~zeython.auth.require_auth`
    first, so an anonymous request gets ``UnauthorizedException`` (401) --
    only a *logged-in* user who fails the ability check gets
    ``ForbiddenException`` (403). Returns the authenticated user on success::

        async def destroy(self, request):
            post = await Post.find(int(request.path_params["id"]))
            await authorize(request, "delete-post", post)
            await post.delete()
    """
    user = await require_auth(request)
    gate: Gate = request.app.state.container.make(Gate)
    if not await gate.allows(user, ability, *args):
        raise ForbiddenException(f"You are not authorized to {ability.replace('-', ' ')}.")
    return user


class AuthorizationServiceProvider(ServiceProvider):
    """Binds an empty :class:`Gate` into the container.

    Define your app's abilities in your own provider's ``boot()`` (register
    this provider first, or anywhere -- ``boot()`` order doesn't matter,
    only that every provider's ``register()`` has already run)::

        class AppAuthorizationProvider(ServiceProvider):
            def boot(self) -> None:
                gate: Gate = self.container.make(Gate)
                gate.define("delete-post", lambda user, post: post.author_id == user.id)
                gate.policy(Post, PostPolicy)
                gate.before(lambda user, ability, *args: True if getattr(user, "is_admin", False) else None)
    """

    def register(self) -> None:
        gate = Gate()
        self.container.singleton(Gate, lambda: gate)


__all__ = ["Gate", "HasRoles", "authorize", "AuthorizationServiceProvider"]

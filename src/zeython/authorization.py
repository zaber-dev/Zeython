"""Authorization: "can this specific user do this specific thing", answered
separately from authentication.

``require_auth()`` (see :mod:`zeython.auth`) only answers "is anyone logged
in" -- a materially different, and much weaker, question than "can the
logged-in user edit *this* post". Almost every mutating endpoint in a real
app needs the second question answered, and there was previously nothing in
the framework that helped with it beyond hand-rolled ``if`` checks scattered
across controllers.

Modeled on Laravel's Gate: named abilities, registered once (typically in a
``ServiceProvider.boot()``), checked by name everywhere they're needed --
not a full policy-class-per-model system, to keep this a small, single seam
rather than another layer of framework machinery.
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


class Gate:
    """A registry of named authorization checks ("abilities")."""

    def __init__(self) -> None:
        self._abilities: dict[str, Check] = {}

    def define(self, ability: str, check: Check) -> None:
        """Register ``check(user, *args) -> bool`` (sync or async) under ``ability``::

            gate.define("update-post", lambda user, post: post.author_id == user.id)
        """
        self._abilities[ability] = check

    async def allows(self, user: Any, ability: str, *args: Any) -> bool:
        """Whether ``user`` passes the ``ability`` check against ``args``.

        Raises ``KeyError`` if ``ability`` was never :meth:`define`-d --
        an authorization check for an ability that doesn't exist is a bug
        in the calling code, not a "deny by default" situation to swallow
        silently.
        """
        check = self._abilities.get(ability)
        if check is None:
            raise KeyError(f"No ability registered for {ability!r}. Register it with gate.define(...).")
        result = check(user, *args)
        if inspect.isawaitable(result):
            result = await result
        return bool(result)

    async def denies(self, user: Any, ability: str, *args: Any) -> bool:
        return not await self.allows(user, ability, *args)


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
    """

    def register(self) -> None:
        gate = Gate()
        self.container.singleton(Gate, lambda: gate)


__all__ = ["Gate", "authorize", "AuthorizationServiceProvider"]

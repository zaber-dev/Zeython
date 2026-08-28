"""Audit logging: an automatic changelog of who created, updated, or
deleted which model records, and what changed.

Built entirely on the existing :class:`~zeython.db.model.Observer` system
rather than a new mechanism -- :class:`AuditObserver` is an ``Observer``
you attach to whichever models need a paper trail::

    Post.observe(AuditObserver(AuditLog))

``AuditLog`` is your own :class:`~zeython.db.Model` subclass (columns:
``auditable_type``, ``auditable_id``, ``event``, ``changes``, ``actor_type``,
``actor_id``) -- the same ``record_model`` pattern
:mod:`zeython.notifications`'s ``database`` channel uses, so each project
owns its own migration for the table instead of the framework mandating
one. Generated for you by `zeython new` under
``app/Models/audit_log.py``.

Every audited write and its audit-log row share the same database session
and therefore the same transaction: :class:`~zeython.db.session.DatabaseSessionMiddleware`
commits or rolls back both together, so an audit entry can never exist
without the change it describes actually landing, or vice versa.

The *actor* attributed to each entry -- who did this -- comes from
:func:`current_actor`, a contextvar :class:`AuditActorMiddleware` sets
automatically per request from whichever authentication scheme is
active. Outside a request (a background job, a console command), call
:func:`set_actor` yourself before making the change.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any
from weakref import WeakKeyDictionary

from sqlalchemy import inspect
from starlette.requests import Request

from zeython.db.model import Model, Observer
from zeython.providers import ServiceProvider

logger = logging.getLogger("zeython.audit_log")

#: Columns never recorded, even for a model with no __hidden__ of its own --
#: every one of these is Model's own bookkeeping, not business data: id is
#: already carried as auditable_id, created_at/updated_at are timestamps
#: (updated_at in particular changes on every single update -- pure noise),
#: and is_deleted/deleted_at are the *mechanism* of a soft delete, already
#: implied by the "deleted" event itself.
_ALWAYS_IGNORED_COLUMNS = frozenset({"id", "created_at", "updated_at", "is_deleted", "deleted_at"})

_current_actor: ContextVar[tuple[str, int] | None] = ContextVar("zeython_audit_actor", default=None)


def current_actor() -> tuple[str, int] | None:
    """The ``(actor_type, actor_id)`` attributed to audit log entries written
    from here on in the current context, or ``None`` for an anonymous/system
    action. ``actor_type`` is the actor model's class name (e.g. ``"User"``).
    """
    return _current_actor.get()


def set_actor(actor: Model | None) -> None:
    """Attribute audit log entries written from here on (in this async
    context) to ``actor`` -- for code with no request/middleware to infer
    it from (a background job, a console command, a scheduled task)::

        async def handle(self) -> None:
            set_actor(await User.find(self.performed_by_id))
            await order.update(status="shipped")

    Pass ``None`` to explicitly record subsequent changes as anonymous/system
    -- e.g. to override an actor :class:`AuditActorMiddleware` already set,
    for a change your own code makes on the user's behalf but that isn't
    really *their* action.
    """
    _current_actor.set((type(actor).__name__, actor.id) if actor is not None else None)


class AuditActorMiddleware:
    """Pure ASGI middleware: sets :func:`current_actor` for the duration of
    the request from whichever authentication scheme resolves a user first
    -- :func:`zeython.auth.current_user` (session cookie), then
    :func:`zeython.api_auth.current_api_user` (bearer token). Leaves the
    actor anonymous (``None``) if neither resolves one, or if neither
    module's middleware is registered at all -- both are tried
    best-effort, so this works whether an app uses cookie auth, token
    auth, both, or neither.

    Registered by default in a generated project, the same reasoning
    :class:`~zeython.request_id.RequestIdServiceProvider` relies on: with
    no model actually being audited (nothing calls ``Model.observe(AuditObserver(...))``),
    this only sets a contextvar nothing reads, so there's nothing to get
    wrong by always registering it.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token = _current_actor.set(None)
        try:
            actor = await self._resolve_actor(Request(scope, receive))
            if actor is not None:
                set_actor(actor)
            await self.app(scope, receive, send)
        finally:
            _current_actor.reset(token)

    async def _resolve_actor(self, request: Request) -> Model | None:
        # Broad except: neither auth module's middleware being registered
        # (zeython.auth's SessionMiddleware not installed, no Authorization
        # header handling wired up) is a completely normal configuration,
        # not a bug to surface here -- an unresolved actor just means this
        # request's audit entries (if any are written) record no actor,
        # which is a metadata gap, not a correctness or security issue.
        try:
            from zeython.auth import current_user

            user = await current_user(request)
            if user is not None:
                return user
        except Exception:
            pass

        try:
            from zeython.api_auth import current_api_user

            user = await current_api_user(request)
            if user is not None:
                return user
        except Exception:
            pass

        return None


class AuditObserver(Observer):
    """Writes one row to ``record_model`` for every create/update/delete of
    whatever model this is attached to, via :meth:`~zeython.db.model.Model.observe`::

        Post.observe(AuditObserver(AuditLog))

    ``changes`` records: every non-hidden field's value for ``created``;
    only the fields that actually changed, as ``{"old": ..., "new": ...}``
    pairs, for ``updated`` (nothing recorded if nothing did); every
    non-hidden field's last known value (as ``"old"``, ``"new"`` left
    ``None``) for ``deleted`` -- captured before the row is gone, so a hard
    delete's audit trail still shows what was deleted, not just that
    something was. Fields named in the audited model's own ``__hidden__``
    (the same convention :meth:`~zeython.db.model.Model.to_dict` uses to
    keep password hashes etc. out of serialized output) are never
    recorded, in either direction.

    Never attach this to ``record_model`` itself -- ``AuditLog.observe(AuditObserver(AuditLog))``
    -- each audit-log row's own creation would trigger another one,
    without end.
    """

    def __init__(self, record_model: type[Model]) -> None:
        self.record_model = record_model
        # Keyed by the model instance itself (not e.g. its id, which is
        # None for a not-yet-flushed record) so an aborted save (updating()
        # ran, but a later step -- validate_or_raise(), the flush itself --
        # raised before updated() ever ran) can't accumulate an entry
        # nothing will ever pop: once the instance itself is no longer
        # referenced elsewhere, this reclaims automatically.
        self._pending_diff: WeakKeyDictionary[Model, dict[str, dict[str, Any]]] = WeakKeyDictionary()

    async def created(self, model: Model) -> None:
        changes = {field: {"old": None, "new": value} for field, value in self._values(model).items()}
        await self._record(model, "created", changes)

    async def updating(self, model: Model) -> None:
        self._pending_diff[model] = self._diff(model)

    async def updated(self, model: Model) -> None:
        changes = self._pending_diff.pop(model, {})
        if changes:
            await self._record(model, "updated", changes)

    async def deleted(self, model: Model) -> None:
        changes = {field: {"old": value, "new": None} for field, value in self._values(model).items()}
        await self._record(model, "deleted", changes)

    def _column_names(self, model: Model) -> set[str]:
        hidden = set(model.__hidden__)
        return {
            name for name in model.__table__.columns.keys()  # noqa: SIM118
            if name not in hidden and name not in _ALWAYS_IGNORED_COLUMNS
        }

    def _values(self, model: Model) -> dict[str, Any]:
        return {name: getattr(model, name) for name in self._column_names(model)}

    def _diff(self, model: Model) -> dict[str, dict[str, Any]]:
        names = self._column_names(model)
        state = inspect(model)
        changes: dict[str, dict[str, Any]] = {}
        for name in names:
            history = state.attrs[name].history
            if not history.has_changes():
                continue
            old = history.deleted[0] if history.deleted else None
            new = history.added[0] if history.added else getattr(model, name)
            changes[name] = {"old": old, "new": new}
        return changes

    async def _record(self, model: Model, event: str, changes: dict[str, dict[str, Any]]) -> None:
        if type(model) is self.record_model:
            raise RuntimeError(
                f"AuditObserver is attached to {self.record_model.__name__} itself -- "
                "that would audit-log every audit-log entry's own creation, without end. "
                "Attach it to the models you want tracked, never to record_model."
            )
        actor = current_actor()
        await self.record_model.create(
            auditable_type=type(model).__name__,
            auditable_id=model.id,
            event=event,
            changes=changes,
            actor_type=actor[0] if actor else None,
            actor_id=actor[1] if actor else None,
        )


async def audit_trail(record_model: type[Model], model: Model) -> list[Model]:
    """Every audit log entry for ``model``, oldest first::

        history = await audit_trail(AuditLog, post)
    """
    rows = await record_model.find_by(auditable_type=type(model).__name__, auditable_id=model.id)
    return sorted(rows, key=lambda row: row.created_at)


class AuditLogServiceProvider(ServiceProvider):
    """Registers :class:`AuditActorMiddleware`, so :func:`current_actor` is
    set automatically from whichever authentication scheme handled the
    current request::

        app.register(AuditLogServiceProvider)

    Register this **first** -- before ``DatabaseServiceProvider``,
    ``AuthServiceProvider``, ``ApiAuthServiceProvider``, before anything
    else that calls ``add_middleware()``. ``add_middleware()`` prepends,
    so the most recently registered middleware wraps outermost; every
    middleware-adding provider registered *after* this one then wraps
    *around* ``AuditActorMiddleware``, pushing it further inward no
    matter how many more get added later. It needs to end up innermost:
    resolving the actor needs a database session already open (a query
    against your user model) and, for cookie auth, ``SessionMiddleware``
    to have already parsed the session cookie -- both are provided by
    middleware layers that must therefore sit *outside* this one.
    Registered too late (anywhere after ``DatabaseServiceProvider``),
    ``current_user()``/``current_api_user()`` both fail silently from
    inside :meth:`AuditActorMiddleware._resolve_actor`'s broad ``except``,
    and every audited entry ends up anonymous even for an authenticated
    request -- the same class of subtle ordering trap documented on
    :class:`~zeython.maintenance.MaintenanceModeServiceProvider`.

    Doesn't attach auditing to any model on its own -- that needs your own
    ``record_model`` (see :mod:`zeython.audit_log`'s own docstring) and at
    least one ``SomeModel.observe(AuditObserver(YourAuditLog))`` call,
    typically in another service provider's ``boot()`` once your models
    are all defined. See docs/audit-log.md.
    """

    def boot(self) -> None:
        self.app.add_middleware(AuditActorMiddleware)


__all__ = [
    "AuditActorMiddleware",
    "AuditLogServiceProvider",
    "AuditObserver",
    "audit_trail",
    "current_actor",
    "set_actor",
]

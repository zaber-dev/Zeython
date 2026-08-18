"""Row-level multi-tenancy: isolating one tenant's rows from another's in a
single shared database, rather than a database (or schema) per tenant.

A model opts in just by declaring a ``tenant_id`` column -- no mixin, no
per-query flag. :class:`~zeython.db.Model`'s own query methods
(``find``/``all``/``find_by``/``paginate``) check for that column and, if
present, scope every read to :func:`current_tenant_id` automatically (see
``Model._base_select()``); a new row gets ``tenant_id`` assigned from the
same source on ``save()`` if it wasn't already set explicitly. Multi-tenant
awareness lives in one place -- the column's presence -- rather than
scattered `.where(tenant_id=...)` calls a future query is one missed line
away from leaking across tenants.

:class:`TenantMiddleware` resolves *which* tenant a request belongs to
and makes it available to :func:`current_tenant_id` for the request's
duration via a :class:`~contextvars.ContextVar`, the same technique
:func:`~zeython.request_id.request_id` and
:func:`~zeython.localization.current_locale` use -- readable from a
``Model`` query with no ``request`` in hand.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from starlette.requests import Request

from zeython.providers import ServiceProvider

if TYPE_CHECKING:
    from zeython.application import Application

_current_tenant_id: ContextVar[Any | None] = ContextVar("zeython_tenant_id", default=None)

#: Resolves a request to a tenant ID (any hashable/comparable value -- an
#: int, a UUID, a slug), or ``None`` if this request doesn't belong to a
#: tenant. May be sync or async.
TenantResolver = Callable[[Request], "Any | None | Awaitable[Any | None]"]

__all__ = ["TenancyServiceProvider", "TenantMiddleware", "TenantResolver", "as_tenant", "current_tenant_id"]


def current_tenant_id() -> Any | None:
    """The current request's resolved tenant ID.

    ``None`` outside a request handled by :class:`TenantMiddleware`, or
    when the resolver returned nothing for this request -- in either case,
    ``Model`` query methods apply no tenant filter at all (not "filter to
    tenant None"), the same way an unauthenticated request has no locale
    override and just gets the default. A background job or script that
    needs tenant scoping sets it explicitly with :func:`as_tenant`.
    """
    return _current_tenant_id.get()


@contextmanager
def as_tenant(tenant_id: Any) -> Iterator[None]:
    """Scope every ``Model`` query inside this block to ``tenant_id`` --
    for a job, a script, or a test that has no request (and therefore no
    :class:`TenantMiddleware`) to resolve one from::

        with as_tenant(tenant.id):
            posts = await Post.all()   # only this tenant's rows
    """
    token = _current_tenant_id.set(tenant_id)
    try:
        yield
    finally:
        _current_tenant_id.reset(token)


class TenantMiddleware:
    """Pure ASGI middleware: resolves the request's tenant via ``resolver``
    and sets it as a contextvar for :func:`current_tenant_id` for the
    request's duration.
    """

    def __init__(self, app: Any, *, resolver: TenantResolver) -> None:
        self.app = app
        self.resolver = resolver

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        tenant_id = self.resolver(request)
        if hasattr(tenant_id, "__await__"):
            tenant_id = await tenant_id  # type: ignore[misc]

        token = _current_tenant_id.set(tenant_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _current_tenant_id.reset(token)


class TenancyServiceProvider(ServiceProvider):
    """Registers :class:`TenantMiddleware` with ``resolver``.

    ``resolver`` is a **required** argument -- there is deliberately no
    default. How a request maps to a tenant (a subdomain, a header, the
    logged-in user's own ``tenant_id``) is entirely app-specific, and
    guessing wrong here is a cross-tenant data leak, not a cosmetic
    mistake -- the same reasoning :class:`~zeython.admin.AdminServiceProvider`'s
    required ``guard`` has.

    ::

        from zeython import Application, TenancyServiceProvider

        def resolve_tenant(request):
            # e.g. acme.example.com -> "acme"
            return request.url.hostname.split(".")[0]

        app.register(TenancyServiceProvider(app, resolver=resolve_tenant))

    See docs/multi-tenancy.md.
    """

    def __init__(self, app: Application, *, resolver: TenantResolver) -> None:
        super().__init__(app)
        self.resolver = resolver

    def boot(self) -> None:
        self.app.add_middleware(TenantMiddleware, resolver=self.resolver)

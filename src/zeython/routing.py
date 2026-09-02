"""Ergonomic routing built on top of Starlette's proven route matching."""

from __future__ import annotations

import contextvars
import functools
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from typing import Any

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import BaseRoute, Mount, Route, WebSocketRoute

Endpoint = Callable[..., Any]

_ALL_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")

_current_api_version: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "zeython_current_api_version", default=None
)


def current_api_version() -> str | None:
    """The version label (e.g. ``"v1"``) the current request was routed under.

    ``None`` outside a request, or inside one routed through a plain
    (non-versioned) :class:`Router`. Set for the duration of an endpoint
    call registered via :meth:`Router.version`.
    """
    return _current_api_version.get()


def deprecated(*, sunset: str | None = None) -> Callable[[Endpoint], Endpoint]:
    """Mark an endpoint deprecated, signaling it with standard HTTP headers.

    Sets ``Deprecation: true`` (per the IETF draft) on every response, and
    ``Sunset: <sunset>`` (an RFC 8594 HTTP-date, per RFC 7231 section 7.1.1.1)
    when a removal date is known::

        @app.router.get("/v1/reports")
        @deprecated(sunset="Wed, 01 Jan 2027 00:00:00 GMT")
        async def old_reports(request: Request) -> Response: ...
    """

    def decorator(endpoint: Endpoint) -> Endpoint:
        @functools.wraps(endpoint)
        async def wrapper(*args: Any, **kwargs: Any) -> Response:
            response: Response = await endpoint(*args, **kwargs)
            response.headers["Deprecation"] = "true"
            if sunset is not None:
                response.headers["Sunset"] = sunset
            return response

        return wrapper

    return decorator


class Controller:
    """Marker base class for class-based controllers used with :meth:`Router.resource`."""


class Router:
    """Collects routes and exposes Laravel/FastAPI-style decorator sugar.

    A ``Router`` compiles down to a plain list of Starlette ``BaseRoute``
    objects, so nesting via :meth:`include` is just a ``Mount`` and gets the
    same battle-tested path matching as everything else built on Starlette.
    """

    def __init__(self, prefix: str = "", *, api_version: str | None = None) -> None:
        self.prefix = prefix.rstrip("/")
        self.routes: list[BaseRoute] = []
        self._api_version = api_version

    def _full_path(self, path: str) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        full = f"{self.prefix}{path}"
        return full or "/"

    def _versioned(self, endpoint: Endpoint) -> Endpoint:
        """Wrap ``endpoint`` so :func:`current_api_version` resolves during its call.

        A no-op unless this router was created with an ``api_version`` (see
        :meth:`version`) -- plain routers pay nothing for this.
        """
        if self._api_version is None:
            return endpoint

        version = self._api_version

        @functools.wraps(endpoint)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            token = _current_api_version.set(version)
            try:
                return await endpoint(*args, **kwargs)
            finally:
                _current_api_version.reset(token)

        return wrapper

    def route(self, path: str, methods: Iterable[str], *, name: str | None = None) -> Callable[[Endpoint], Endpoint]:
        def decorator(endpoint: Endpoint) -> Endpoint:
            self.routes.append(
                Route(
                    self._full_path(path),
                    self._versioned(endpoint),
                    methods=list(methods),
                    name=name or endpoint.__name__,
                )
            )
            return endpoint

        return decorator

    def get(self, path: str, *, name: str | None = None) -> Callable[[Endpoint], Endpoint]:
        return self.route(path, ["GET"], name=name)

    def post(self, path: str, *, name: str | None = None) -> Callable[[Endpoint], Endpoint]:
        return self.route(path, ["POST"], name=name)

    def put(self, path: str, *, name: str | None = None) -> Callable[[Endpoint], Endpoint]:
        return self.route(path, ["PUT"], name=name)

    def patch(self, path: str, *, name: str | None = None) -> Callable[[Endpoint], Endpoint]:
        return self.route(path, ["PATCH"], name=name)

    def delete(self, path: str, *, name: str | None = None) -> Callable[[Endpoint], Endpoint]:
        return self.route(path, ["DELETE"], name=name)

    def any(self, path: str, *, name: str | None = None) -> Callable[[Endpoint], Endpoint]:
        return self.route(path, _ALL_METHODS, name=name)

    def websocket(self, path: str, *, name: str | None = None) -> Callable[[Endpoint], Endpoint]:
        """Register a WebSocket handler: ``async def handler(websocket: WebSocket) -> None``.

        See :mod:`zeython.websockets` and docs/websockets.md.
        """

        def decorator(endpoint: Endpoint) -> Endpoint:
            self.routes.append(
                WebSocketRoute(self._full_path(path), self._versioned(endpoint), name=name or endpoint.__name__)
            )
            return endpoint

        return decorator

    def include(self, router: Router, *, prefix: str = "") -> None:
        """Mount another router's routes under an optional additional prefix."""
        self.routes.append(Mount(prefix or "/", routes=router.routes))

    @contextmanager
    def version(self, version: str, *, prefix: str | None = None) -> Iterator[Router]:
        """Group routes under a version prefix, with :func:`current_api_version` set during each call.

        Yields a sub-:class:`Router` to register routes on; it's mounted
        onto this router only once the ``with`` block finishes, so build it
        up fully inside the block::

            with app.router.version("v1") as v1:
                v1.resource("/posts", PostControllerV1)

        Defaults ``prefix`` to ``/{version}`` (so ``"v1"`` mounts at
        ``/v1``); pass ``prefix=""`` to version routes without changing
        their path.
        """
        sub_prefix = self.prefix + (prefix if prefix is not None else f"/{version}")
        sub = Router(sub_prefix, api_version=version)
        yield sub
        # Not routed through include()/Mount: the sub-router already bakes
        # its full prefix into every route it registers, so mounting it
        # under another prefix would double it up -- and mounting several
        # versions each at "/" would have every one of them match (and
        # claim) every request, since a Mount's own prefix strips to "" at
        # "/". Flattening its already-fully-pathed routes in directly
        # avoids both problems.
        self.routes.extend(sub.routes)

    def mount(self, path: str, app: Any, *, name: str | None = None) -> None:
        """Mount an arbitrary ASGI app (e.g. ``starlette.staticfiles.StaticFiles``) at a path prefix."""
        self.routes.append(Mount(path, app=app, name=name))

    def resource(self, path: str, controller_cls: type[Controller], *, only: Iterable[str] | None = None) -> None:
        """Register RESTful CRUD routes bound to a controller's methods.

        Maps: index->GET path, store->POST path, show->GET path/{id:int},
        update->PUT/PATCH path/{id:int}, destroy->DELETE path/{id:int}.

        ``{id:int}``, not a plain ``{id}`` -- every :class:`~zeython.db.Model`'s
        primary key is an integer, so a request for e.g. ``/posts/abc``
        fails route *matching* itself (a clean 404, same as an unknown
        route) instead of reaching the handler and blowing up on
        ``int(request.path_params["id"])``, the conversion every generated
        ``show``/``update``/``destroy`` action does next.
        """
        controller = controller_cls()
        action_map: dict[str, tuple[tuple[str, ...], str]] = {
            "index": (("GET",), ""),
            "store": (("POST",), ""),
            "show": (("GET",), "/{id:int}"),
            "update": (("PUT", "PATCH"), "/{id:int}"),
            "destroy": (("DELETE",), "/{id:int}"),
        }
        allowed = set(only) if only is not None else set(action_map)

        for action, (methods, suffix) in action_map.items():
            if action not in allowed or not hasattr(controller, action):
                continue
            handler = getattr(controller, action)
            route_path = self._full_path(f"{path.rstrip('/')}{suffix}")
            self.routes.append(
                Route(
                    route_path,
                    self._versioned(handler),
                    methods=list(methods),
                    name=f"{path.strip('/')}.{action}",
                )
            )


__all__ = ["Router", "Controller", "Request", "Response", "current_api_version", "deprecated"]

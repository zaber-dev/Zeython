"""Ergonomic routing built on top of Starlette's proven route matching."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import BaseRoute, Mount, Route

Endpoint = Callable[..., Any]

_ALL_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")


class Controller:
    """Marker base class for class-based controllers used with :meth:`Router.resource`."""


class Router:
    """Collects routes and exposes Laravel/FastAPI-style decorator sugar.

    A ``Router`` compiles down to a plain list of Starlette ``BaseRoute``
    objects, so nesting via :meth:`include` is just a ``Mount`` and gets the
    same battle-tested path matching as everything else built on Starlette.
    """

    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix.rstrip("/")
        self.routes: list[BaseRoute] = []

    def _full_path(self, path: str) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        full = f"{self.prefix}{path}"
        return full or "/"

    def route(self, path: str, methods: Iterable[str], *, name: str | None = None) -> Callable[[Endpoint], Endpoint]:
        def decorator(endpoint: Endpoint) -> Endpoint:
            self.routes.append(
                Route(self._full_path(path), endpoint, methods=list(methods), name=name or endpoint.__name__)
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

    def include(self, router: Router, *, prefix: str = "") -> None:
        """Mount another router's routes under an optional additional prefix."""
        self.routes.append(Mount(prefix or "/", routes=router.routes))

    def mount(self, path: str, app: Any, *, name: str | None = None) -> None:
        """Mount an arbitrary ASGI app (e.g. ``starlette.staticfiles.StaticFiles``) at a path prefix."""
        self.routes.append(Mount(path, app=app, name=name))

    def resource(self, path: str, controller_cls: type[Controller], *, only: Iterable[str] | None = None) -> None:
        """Register RESTful CRUD routes bound to a controller's methods.

        Maps: index->GET path, store->POST path, show->GET path/{id},
        update->PUT/PATCH path/{id}, destroy->DELETE path/{id}.
        """
        controller = controller_cls()
        action_map: dict[str, tuple[str, str]] = {
            "index": ("GET", ""),
            "store": ("POST", ""),
            "show": ("GET", "/{id}"),
            "update": ("PUT", "/{id}"),
            "destroy": ("DELETE", "/{id}"),
        }
        allowed = set(only) if only is not None else set(action_map)

        for action, (method, suffix) in action_map.items():
            if action not in allowed or not hasattr(controller, action):
                continue
            handler = getattr(controller, action)
            route_path = self._full_path(f"{path.rstrip('/')}{suffix}")
            self.routes.append(
                Route(route_path, handler, methods=[method], name=f"{path.strip('/')}.{action}")
            )


__all__ = ["Router", "Controller", "Request", "Response"]

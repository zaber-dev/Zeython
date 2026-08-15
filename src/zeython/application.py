"""The Zeython application: an ASGI app assembled from service providers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import Response

from zeython.config import Config
from zeython.container import Container
from zeython.exceptions import default_exception_handlers
from zeython.providers import ServiceProvider
from zeython.routing import Endpoint, Router


class Application:
    """The central object: owns the container, config, router, and providers.

    ``Application`` is itself a valid ASGI callable, so ``uvicorn main:app``
    works directly once you construct one and register at least a router.
    """

    def __init__(self, config: Config | None = None, *, base_path: str | Path | None = None) -> None:
        self.base_path = Path(base_path) if base_path is not None else Path.cwd()
        self.config = config or Config.load(self.base_path)
        self.container = Container()
        self.container.instance(Config, self.config)
        self.container.instance(Container, self.container)

        self.router = Router()
        self.container.instance(Router, self.router)

        self._providers: list[ServiceProvider] = []
        self._middleware: list[Middleware] = []
        self._booted = False
        self._asgi: Starlette | None = None

    # -- Providers ------------------------------------------------------------------

    def register(self, provider: type[ServiceProvider] | ServiceProvider) -> Application:
        instance = provider(self) if isinstance(provider, type) else provider
        instance.register()
        self._providers.append(instance)
        return self

    def add_middleware(self, middleware_class: Callable[..., Any], **options: Any) -> None:
        self._middleware.append(Middleware(middleware_class, **options))

    def boot(self) -> Application:
        if self._booted:
            return self
        for provider in self._providers:
            provider.boot()
        self._booted = True
        return self

    # -- Routing sugar, delegating to the app's router -------------------------------

    def get(self, path: str, *, name: str | None = None) -> Callable[[Endpoint], Endpoint]:
        return self.router.get(path, name=name)

    def post(self, path: str, *, name: str | None = None) -> Callable[[Endpoint], Endpoint]:
        return self.router.post(path, name=name)

    def put(self, path: str, *, name: str | None = None) -> Callable[[Endpoint], Endpoint]:
        return self.router.put(path, name=name)

    def patch(self, path: str, *, name: str | None = None) -> Callable[[Endpoint], Endpoint]:
        return self.router.patch(path, name=name)

    def delete(self, path: str, *, name: str | None = None) -> Callable[[Endpoint], Endpoint]:
        return self.router.delete(path, name=name)

    def include_router(self, router: Router, *, prefix: str = "") -> None:
        self.router.include(router, prefix=prefix)

    # -- ASGI ------------------------------------------------------------------------

    def _build_asgi(self) -> Starlette:
        self.boot()
        app = Starlette(
            debug=self.config.debug,
            routes=self.router.routes,
            middleware=self._middleware,
            exception_handlers=default_exception_handlers(),
        )
        app.state.debug = self.config.debug
        app.state.container = self.container
        app.state.config = self.config
        return app

    @property
    def asgi(self) -> Starlette:
        if self._asgi is None:
            self._asgi = self._build_asgi()
        return self._asgi

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        await self.asgi(scope, receive, send)

    def run(self, *, host: str | None = None, port: int | None = None) -> None:
        """Run with uvicorn. For auto-reload during development, use the `zeython serve` CLI instead."""
        import uvicorn

        uvicorn.run(self, host=host or self.config.host, port=port or self.config.port)


__all__ = ["Application", "Request", "Response"]

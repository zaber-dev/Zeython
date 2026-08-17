"""Service providers: the seam where cross-cutting concerns hook into boot."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zeython.application import Application


class ServiceProvider:
    """Base class for registering and booting application services.

    ``register()`` runs for every provider before any provider's ``boot()``
    runs, so bindings you depend on in ``boot()`` are guaranteed to exist
    regardless of registration order.
    """

    def __init__(self, app: Application) -> None:
        self.app = app
        self.container = app.container
        self.config = app.config

    def register(self) -> None:
        """Bind services into the container. Override in subclasses."""

    def boot(self) -> None:
        """Run once all providers have registered. Override in subclasses."""


class DatabaseServiceProvider(ServiceProvider):
    """Wires up the async :class:`~zeython.db.Database` and its request-scoped session.

    ``DATABASE_POOL_SIZE``/``DATABASE_MAX_OVERFLOW`` are passed straight
    through to SQLAlchemy's connection pool when set -- unset by default,
    so nothing changes for an in-memory SQLite URL (``:memory:``), whose
    default pool doesn't accept them at all. See
    docs/database.md#connection-pooling.
    """

    def register(self) -> None:
        from zeython.db.session import Database

        engine_kwargs: dict[str, object] = {}
        pool_size = self.config.get("database.pool_size")
        if pool_size is not None:
            engine_kwargs["pool_size"] = pool_size
        max_overflow = self.config.get("database.max_overflow")
        if max_overflow is not None:
            engine_kwargs["max_overflow"] = max_overflow

        database = Database(
            self.config.database_url,
            echo=self.config.get("database.echo", False),
            **engine_kwargs,
        )
        self.container.singleton(Database, lambda: database)

    def boot(self) -> None:
        from zeython.db.session import Database, DatabaseSessionMiddleware

        database = self.container.make(Database)
        self.app.add_middleware(DatabaseSessionMiddleware, database=database)


class RouteServiceProvider(ServiceProvider):
    """Imports route modules for their side effect of registering routes on the app."""

    def __init__(self, app: Application, modules: tuple[str, ...] = ()) -> None:
        super().__init__(app)
        self.modules = modules

    def register(self) -> None:
        import importlib

        for module_name in self.modules:
            importlib.import_module(module_name)


class ViewServiceProvider(ServiceProvider):
    """Binds a :class:`~zeython.views.Views` instance for server-rendered HTML.

    Looks for templates in ``resources/views`` under the app's base path by
    default; override with ``VIEWS_PATH`` in ``.env`` or the ``views.path``
    config key.
    """

    def register(self) -> None:
        from zeython.views import Views

        directory = self.config.get("views.path", str(self.app.base_path / "resources" / "views"))
        views = Views(directory)
        self.container.singleton(Views, lambda: views)


class CorsServiceProvider(ServiceProvider):
    """Opt-in CORS support, configured via ``.env``.

    - ``CORS_ORIGINS`` — comma-separated list of allowed origins (default: none)
    - ``CORS_ALLOW_CREDENTIALS`` — default ``false``
    - ``CORS_ALLOW_METHODS`` — comma-separated, default ``*``
    - ``CORS_ALLOW_HEADERS`` — comma-separated, default ``*``
    """

    def boot(self) -> None:
        from starlette.middleware.cors import CORSMiddleware

        origins_raw = self.config.get("cors.origins", "")
        origins = [origin.strip() for origin in str(origins_raw).split(",") if origin.strip()]
        methods = [m.strip() for m in str(self.config.get("cors.allow_methods", "*")).split(",") if m.strip()]
        headers = [h.strip() for h in str(self.config.get("cors.allow_headers", "*")).split(",") if h.strip()]

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=bool(self.config.get("cors.allow_credentials", False)),
            allow_methods=methods,
            allow_headers=headers,
        )

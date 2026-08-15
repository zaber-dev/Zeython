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
    """Wires up the async :class:`~zeython.db.Database` and its request-scoped session."""

    def register(self) -> None:
        from zeython.db.session import Database

        database = Database(self.config.database_url, echo=self.config.get("database.echo", False))
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

"""Database seeders: populating a database with initial or demo data.

A fresh `zeython db migrate` gives you empty tables -- a seeder is how you
get from there to something a developer can actually click around in (an
admin user, a handful of demo posts) or a fixed reference row production
genuinely needs (a default role, a system account). One class per concern
in ``database/seeders/``, run with ``zeython db seed``.
"""

from __future__ import annotations

import importlib
import inspect
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from zeython.cli.loader import sync_project_modules

if TYPE_CHECKING:
    from zeython.application import Application


class Seeder(ABC):
    """Base class for a database seeder.

    ::

        class UserSeeder(Seeder):
            async def run(self) -> None:
                await UserFactory().create(email="admin@example.com")
                await UserFactory().create_many(9)

        class DatabaseSeeder(Seeder):
            async def run(self) -> None:
                await self.call(UserSeeder, PostSeeder)

    Runs inside a single database session opened by the CLI (``zeython db
    seed``) -- ``Model.create()``/factory ``create()`` calls inside ``run()``
    work exactly as they do in a request handler, no session parameter to
    thread through.
    """

    def __init__(self, app: Application) -> None:
        self.app = app
        self.container = app.container

    @abstractmethod
    async def run(self) -> None:
        """Insert seed data -- via factories, or ``Model.create()`` directly."""

    async def call(self, *seeder_classes: type[Seeder]) -> None:
        """Run other seeders from within this one, in order."""
        for seeder_cls in seeder_classes:
            await seeder_cls(self.app).run()


def discover_seeders(project_root: Path) -> dict[str, type[Seeder]]:
    """Every :class:`Seeder` subclass in ``database/seeders/*.py``, keyed by class name."""
    seeders_dir = project_root / "database" / "seeders"
    seeders: dict[str, type[Seeder]] = {}
    if not seeders_dir.is_dir():
        return seeders

    root_str = str(project_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    sync_project_modules(project_root)
    importlib.invalidate_caches()

    for path in sorted(seeders_dir.glob("*.py")):
        if path.stem == "__init__":
            continue

        module = importlib.import_module(f"database.seeders.{path.stem}")
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if obj is Seeder or not issubclass(obj, Seeder):
                continue
            if obj.__module__ != module.__name__:
                continue  # e.g. `from zeython.database.seeder import Seeder` itself
            seeders[name] = obj

    return seeders


__all__ = ["Seeder", "discover_seeders"]

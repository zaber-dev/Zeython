"""Custom CLI commands: the ``app/Console/Commands/`` extension point.

Laravel's Artisan and Django's ``manage.py`` both let an application define
its own CLI commands, wired into the same container/config the rest of the
app uses -- without that, a one-off script (a data import, a cleanup job)
ends up disconnected from the app entirely: its own hand-rolled
``Application()`` bootstrap, no access to ``container.make(...)``, easy to
drift from how the real app is actually configured. ``zeython command
<name>`` closes that gap.

One file per command in ``app/Console/Commands/``, one ``Command``
subclass per file -- ``zeython make command SendReport`` scaffolds one.
The command's CLI name defaults to the snake_case filename; override with
a ``name`` class attribute for something else (``reports:send``, ...).
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


class Command(ABC):
    """Base class for a custom ``zeython command <name>`` CLI command."""

    #: CLI name; defaults to the snake_case filename if left unset.
    name: str | None = None
    #: One-line description, shown by `zeython commands`.
    help: str = ""

    def __init__(self, app: Application) -> None:
        self.app = app
        self.container = app.container
        self.config = app.config

    @abstractmethod
    async def handle(self, *args: str) -> None:
        """Do the work. ``args`` are the raw extra CLI arguments after the command name.

        Runs outside any request, so there's no request-scoped database
        session automatically available -- open one explicitly if you need
        one, the same way any other out-of-request code does::

            async def handle(self, *args: str) -> None:
                database: Database = self.container.make(Database)
                async with database.session():
                    ...
        """


def discover_commands(project_root: Path) -> dict[str, type[Command]]:
    """Every :class:`Command` subclass in ``app/Console/Commands/*.py``, keyed by CLI name."""
    commands_dir = project_root / "app" / "Console" / "Commands"
    commands: dict[str, type[Command]] = {}
    if not commands_dir.is_dir():
        return commands

    root_str = str(project_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    sync_project_modules(project_root)

    # A freshly-scaffolded command file may not exist yet as far as the
    # path-based finder's directory-listing cache is concerned (e.g. right
    # after `zeython make command` wrote it) -- safe to call unconditionally,
    # unlike the sys.modules purge in sync_project_modules() above, since this
    # only clears finder caches and never un-registers an already-imported
    # module.
    importlib.invalidate_caches()

    for path in sorted(commands_dir.glob("*.py")):
        if path.stem == "__init__":
            continue

        module = importlib.import_module(f"app.Console.Commands.{path.stem}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is Command or not issubclass(obj, Command):
                continue
            if obj.__module__ != module.__name__:
                continue  # e.g. `from zeython.console import Command` itself, not a real command

            # `zeython make command` names the file with a `_command` suffix
            # (matching `make job`'s `_job.py` convention) but promises a
            # CLI name with that suffix stripped -- mirror the same stripping
            # here so a scaffolded command is actually runnable under the
            # name its own generated docstring claims.
            command_name = obj.name or path.stem.removesuffix("_command").replace("_", "-")
            commands[command_name] = obj

    return commands


__all__ = ["Command", "discover_commands"]

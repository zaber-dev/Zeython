"""Import a Zeython project's ``Application`` instance from its ``main.py``,
the way ``zeython serve``/``zeython command``/the MCP server all need to.

A single shared implementation because the subtlety here (temporarily
`chdir`-ing so `.env` loads from the right place, reloading `main` if a
long-lived process asks about the same project twice) is exactly the kind
of thing that drifts if copy-pasted into every caller that needs it.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import sys
from pathlib import Path
from typing import Any

_current_project_root: str | None = None
#: Top-level project-owned modules/packages this guard purges on a project
#: switch -- `app` (models, controllers, ...), `database` (factories,
#: seeders), and `main` itself (the project's entry point -- see
#: _import_main()'s docstring for why this one matters most).
_TRACKED_PACKAGES = ("app", "database", "main")


def sync_project_modules(project_root: Path) -> None:
    """Purge cached ``app``/``database``/``main`` modules if ``project_root``
    differs from the last project asked about in this process.

    A process that inspects more than one project in sequence -- this
    package's own test suite; hypothetically a long-lived process like the
    MCP server -- would otherwise silently resolve ``app``/``database``/``main``
    against whatever differently-rooted package happens to already be
    cached in ``sys.modules``, since a bare ``importlib.import_module(...)``
    reuses that cache without re-consulting ``sys.path`` at all. ``main``
    matters most here: without purging it too, a project with no
    ``main.py`` of its own would silently get back the *previous*
    project's cached ``Application`` instead of a clear error -- see
    :func:`_import_main`.

    Calls for the *same* project deliberately do nothing: re-importing
    would re-run every model's class body a second time, and SQLAlchemy's
    process-global registry rejects redefining the same table twice.
    """
    global _current_project_root
    root_str = str(project_root)
    if _current_project_root == root_str:
        return
    for module_name in [
        name
        for name in sys.modules
        if any(name == package or name.startswith(f"{package}.") for package in _TRACKED_PACKAGES)
    ]:
        del sys.modules[module_name]
    importlib.invalidate_caches()
    _current_project_root = root_str


def load_app(project_root: Path) -> Any:
    """Import ``main`` from ``project_root``, returning its ``app``.

    Temporarily changes the process's working directory to ``project_root``
    while importing: ``Application()`` (called at module scope in every
    generated ``main.py``) loads ``.env`` relative to ``Path.cwd()``, not
    relative to wherever this function's caller happens to be running from
    -- a long-lived process (an MCP server) or one invoked from a different
    directory has no particular relationship to the project it's currently
    being asked about, so without this, config would silently come from the
    wrong place (or nowhere).

    Raises ``ModuleNotFoundError`` if there's no ``main.py`` there, or
    ``AttributeError`` if it has no ``app`` -- both are accurate, actionable
    errors for "this isn't a Zeython project root," so they're left to
    propagate rather than being caught and reworded. That guarantee
    depends on this loader maintaining a single-project invariant in
    ``sys.path``: the *previous* project's root is removed before the new
    one is added, so a project with no ``main.py`` of its own can't have
    Python's import machinery silently fall through to an old project's
    still-importable ``main.py`` sitting earlier on the path.
    """
    root_str = str(project_root)

    previous_root = _current_project_root
    if previous_root is not None and previous_root != root_str:
        with contextlib.suppress(ValueError):
            sys.path.remove(previous_root)

    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    sync_project_modules(project_root)

    previous_cwd = Path.cwd()
    os.chdir(project_root)
    try:
        return _import_main()
    finally:
        os.chdir(previous_cwd)


def _import_main() -> Any:
    if "main" in sys.modules:
        # A long-lived process (the MCP server) may be asked about the same
        # project more than once; reload so edits since the last call are reflected.
        main = importlib.reload(sys.modules["main"])
    else:
        main = importlib.import_module("main")

    return main.app


__all__ = ["load_app", "sync_project_modules"]

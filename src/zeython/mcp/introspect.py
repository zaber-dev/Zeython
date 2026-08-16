"""Pure introspection functions the MCP tools build on.

Kept separate from the MCP tool definitions themselves so they're testable
without going through the MCP protocol layer at all -- these are just
"import a project's app and describe it" functions.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from zeython.cli.loader import load_app, sync_app_modules

__all__ = ["load_app", "describe_routes", "describe_models", "describe_app"]


def describe_routes(app: Any) -> list[dict[str, str]]:
    """Every registered HTTP route: method(s), path, and name."""
    routes: list[dict[str, str]] = []
    for route in app.router.routes:
        path = getattr(route, "path", None)
        if path is None:
            continue  # a Mount with no direct path (e.g. static files) -- not a single route
        methods = sorted(getattr(route, "methods", None) or [])
        routes.append(
            {
                "path": path,
                "methods": ", ".join(methods) if methods else "",
                "name": getattr(route, "name", None) or "",
            }
        )
    return routes


def describe_models(project_root: Path) -> list[dict[str, Any]]:
    """Every ``Model`` subclass registered under ``app.Models``: table, columns, relationships."""
    root_str = str(project_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    sync_app_modules(project_root)
    importlib.import_module("app.Models")

    from zeython.db import Model

    models: list[dict[str, Any]] = []
    for mapper in Model.registry.mappers:
        cls = mapper.class_
        # `cls.__dict__` (not `getattr`) -- __abstract__ is a plain class
        # attribute, and `getattr` would inherit `True` from Model itself
        # for every concrete subclass that doesn't happen to redeclare it.
        if cls is Model or cls.__dict__.get("__abstract__", False):
            continue
        columns = [
            {
                "name": column.name,
                "type": str(column.type),
                "nullable": column.nullable,
                "primary_key": column.primary_key,
            }
            for column in mapper.columns
        ]
        models.append(
            {
                "name": cls.__name__,
                "table": cls.__tablename__,
                "columns": columns,
                "relationships": [rel.key for rel in mapper.relationships],
            }
        )
    models.sort(key=lambda m: m["name"])
    return models


def describe_app(app: Any) -> dict[str, Any]:
    """Basic project info: app name, environment, debug flag, registered providers."""
    import zeython

    return {
        "app_name": app.config.app_name,
        "environment": app.config.environment,
        "debug": app.config.debug,
        "zeython_version": zeython.__version__,
        "providers": [type(provider).__name__ for provider in app.providers],
    }

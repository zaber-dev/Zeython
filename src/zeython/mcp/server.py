"""Zeython's MCP server: gives an AI coding agent direct tools to inspect a
Zeython project (its routes, its models) and search the framework's own
bundled, version-matched documentation, instead of grepping source files or
guessing at APIs.

Requires the ``mcp`` extra: ``pip install zeython[mcp]``. Run it with
``zeython mcp`` (stdio transport) and point your MCP client's config at that
command from your project directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from zeython.mcp import docs_index, introspect

server = FastMCP(
    "Zeython",
    instructions=(
        "Tools for working in a Zeython (async Python MVC framework) project. "
        "Prefer list_routes/list_models over grepping routes/web.py or app/Models/*.py by hand -- "
        "they reflect the actual registered routes and database schema, not what the source "
        "*looks like* it does. Prefer search_docs over guessing at a Zeython API; it searches "
        "the documentation bundled with the exact installed framework version, not a possibly "
        "stale training-data memory of it."
    ),
)


@server.tool()
def list_routes(project_root: str = ".") -> list[dict[str, str]]:
    """List every HTTP route registered in the Zeython project at project_root.

    Each entry has `path`, `methods` (comma-separated), and `name`. Read this
    before assuming a route exists, or before grepping routes/web.py by hand
    -- it reflects what's actually registered, including routes added via
    `.resource()` or mounted by service providers.
    """
    app = introspect.load_app(Path(project_root).resolve())
    return introspect.describe_routes(app)


@server.tool()
def list_models(project_root: str = ".") -> list[dict[str, Any]]:
    """List every Model subclass registered under app/Models/ in the Zeython project.

    Each entry has `name`, `table`, `columns` (name/type/nullable/primary_key),
    and `relationships` (attribute names). Read this before guessing a
    model's schema or grepping app/Models/*.py by hand.
    """
    return introspect.describe_models(Path(project_root).resolve())


@server.tool()
def app_info(project_root: str = ".") -> dict[str, Any]:
    """Basic info about the Zeython project at project_root: app name,
    environment, debug flag, installed Zeython version, and registered
    service providers (which tells you what's actually wired up -- auth,
    storage, mail, etc. -- not just what's importable).
    """
    app = introspect.load_app(Path(project_root).resolve())
    return introspect.describe_app(app)


@server.tool()
def search_docs(query: str) -> list[dict[str, str]]:
    """Search Zeython's own documentation, bundled with this installed
    version of the framework, for `query`. Use this before assuming a
    Zeython API exists, guessing at a config key, or inventing a convention
    -- the results are the real, current docs for the framework version
    actually installed in this project, not a training-data memory of some
    other version.
    """
    results = docs_index.search(query)
    return [{"file": r.file, "title": r.title, "snippet": r.snippet} for r in results]


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()

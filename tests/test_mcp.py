"""Tests for zeython.mcp -- skipped entirely if the `mcp` extra isn't installed.

Uses a single, module-scoped generated project rather than one per test:
SQLAlchemy's declarative registry (`Model.registry`/`Model.metadata`) is
process-global, so a second scaffold project defining its own `User`/`Post`
classes with the same table names would collide with the first's -- cleaning
up `sys.modules` between tests isn't enough to undo that. One shared project
for the whole module sidesteps it entirely.
"""

from pathlib import Path

import pytest

pytest.importorskip("mcp")

from zeython.cli.scaffold import new_project  # noqa: E402
from zeython.mcp import docs_index, introspect  # noqa: E402


@pytest.fixture(scope="module")
def scaffold_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    project_dir = tmp_path_factory.mktemp("mcp_project")
    new_project("MCP Test App", project_dir)
    db_path = project_dir / "database.db"
    (project_dir / ".env").write_text(
        f"APP_NAME=MCP Test App\nAPP_SECRET_KEY=test-secret\nAPP_DEBUG=true\n"
        f"DATABASE_URL=sqlite+aiosqlite:///{db_path}\n"
    )
    return project_dir


@pytest.fixture(scope="module")
def app(scaffold_project: Path):
    return introspect.load_app(scaffold_project)


# -- introspect.load_app / describe_* -------------------------------------------------


def test_load_app_returns_the_project_application(app) -> None:
    assert app.config.app_name == "MCP Test App"


def test_load_app_restores_the_working_directory(scaffold_project: Path) -> None:
    cwd_before = Path.cwd()
    introspect.load_app(scaffold_project)
    assert Path.cwd() == cwd_before


def test_describe_routes_lists_every_registered_route(app) -> None:
    routes = introspect.describe_routes(app)

    paths = {route["path"] for route in routes}
    assert "/" in paths
    assert "/users" in paths
    assert "/posts" in paths
    assert "/register" in paths

    home = next(route for route in routes if route["name"] == "home")
    assert "GET" in home["methods"]


def test_describe_models_lists_user_and_post_with_columns_and_relationships(scaffold_project: Path) -> None:
    # A subset check, not equality: Model.registry is process-global, so
    # other test files' throwaway model classes (Article, Account, ...) are
    # also present by the time the full suite has run -- describe_models()
    # accurately reflects that shared registry, which is exactly correct
    # behavior for a single real project (where nothing else would be
    # importing unrelated models into the same process).
    models = introspect.describe_models(scaffold_project)
    by_name = {model["name"]: model for model in models}

    assert {"User", "Post"} <= set(by_name)

    user_columns = {column["name"] for column in by_name["User"]["columns"]}
    assert {"id", "name", "email", "password_hash"} <= user_columns
    assert by_name["User"]["relationships"] == ["posts"]

    post_columns = {column["name"] for column in by_name["Post"]["columns"]}
    assert {"id", "title", "body", "author_id"} <= post_columns
    assert by_name["Post"]["relationships"] == ["author"]


def test_describe_app_reports_name_and_registered_providers(app) -> None:
    info = introspect.describe_app(app)

    assert info["app_name"] == "MCP Test App"
    assert info["debug"] is True
    assert "AuthServiceProvider" in info["providers"]
    assert "zeython_version" in info


# -- docs_index.search ----------------------------------------------------------------


def test_search_finds_the_most_relevant_doc_by_title() -> None:
    results = docs_index.search("relationships eager loading")

    assert results
    assert results[0].file == "relationships.md"


def test_search_returns_nothing_for_a_nonsense_query() -> None:
    assert docs_index.search("zzz_not_a_real_word_zzz") == []


def test_search_respects_the_limit() -> None:
    results = docs_index.search("the", limit=2)
    assert len(results) <= 2


# -- server tool registration -----------------------------------------------------------


async def test_server_exposes_the_expected_tools() -> None:
    from zeython.mcp.server import server

    tools = await server.list_tools()
    tool_names = {tool.name for tool in tools}
    assert {"list_routes", "list_models", "app_info", "search_docs"} <= tool_names

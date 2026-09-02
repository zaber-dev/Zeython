"""Tests for zeython.graphql -- execute_graphql() and GraphQLServiceProvider."""

import builtins
from pathlib import Path

import pytest
from graphql import GraphQLArgument, GraphQLField, GraphQLObjectType, GraphQLSchema, GraphQLString

from zeython.application import Application
from zeython.config import Config
from zeython.graphql import GraphQLServiceProvider, execute_graphql
from zeython.testing import client


def _resolve_hello(root: object, info: object, name: str = "World") -> str:
    return f"Hello, {name}!"


def _resolve_context(root: object, info: object) -> str:
    context = info.context  # type: ignore[attr-defined]
    return f"{'request' in context}:{'container' in context}"


def _resolve_boom(root: object, info: object) -> str:
    raise RuntimeError("boom")


def _build_schema() -> GraphQLSchema:
    query_type = GraphQLObjectType(
        name="Query",
        fields={
            "hello": GraphQLField(
                GraphQLString,
                args={"name": GraphQLArgument(GraphQLString)},
                resolve=_resolve_hello,
            ),
            "context": GraphQLField(GraphQLString, resolve=_resolve_context),
            "boom": GraphQLField(GraphQLString, resolve=_resolve_boom),
        },
    )
    return GraphQLSchema(query=query_type)


# -- execute_graphql() --------------------------------------------------------------


async def test_execute_graphql_returns_data_for_a_valid_query() -> None:
    schema = _build_schema()
    body = await execute_graphql(schema, query="{ hello }")

    assert body == {"data": {"hello": "Hello, World!"}}


async def test_execute_graphql_passes_variables_through() -> None:
    schema = _build_schema()
    body = await execute_graphql(
        schema,
        query="query($name: String) { hello(name: $name) }",
        variables={"name": "Ada"},
    )

    assert body == {"data": {"hello": "Hello, Ada!"}}


async def test_execute_graphql_passes_context_value_through_to_resolvers() -> None:
    schema = _build_schema()
    body = await execute_graphql(schema, query="{ context }", context_value={"request": 1, "container": 2})

    assert body == {"data": {"context": "True:True"}}


async def test_execute_graphql_formats_a_resolver_exception_as_an_error() -> None:
    schema = _build_schema()
    body = await execute_graphql(schema, query="{ boom }")

    assert body["data"] == {"boom": None}
    assert len(body["errors"]) == 1
    assert body["errors"][0]["message"] == "boom"


async def test_execute_graphql_reports_a_syntax_error_without_data() -> None:
    schema = _build_schema()
    body = await execute_graphql(schema, query="{ not valid graphql")

    assert body["data"] is None
    assert len(body["errors"]) == 1


async def test_execute_graphql_raises_a_clear_import_error_without_the_extra_installed() -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "graphql":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    schema = _build_schema()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(builtins, "__import__", fake_import)
        with pytest.raises(ImportError, match=r"pip install zeython\[graphql\]"):
            await execute_graphql(schema, query="{ hello }")


# -- GraphQLServiceProvider -----------------------------------------------------------


async def _make_app(tmp_path: Path, **kwargs: object) -> Application:
    app = Application(Config.load(tmp_path))
    app.register(GraphQLServiceProvider(app, schema=_build_schema(), **kwargs))
    return app


async def test_post_executes_a_query(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        response = await http.post("/graphql", json={"query": "{ hello }"})

    assert response.status_code == 200
    assert response.json() == {"data": {"hello": "Hello, World!"}}


async def test_post_accepts_variables_and_operation_name(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        response = await http.post(
            "/graphql",
            json={
                "query": "query Greet($name: String) { hello(name: $name) }",
                "variables": {"name": "Ada"},
                "operationName": "Greet",
            },
        )

    assert response.json() == {"data": {"hello": "Hello, Ada!"}}


async def test_post_without_a_query_field_is_a_bad_request(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        response = await http.post("/graphql", json={})

    assert response.status_code == 400


async def test_post_with_malformed_json_is_a_bad_request_not_a_500(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        response = await http.post(
            "/graphql", content=b"{not valid json", headers={"content-type": "application/json"}
        )

    assert response.status_code == 400


async def test_post_with_a_json_array_body_is_a_bad_request(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        response = await http.post("/graphql", json=["not", "an", "object"])

    assert response.status_code == 400


async def test_post_with_a_non_string_query_is_a_bad_request(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        response = await http.post("/graphql", json={"query": 123})

    assert response.status_code == 400


async def test_post_with_non_object_variables_is_a_bad_request(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        response = await http.post("/graphql", json={"query": "{ hello }", "variables": "not an object"})

    assert response.status_code == 400


async def test_resolvers_receive_the_request_and_container_in_context(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        response = await http.post("/graphql", json={"query": "{ context }"})

    assert response.json() == {"data": {"context": "True:True"}}


async def test_graphiql_is_disabled_by_default(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/graphql")

    assert response.status_code == 405


async def test_graphiql_defaults_to_debug_mode(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("APP_DEBUG=true\n")
    app = await _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/graphql")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "graphiql" in response.text.lower()
    assert "/graphql" in response.text


async def test_graphiql_can_be_forced_on_regardless_of_debug_mode(tmp_path: Path) -> None:
    app = await _make_app(tmp_path, graphiql=True)

    async with client(app) as http:
        response = await http.get("/graphql")

    assert response.status_code == 200


async def test_graphiql_can_be_forced_off_even_in_debug_mode(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("APP_DEBUG=true\n")
    app = await _make_app(tmp_path, graphiql=False)

    async with client(app) as http:
        response = await http.get("/graphql")

    assert response.status_code == 405


async def test_path_is_configurable(tmp_path: Path) -> None:
    app = await _make_app(tmp_path, path="/api/graphql")

    async with client(app) as http:
        default_path = await http.post("/graphql", json={"query": "{ hello }"})
        configured_path = await http.post("/api/graphql", json={"query": "{ hello }"})

    assert default_path.status_code == 404
    assert configured_path.status_code == 200

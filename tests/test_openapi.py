from pathlib import Path

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from zeython.application import Application
from zeython.config import Config
from zeython.db import Model
from zeython.openapi import OpenApiServiceProvider, describe, generate_openapi, model_schema
from zeython.routing import Controller
from zeython.testing import client


class OpenApiWidget(Model):
    __tablename__ = "openapi_widgets"
    __hidden__ = ("secret",)

    name: Mapped[str] = mapped_column(String(255))
    secret: Mapped[str] = mapped_column(String(255))
    note: Mapped[str] = mapped_column(String(255), nullable=True)


def _make_app(tmp_path: Path) -> Application:
    return Application(Config.load(tmp_path))


# -- generate_openapi() ----------------------------------------------------------------


def test_basic_shape_has_openapi_info_and_paths(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    @app.get("/ping")
    async def ping(request):
        return JSONResponse({"ok": True})

    spec = generate_openapi(app, title="My API", version="2.0.0", description="A test API")

    assert spec["openapi"] == "3.0.3"
    assert spec["info"] == {"title": "My API", "version": "2.0.0", "description": "A test API"}
    assert "/ping" in spec["paths"]
    assert "get" in spec["paths"]["/ping"]


def test_route_without_describe_gets_a_generic_response(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    @app.get("/ping")
    async def ping(request):
        return JSONResponse({"ok": True})

    spec = generate_openapi(app, title="t")
    operation = spec["paths"]["/ping"]["get"]

    assert operation["responses"] == {"200": {"description": "Successful response"}}
    assert "summary" not in operation
    assert "tags" not in operation


def test_describe_attaches_summary_and_tags(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    @app.get("/ping")
    @describe(summary="Ping the server", tags=["health"])
    async def ping(request):
        return JSONResponse({"ok": True})

    spec = generate_openapi(app, title="t")
    operation = spec["paths"]["/ping"]["get"]

    assert operation["summary"] == "Ping the server"
    assert operation["tags"] == ["health"]


def test_describe_attaches_request_body_and_responses(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    @app.post("/widgets")
    @describe(
        request_body={"type": "object", "properties": {"name": {"type": "string"}}},
        responses={201: {"description": "Created"}, 422: {"description": "Invalid"}},
    )
    async def create(request):
        return JSONResponse({}, status_code=201)

    spec = generate_openapi(app, title="t")
    operation = spec["paths"]["/widgets"]["post"]

    assert operation["requestBody"] == {
        "content": {"application/json": {"schema": {"type": "object", "properties": {"name": {"type": "string"}}}}}
    }
    assert operation["responses"] == {
        "201": {"description": "Created"},
        "422": {"description": "Invalid"},
    }


def test_describe_works_on_controller_methods_via_resource(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    class WidgetController(Controller):
        @describe(summary="List widgets", tags=["widgets"])
        async def index(self, request):
            return JSONResponse([])

        async def show(self, request):
            return JSONResponse({})

    app.router.resource("/widgets", WidgetController, only=("index", "show"))

    spec = generate_openapi(app, title="t")

    # @describe on a class method: getattr(instance, "index") returns a bound
    # method, and bound-method attribute lookup falls through to the
    # underlying function -- this is what proves that actually works, not
    # just that the decorator runs.
    assert spec["paths"]["/widgets"]["get"]["summary"] == "List widgets"
    assert spec["paths"]["/widgets"]["get"]["tags"] == ["widgets"]
    # The undecorated sibling method still gets a generic entry.
    assert spec["paths"]["/widgets/{id}"]["get"]["responses"] == {"200": {"description": "Successful response"}}


def test_head_and_options_are_excluded_from_operations(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    @app.get("/ping")
    async def ping(request):
        return JSONResponse({"ok": True})

    spec = generate_openapi(app, title="t")
    operations = spec["paths"]["/ping"]

    assert set(operations) == {"get"}


def test_typed_path_params_produce_openapi_path_and_parameters(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    @app.get("/items/{item_id:int}")
    async def show(request):
        return JSONResponse({})

    spec = generate_openapi(app, title="t")

    assert "/items/{item_id}" in spec["paths"]
    parameters = spec["paths"]["/items/{item_id}"]["get"]["parameters"]
    assert parameters == [{"name": "item_id", "in": "path", "required": True, "schema": {"type": "integer"}}]


def test_untyped_path_params_default_to_string(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    @app.get("/items/{item_id}")
    async def show(request):
        return JSONResponse({})

    spec = generate_openapi(app, title="t")
    parameters = spec["paths"]["/items/{item_id}"]["get"]["parameters"]

    assert parameters == [{"name": "item_id", "in": "path", "required": True, "schema": {"type": "string"}}]


def test_mounted_routes_do_not_produce_broken_or_empty_entries(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    static_dir = tmp_path / "static"
    static_dir.mkdir()

    @app.get("/ping")
    async def ping(request):
        return JSONResponse({"ok": True})

    app.router.mount("/static", StaticFiles(directory=str(static_dir)))

    spec = generate_openapi(app, title="t")  # must not raise

    assert list(spec["paths"]) == ["/ping"]


# -- model_schema() ---------------------------------------------------------------------


def test_model_schema_excludes_hidden_fields() -> None:
    schema = model_schema(OpenApiWidget)

    assert "secret" not in schema["properties"]
    assert "name" in schema["properties"]
    assert schema["properties"]["name"] == {"type": "string"}


def test_model_schema_marks_non_nullable_columns_without_default_as_required() -> None:
    schema = model_schema(OpenApiWidget)

    assert "name" in schema["required"]
    assert "note" not in schema["required"]  # nullable=True


def test_model_schema_accepts_extra_excludes() -> None:
    schema = model_schema(OpenApiWidget, exclude=("note",))

    assert "note" not in schema["properties"]


# -- OpenApiServiceProvider over HTTP --------------------------------------------------


async def test_openapi_json_is_served_and_reflects_registered_routes(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    @app.get("/ping")
    async def ping(request):
        return JSONResponse({"ok": True})

    app.register(OpenApiServiceProvider(app, title="Widget API", version="1.2.3"))

    async with client(app) as http:
        response = await http.get("/openapi.json")
        assert response.status_code == 200
        body = response.json()
        assert body["info"]["title"] == "Widget API"
        assert body["info"]["version"] == "1.2.3"
        assert "/ping" in body["paths"]
        assert "/openapi.json" in body["paths"]  # the endpoint documents itself, too


async def test_docs_serves_a_swagger_ui_page(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    app.register(OpenApiServiceProvider(app, title="Widget API"))

    async with client(app) as http:
        response = await http.get("/docs")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "swagger-ui" in response.text
        assert "/openapi.json" in response.text


async def test_disabling_openapi_removes_both_routes(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("OPENAPI_ENABLED=false\n")
    app = _make_app(tmp_path)
    app.register(OpenApiServiceProvider(app, title="Widget API"))

    async with client(app) as http:
        assert (await http.get("/openapi.json")).status_code == 404
        assert (await http.get("/docs")).status_code == 404


async def test_json_and_docs_paths_are_configurable(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("OPENAPI_JSON_PATH=/schema.json\nOPENAPI_DOCS_PATH=/api-docs\n")
    app = _make_app(tmp_path)
    app.register(OpenApiServiceProvider(app, title="Widget API"))

    async with client(app) as http:
        assert (await http.get("/schema.json")).status_code == 200
        assert (await http.get("/api-docs")).status_code == 200
        assert (await http.get("/openapi.json")).status_code == 404

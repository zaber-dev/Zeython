"""OpenAPI spec generation and an interactive Swagger UI, built from the
app's actually-registered routes.

This is deliberately *not* FastAPI-style automatic request/response
validation from type hints -- Zeython's handlers take a plain `request`
and call `request.json()` themselves, and models validate via `__rules__`
(see docs/validation.md), not typed request models. Rearchitecting that to
get automatic schema inference would be a much bigger, separate change,
and would fight the framework's existing conventions rather than describe
them. What this module does instead: read the routes actually registered
on the router (the same technique `zeython.mcp.introspect.describe_routes`
uses) and build an OpenAPI document from them, enriched by an optional
`@describe(...)` decorator for handlers that want a real summary, tags, or
request/response schema instead of a generic placeholder.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Float, Integer
from sqlalchemy import inspect as sa_inspect
from starlette.responses import HTMLResponse, JSONResponse

from zeython.providers import ServiceProvider
from zeython.routing import Endpoint

if TYPE_CHECKING:
    from zeython.application import Application
    from zeython.db import Model

_PATH_PARAM_RE = re.compile(r"\{(\w+)(?::(\w+))?\}")
_CONVERTER_SCHEMAS: dict[str, dict[str, str]] = {
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "uuid": {"type": "string", "format": "uuid"},
    "path": {"type": "string"},
    "str": {"type": "string"},
}


def describe(
    *,
    summary: str | None = None,
    tags: list[str] | None = None,
    request_body: dict[str, Any] | None = None,
    responses: dict[int, dict[str, Any]] | None = None,
) -> Callable[[Endpoint], Endpoint]:
    """Attach OpenAPI metadata to a route handler, read by :func:`generate_openapi`.

    Without this, a route still appears in the generated spec — just with
    a generic "Successful response" 200 and no summary/tags::

        @describe(
            summary="List posts",
            tags=["posts"],
            responses={200: {"description": "The post list", "content": {
                "application/json": {"schema": {"type": "array", "items": model_schema(Post)}},
            }}},
        )
        async def index(self, request): ...

    Works on both function-based routes and ``Controller`` methods —
    attaches to the underlying function, which bound-method attribute
    lookup falls through to automatically.
    """

    def decorator(fn: Endpoint) -> Endpoint:
        fn._openapi = {  # type: ignore[attr-defined]
            "summary": summary,
            "tags": tags or [],
            "request_body": request_body,
            "responses": responses or {},
        }
        return fn

    return decorator


def model_schema(model_cls: type[Model], *, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    """A JSON Schema object for ``model_cls``'s mapped columns, for use in
    ``@describe(request_body=...)``/``responses=...``.

    Excludes ``model_cls.__hidden__`` (e.g. ``password_hash``) automatically
    — the same fields :meth:`~zeython.db.Model.to_dict` never serializes
    shouldn't show up as "here's the shape of this response" either. This
    is documentation, not enforcement: nothing checks an actual response
    body against it.
    """
    mapper = sa_inspect(model_cls)
    hidden = set(getattr(model_cls, "__hidden__", ())) | set(exclude)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for column in mapper.columns:
        if column.name in hidden:
            continue
        properties[column.name] = _column_schema(column.type)
        if not column.nullable and column.default is None and not column.primary_key:
            required.append(column.name)

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _column_schema(column_type: Any) -> dict[str, str]:
    if isinstance(column_type, Boolean):
        return {"type": "boolean"}
    if isinstance(column_type, DateTime):
        return {"type": "string", "format": "date-time"}
    if isinstance(column_type, Integer):
        return {"type": "integer"}
    if isinstance(column_type, Float):
        return {"type": "number"}
    return {"type": "string"}


def _openapi_path_and_params(path: str) -> tuple[str, list[dict[str, Any]]]:
    """Convert a Starlette path template to an OpenAPI one, plus its path parameters.

    Starlette allows a type converter (``{id:int}``); OpenAPI's path
    template only ever uses ``{id}``, with the type described separately
    in ``parameters``.
    """
    parameters = []
    for name, converter in _PATH_PARAM_RE.findall(path):
        schema = _CONVERTER_SCHEMAS.get(converter or "str", {"type": "string"})
        parameters.append({"name": name, "in": "path", "required": True, "schema": schema})
    openapi_path = _PATH_PARAM_RE.sub(r"{\1}", path)
    return openapi_path, parameters


def _build_operation(meta: dict[str, Any], parameters: list[dict[str, Any]]) -> dict[str, Any]:
    operation: dict[str, Any] = {}
    if parameters:
        operation["parameters"] = parameters
    if meta.get("summary"):
        operation["summary"] = meta["summary"]
    if meta.get("tags"):
        operation["tags"] = meta["tags"]
    if meta.get("request_body"):
        operation["requestBody"] = {"content": {"application/json": {"schema": meta["request_body"]}}}

    responses = meta.get("responses") or {}
    operation["responses"] = (
        {str(code): body for code, body in responses.items()}
        if responses
        else {"200": {"description": "Successful response"}}
    )
    return operation


def generate_openapi(
    app: Application, *, title: str, version: str = "1.0.0", description: str | None = None
) -> dict[str, Any]:
    """Build an OpenAPI 3.0 document from every route currently on ``app.router``.

    Reads the router directly (the same technique
    ``zeython.mcp.introspect.describe_routes`` uses), not a separately
    maintained route list — the spec always reflects what's actually
    registered, not what the source *looks like* it registers.

    Routes mounted via ``Router.mount()``/``.include()`` (``StaticFiles``,
    a nested sub-router) aren't recursed into and don't appear — this
    covers directly-registered routes only, a v1 scope limitation, not an
    oversight.
    """
    paths: dict[str, dict[str, Any]] = {}

    for route in app.router.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path is None or not methods:
            continue

        endpoint = getattr(route, "endpoint", None)
        meta = getattr(endpoint, "_openapi", {}) if endpoint is not None else {}
        openapi_path, parameters = _openapi_path_and_params(path)
        operations = paths.setdefault(openapi_path, {})

        for method in sorted(methods):
            if method in ("HEAD", "OPTIONS"):
                continue
            operations[method.lower()] = _build_operation(meta, parameters)

    info: dict[str, Any] = {"title": title, "version": version}
    if description:
        info["description"] = description

    return {"openapi": "3.0.3", "info": info, "paths": paths}


_SWAGGER_UI_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{title} &middot; API Docs</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css" />
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.onload = () => {{
      window.ui = SwaggerUIBundle({{ url: "{openapi_url}", dom_id: "#swagger-ui" }});
    }};
  </script>
</body>
</html>
"""


class OpenApiServiceProvider(ServiceProvider):
    """Serves a generated OpenAPI document and an interactive Swagger UI.

    Not registered by default — opt in once your routes exist (register
    after ``RouteServiceProvider``, order otherwise doesn't matter)::

        app.register(RouteServiceProvider(app, modules=("routes.web",)))
        app.register(OpenApiServiceProvider(app, title="My API"))

    ``.env``:

    - ``OPENAPI_ENABLED`` — default ``true`` once registered; set ``false``
      to register the provider (so ``generate_openapi`` is still usable
      programmatically) without exposing the two routes, e.g. in production.
    - ``OPENAPI_JSON_PATH`` — default ``/openapi.json``
    - ``OPENAPI_DOCS_PATH`` — default ``/docs``

    Swagger UI loads from a CDN — unlike the Tailwind Play CDN
    (see docs/frontend.md), this is a static asset bundle, not something
    recompiled per request, so there's no dev-only caveat for using it in
    production too.
    """

    def __init__(self, app: Application, *, title: str, version: str = "1.0.0", description: str | None = None) -> None:
        super().__init__(app)
        self.title = title
        self.version = version
        self.description = description

    def boot(self) -> None:
        if not bool(self.config.get("openapi.enabled", True)):
            return

        json_path = self.config.get("openapi.json_path", "/openapi.json")
        docs_path = self.config.get("openapi.docs_path", "/docs")

        async def openapi_json(request: Any) -> JSONResponse:
            spec = generate_openapi(self.app, title=self.title, version=self.version, description=self.description)
            return JSONResponse(spec)

        async def docs(request: Any) -> HTMLResponse:
            return HTMLResponse(_SWAGGER_UI_HTML.format(title=self.title, openapi_url=json_path))

        self.app.get(json_path, name="openapi.json")(openapi_json)
        self.app.get(docs_path, name="openapi.docs")(docs)


__all__ = ["describe", "model_schema", "generate_openapi", "OpenApiServiceProvider"]

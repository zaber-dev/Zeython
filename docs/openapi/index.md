# OpenAPI & API Docs

`zeython.openapi` generates an OpenAPI 3.0 document from the routes actually registered on your app, and serves it alongside an interactive Swagger UI. `zeython new` wires this in by default — visit `/docs` on a running app.

## What this is, and what it deliberately isn't

This is **not** FastAPI-style automatic request/response validation from type hints. A Zeython handler takes a plain `request` and calls `request.json()` itself; a model validates via `__rules__` (see [Validation](https://zeython.zaber.dev/docs/validation/index.md)), not a typed request model. Rearchitecting that to get automatic schema inference the way FastAPI does would be a much bigger, separate change — and would fight the framework's existing conventions rather than describe them.

What this module actually does: read the routes registered on `app.router` (the same technique the [AI Agents](https://zeython.zaber.dev/docs/ai-agents/index.md) MCP server's `list_routes` uses) and build an OpenAPI document from them. Every route appears, even with no annotation at all — with a generic "Successful response" 200. The optional `@describe(...)` decorator is how you give a route a real summary, tags, or request/response schema instead.

## Setup

Registered by default in a generated project:

```python
app.register(OpenApiServiceProvider(app, title=app.config.app_name))
```

Visit `/docs` for the Swagger UI, `/openapi.json` for the raw spec.

## Describing a route

```python
from zeython.openapi import describe, model_schema
from app.Models.post import Post

_POST_SCHEMA = model_schema(Post)

class PostController(Controller):
    @describe(
        summary="List posts",
        tags=["posts"],
        responses={200: {
            "description": "The post list",
            "content": {"application/json": {"schema": {"type": "array", "items": _POST_SCHEMA}}},
        }},
    )
    async def index(self, request): ...
```

`@describe` works on both function-based routes and `Controller` methods — it attaches to the underlying function, and Python's bound-method attribute lookup falls through to it automatically, so it survives being wrapped as `instance.index` inside `Router.resource()`.

## `model_schema()`

A convenience for building the JSON Schema fragments `@describe` takes, from a model's actual mapped columns:

```python
model_schema(Post)
# {"type": "object", "properties": {"id": {"type": "integer"}, "title": {"type": "string"}, ...}, "required": [...]}
```

Automatically excludes `__hidden__` fields (`password_hash`, etc.) — the same fields `to_dict()` never serializes shouldn't show up as "here's the shape of this response" either. This is documentation, generated once when the module loads — nothing checks an actual response body against it at request time.

## Configuration

```text
OPENAPI_ENABLED=true       # false to register the provider without exposing the routes
OPENAPI_JSON_PATH=/openapi.json
OPENAPI_DOCS_PATH=/docs
```

Set `OPENAPI_ENABLED=false` to keep `generate_openapi()` usable programmatically (e.g. to write `openapi.json` to a file as part of a build step) without exposing `/docs`/`/openapi.json` over HTTP — a reasonable choice in production if you don't want your API surface publicly browsable.

Swagger UI loads from a CDN (`swagger-ui-dist`), same zero-setup approach as [the Tailwind welcome page](https://zeython.zaber.dev/docs/frontend/index.md) — but unlike Tailwind's Play CDN, this is a static asset bundle, not something recompiled on every page load, so there's no dev-only caveat here.

## Scope limits

- Routes mounted via `Router.mount()`/`.include()` (`StaticFiles`, a nested sub-router) aren't recursed into and don't appear in the spec — directly registered routes only.
- Path parameters get a schema from a Starlette type converter if you used one (`{id:int}` → `integer`); an untyped `{id}` defaults to `string`.
- There's no request-body *validation* here, only *documentation* — the `request_body`/`responses` you pass to `@describe` describe what your handler is supposed to do, and nothing enforces that it matches.

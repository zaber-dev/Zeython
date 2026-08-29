# GraphQL

`zeython.graphql` serves a GraphQL endpoint built on
[`graphql-core`](https://graphql-core-3.readthedocs.io/), the pure-Python
reference GraphQL implementation. Zeython owns the transport — the
endpoint, request parsing, error formatting, and an optional interactive
GraphiQL UI. You own the schema.

Not registered by default, and `graphql-core` is an optional dependency —
install it with:

```bash
pip install zeython[graphql]
```

## What this is, and what it deliberately isn't

This is **not** Strawberry- or Ariadne-style automatic schema generation
from type-hinted Python classes — the same reasoning
[`zeython.openapi`](openapi.md) gives for not auto-generating request
models from type hints applies here too. You build a `graphql.GraphQLSchema`
however `graphql-core` lets you: programmatically with `GraphQLObjectType`/
`GraphQLField`, or from an SDL string via `graphql.build_schema()` with
resolvers attached afterward. Zeython just executes queries against
whichever one you hand it.

## Setup

```python
# app/graphql/schema.py
from graphql import GraphQLField, GraphQLObjectType, GraphQLSchema, GraphQLString

async def resolve_hello(root, info, name="World"):
    return f"Hello, {name}!"

query_type = GraphQLObjectType(
    name="Query",
    fields={"hello": GraphQLField(GraphQLString, args={"name": GraphQLString}, resolve=resolve_hello)},
)

schema = GraphQLSchema(query=query_type)
```

```python
# main.py
from zeython import Application, GraphQLServiceProvider
from app.graphql.schema import schema

app = Application()
app.register(GraphQLServiceProvider(app, schema=schema))
```

```bash
curl -X POST http://localhost:8000/graphql \
  -H 'Content-Type: application/json' \
  -d '{"query": "{ hello(name: \"Ada\") }"}'
# {"data": {"hello": "Hello, Ada!"}}
```

A single route (default `/graphql`) handles both verbs: `POST` executes a
query/mutation from a JSON body (`query`, optional `variables`/
`operationName`); `GET` serves the interactive GraphiQL UI, when enabled.

## Reaching your app's services from a resolver

Every resolver's `info.context` is a dict with `request` (the current
`starlette.requests.Request`) and `container` (the app's
[`Container`](architecture.md)) — the same things a plain HTTP handler
already has, just handed to resolvers instead of read off the request
directly:

```python
async def resolve_me(root, info):
    request = info.context["request"]
    return current_user(request)

async def resolve_posts(root, info):
    return await Post.all()  # a Model query works the same as anywhere else --
                              # the request-scoped session is already open
```

## The GraphiQL UI

```python
GraphQLServiceProvider(app, schema=schema, graphiql=True)
```

`graphiql` defaults to `app.config.debug` — visible locally, off in
production, the same default [Swagger UI](openapi.md) and the
[HTML debug error page](api-standards.md#debug-mode-a-browsable-html-error-page)
use, since it exposes your whole schema and lets anyone run arbitrary
queries against it. Pass `graphiql=True`/`False` explicitly to override
that default in either direction. Loads React and GraphiQL from a CDN,
same zero-setup approach as Swagger UI — a static asset bundle, not
something recompiled per request.

With `graphiql` off (the production default), a `GET` request to the
endpoint gets a `405` instead of the UI.

## Configuration

```python
GraphQLServiceProvider(
    app,
    schema=schema,
    path="/graphql",   # default
    graphiql=None,     # default: falls back to app.config.debug
)
```

## Errors

`execute_graphql()` — the function the service provider calls, also usable
directly (e.g. from a console command, or a test) — always returns `200`
from the HTTP endpoint, with the GraphQL-over-HTTP-standard body shape:

```json
{"data": {"hello": null}, "errors": [{"message": "...", "path": ["hello"], "locations": [...]}]}
```

`errors` is only present when at least one occurred — a query syntax error,
a resolver that raised, or a value that failed the schema's own
validation. This is GraphQL convention, not a Zeython choice: a GraphQL
request can partially succeed (some fields resolved, one didn't), which a
single HTTP status code can't represent — the client always reads
`errors`, the same way it always reads `data`.

A request with a body that isn't valid JSON, or is JSON but has no
`query` field, gets a `400` — that's malformed at the transport level,
before GraphQL execution ever starts.

## Scope limits

Single-schema, single-endpoint, query/mutation execution — no schema
stitching or federation across services, no subscriptions (GraphQL's
WebSocket-based push model; see [WebSockets](websockets.md) for Zeython's
own real-time primitives if you need push today), and no response-level
query cost limiting. For an API with those requirements, or a schema
large enough to want to split across teams/services, a dedicated GraphQL
gateway is a better fit than growing this module to match it.

## API reference

See [`zeython.graphql`](reference/http-api.md) for the full API.

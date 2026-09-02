"""A GraphQL endpoint built on graphql-core, the pure-Python reference
GraphQL implementation.

Zeython owns the transport: the ``/graphql`` endpoint, request parsing,
error formatting, and an optional interactive GraphiQL UI in debug mode.
Your app owns the schema -- built however ``graphql-core`` lets you build
one (programmatically with ``GraphQLObjectType``, or from SDL via
``graphql.build_schema()`` with resolvers attached afterward). There's no
FastAPI/Strawberry-style automatic type-hint-to-schema generation here,
for the same reason ``zeython.openapi`` doesn't auto-generate request
models: it would fight the framework's existing conventions rather than
describe them.

``graphql-core`` is an optional dependency (``pip install
zeython[graphql]``), not a default one -- most apps don't need a GraphQL
API alongside their REST one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from zeython.exceptions import BadRequestException, MethodNotAllowedException
from zeython.providers import ServiceProvider

if TYPE_CHECKING:
    from graphql import GraphQLSchema

    from zeython.application import Application


async def execute_graphql(
    schema: GraphQLSchema,
    *,
    query: str,
    variables: dict[str, Any] | None = None,
    operation_name: str | None = None,
    context_value: Any = None,
) -> dict[str, Any]:
    """Execute a single GraphQL query/mutation against ``schema``.

    Returns a ``{"data": ..., "errors": [...]}`` body per the GraphQL-over-HTTP
    spec -- ``errors`` is only present when at least one occurred.

    Raises ``ImportError`` with a ``pip install zeython[graphql]`` hint if
    ``graphql-core`` isn't installed.
    """
    try:
        from graphql import graphql
    except ImportError as exc:
        raise ImportError(
            "zeython.graphql requires graphql-core -- install it with `pip install zeython[graphql]`."
        ) from exc

    result = await graphql(
        schema,
        source=query,
        variable_values=variables,
        operation_name=operation_name,
        context_value=context_value,
    )

    body: dict[str, Any] = {"data": result.data}
    if result.errors:
        body["errors"] = [error.formatted for error in result.errors]
    return body


_GRAPHIQL_HTML = """<!doctype html>
<html>
<head>
  <title>GraphiQL</title>
  <style>body {{ height: 100%; margin: 0; width: 100%; overflow: hidden; }}
  #graphiql {{ height: 100vh; }}</style>
  <script crossorigin src="https://cdn.jsdelivr.net/npm/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://cdn.jsdelivr.net/npm/react-dom@18/umd/react-dom.production.min.js"></script>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/graphiql/graphiql.min.css" />
</head>
<body>
  <div id="graphiql">Loading GraphiQL...</div>
  <script src="https://cdn.jsdelivr.net/npm/graphiql/graphiql.min.js" type="application/javascript"></script>
  <script>
    const root = ReactDOM.createRoot(document.getElementById("graphiql"));
    root.render(
      React.createElement(GraphiQL, {{
        fetcher: GraphiQL.createFetcher({{ url: {graphql_url!r} }}),
      }}),
    );
  </script>
</body>
</html>
"""


class GraphQLServiceProvider(ServiceProvider):
    """Serves a GraphQL endpoint for a schema you provide.

    ```python
    # main.py
    from zeython import Application, GraphQLServiceProvider
    from app.graphql.schema import schema  # a graphql.GraphQLSchema you build

    app = Application()
    app.register(GraphQLServiceProvider(app, schema=schema))
    ```

    A single route (default ``/graphql``) handles both verbs: ``POST``
    executes a query/mutation from a JSON body (``query``, optional
    ``variables``/``operationName``); ``GET`` serves an interactive
    GraphiQL UI, when enabled.

    Every resolver's ``info.context`` is a dict with ``request`` (the
    current ``starlette.requests.Request``) and ``container`` (the app's
    :class:`~zeython.container.Container`, for pulling out anything else
    a resolver needs -- a service, ``current_user()``, the database
    session) -- the same shape a request handler already has, just handed
    to resolvers instead of read off the request directly.

    ``graphiql`` defaults to ``self.config.debug`` -- on locally, off in
    production, the same default ``zeython.openapi``'s Swagger UI and the
    HTML debug error page use, since it exposes your full schema and lets
    anyone run arbitrary queries against it.
    """

    def __init__(
        self,
        app: Application,
        *,
        schema: GraphQLSchema,
        path: str = "/graphql",
        graphiql: bool | None = None,
    ) -> None:
        super().__init__(app)
        self.schema = schema
        self.path = path
        self._graphiql = graphiql

    def boot(self) -> None:
        graphiql_enabled = self._graphiql if self._graphiql is not None else self.config.debug

        async def endpoint(request: Request) -> Response:
            if request.method == "GET":
                if not graphiql_enabled:
                    raise MethodNotAllowedException("GraphiQL is disabled -- send a POST request instead.")
                return HTMLResponse(_GRAPHIQL_HTML.format(graphql_url=self.path))

            try:
                payload = await request.json()
            except ValueError as exc:
                raise BadRequestException(f"Malformed JSON request body: {exc}") from exc
            if not isinstance(payload, dict):
                raise BadRequestException("A GraphQL request body must be a JSON object.")

            query = payload.get("query")
            if not isinstance(query, str) or not query:
                raise BadRequestException("A GraphQL request body must include a non-empty string 'query' field.")

            variables = payload.get("variables")
            if variables is not None and not isinstance(variables, dict):
                raise BadRequestException("A GraphQL request's 'variables' must be a JSON object.")

            body = await execute_graphql(
                self.schema,
                query=query,
                variables=variables,
                operation_name=payload.get("operationName"),
                context_value={"request": request, "container": request.app.state.container},
            )
            return JSONResponse(body)

        self.app.router.route(self.path, ["GET", "POST"], name="graphql")(endpoint)


__all__ = ["execute_graphql", "GraphQLServiceProvider"]

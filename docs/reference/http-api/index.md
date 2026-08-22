# HTTP & APIs

Rate limiting, ETags, gzip compression, request correlation IDs, and OpenAPI schema generation.

## rate_limit

Rate limiting: an in-memory sliding-window limiter by default, a per-route `throttle()` guard, and an opt-in blanket middleware.

The in-memory backend is process-local by design — correct for a single worker, and a real (if common) limitation once you run multiple processes or machines, where each would count independently. That's a documented trade-off, not an oversight: :class:`RedisRateLimiter` is the opt-in, shared alternative for when you need distributed limits.

### RateLimiter

Bases: `ABC`

Counts hits against a key within a rolling time window.

#### hit

```python
hit(
    key: str, *, limit: int, window: float
) -> RateLimitResult
```

Record a hit for `key` and report whether it's within `limit` per `window` seconds.

Source code in `src/zeython/rate_limit.py`

```python
@abstractmethod
async def hit(self, key: str, *, limit: int, window: float) -> RateLimitResult:
    """Record a hit for ``key`` and report whether it's within ``limit`` per ``window`` seconds."""
```

### InMemoryRateLimiter

```python
InMemoryRateLimiter(
    *, clock: Callable[[], float] = time.monotonic
)
```

Bases: `RateLimiter`

A sliding-window-log limiter, correct and simple, scoped to one process.

Each key keeps a deque of hit timestamps; on every call, timestamps older than the window are dropped before counting. A single lock serializes hits — fine here since each check is a handful of in-memory operations, not I/O.

Source code in `src/zeython/rate_limit.py`

```python
def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
    self._hits: dict[str, deque[float]] = defaultdict(deque)
    self._lock = asyncio.Lock()
    self._clock = clock
```

### RedisRateLimiter

```python
RedisRateLimiter(
    url: str, *, prefix: str = "zeython:ratelimit:"
)
```

Bases: `RateLimiter`

A Redis-backed :class:`RateLimiter`, shared across every process/machine pointed at the same Redis — the limitation :class:`InMemoryRateLimiter`'s docstring names. Requires the `redis` extra (`pip install zeython[redis]`).

Fixed-window (`INCR` + `EXPIRE`), not sliding-window-log like `InMemoryRateLimiter` — the standard, well-known Redis rate-limiting pattern, and its standard trade-off: a client can get up to `2x limit` requests through across a window boundary (e.g. a burst just before the window resets, then another just after). Accept that, or implement a sliding-window version yourself if you need the tighter guarantee.

All keys are namespaced under `prefix` (default `"zeython:ratelimit:"`) — safe to point at a Redis instance shared with other subsystems.

Source code in `src/zeython/rate_limit.py`

```python
def __init__(self, url: str, *, prefix: str = "zeython:ratelimit:") -> None:
    try:
        from redis.asyncio import Redis
    except ImportError as exc:
        raise ImportError(
            "RedisRateLimiter requires the redis package. Install it with: pip install zeython[redis]"
        ) from exc

    self._client = Redis.from_url(url)
    self._prefix = prefix
```

### RateLimitMiddleware

```python
RateLimitMiddleware(
    app: object,
    *,
    limiter: RateLimiter,
    limit: int,
    window: float,
)
```

Pure ASGI middleware applying a blanket per-IP limit to every request.

Source code in `src/zeython/rate_limit.py`

```python
def __init__(self, app: object, *, limiter: RateLimiter, limit: int, window: float) -> None:
    self.app = app
    self.limiter = limiter
    self.limit = limit
    self.window = window
```

### RateLimitHeadersMiddleware

```python
RateLimitHeadersMiddleware(app: object)
```

Pure ASGI middleware that stamps the standard `X-RateLimit-Limit`/ `X-RateLimit-Remaining`/`X-RateLimit-Reset` headers (as GitHub's, Stripe's, and Laravel's APIs do) onto every response for which a rate limiter actually ran -- whether that was a per-route :func:`throttle` call or the blanket :class:`RateLimitMiddleware`.

Both of those store their :class:`RateLimitResult` on `request.state` (backed by `scope["state"]`, read here directly since a plain ASGI middleware has no `Request` of its own); a handler that never calls either leaves no result to report, so no headers are added. Registered automatically -- and unconditionally, since :func:`throttle` works without the blanket middleware being enabled -- by :class:`RateLimitServiceProvider`.

Source code in `src/zeython/rate_limit.py`

```python
def __init__(self, app: object) -> None:
    self.app = app
```

### RateLimitServiceProvider

```python
RateLimitServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Binds a :class:`RateLimiter` into the container. :class:`InMemoryRateLimiter` (process-local) by default.

The limiter is always available for :func:`throttle` calls in your own handlers. The blanket, all-routes middleware is opt-in via `.env`:

- `RATE_LIMIT_ENABLED` — default `false`
- `RATE_LIMIT_MAX_REQUESTS` — default `60`
- `RATE_LIMIT_WINDOW_SECONDS` — default `60`

For a shared, distributed limiter, bind :class:`RedisRateLimiter` instead of registering this provider::

```text
app.container.singleton(RateLimiter, lambda: RedisRateLimiter(config.get("redis.url")))
```

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

### client_ip

```python
client_ip(request: Request) -> str
```

The connecting client's IP, or `"unknown"` if the ASGI server didn't report one.

Source code in `src/zeython/rate_limit.py`

```python
def client_ip(request: Request) -> str:
    """The connecting client's IP, or ``"unknown"`` if the ASGI server didn't report one."""
    return request.client.host if request.client else "unknown"
```

### throttle

```python
throttle(
    request: Request,
    *,
    key: str | None = None,
    limit: int,
    window: float,
) -> None
```

Raise :class:`~zeython.exceptions.TooManyRequestsException` past `limit` hits per `window` seconds.

Defaults to limiting per client IP; pass `key` to scope it differently (e.g. `f"login:{client_ip(request)}"` to namespace it separately from other throttled endpoints, or `f"login:{email}"` to limit attempts per account regardless of source IP). Call at the top of any handler you want to protect::

```text
async def login(self, request):
    await throttle(request, limit=5, window=60)  # 5 attempts/minute per IP
```

Every response -- allowed or rejected -- carries the standard `X-RateLimit-Limit`/`X-RateLimit-Remaining`/`X-RateLimit-Reset` headers, added by :class:`RateLimitHeadersMiddleware` (registered automatically by :class:`RateLimitServiceProvider`).

Source code in `src/zeython/rate_limit.py`

```python
async def throttle(request: Request, *, key: str | None = None, limit: int, window: float) -> None:
    """Raise :class:`~zeython.exceptions.TooManyRequestsException` past ``limit`` hits per ``window`` seconds.

    Defaults to limiting per client IP; pass ``key`` to scope it differently
    (e.g. ``f"login:{client_ip(request)}"`` to namespace it separately from
    other throttled endpoints, or ``f"login:{email}"`` to limit attempts per
    account regardless of source IP). Call at the top of any handler you
    want to protect::

        async def login(self, request):
            await throttle(request, limit=5, window=60)  # 5 attempts/minute per IP

    Every response -- allowed or rejected -- carries the standard
    ``X-RateLimit-Limit``/``X-RateLimit-Remaining``/``X-RateLimit-Reset``
    headers, added by :class:`RateLimitHeadersMiddleware` (registered
    automatically by :class:`RateLimitServiceProvider`).
    """
    limiter: RateLimiter = request.app.state.container.make(RateLimiter)
    effective_key = key or f"ip:{client_ip(request)}"
    result = await limiter.hit(effective_key, limit=limit, window=window)
    # RateLimitHeadersMiddleware reads this to stamp X-RateLimit-* on
    # whatever response eventually gets sent -- the normal one below, or
    # (via the exception handler) the 429 raised just below.
    request.state.rate_limit_result = result

    if not result.allowed:
        retry_after = int(result.retry_after) + 1
        raise TooManyRequestsException(
            f"Too many requests. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )
```

## etag

Conditional GETs: an `ETag` on a cacheable response, and a `304 Not Modified` (empty body) when the client's `If-None-Match` already matches it -- for a GET/HEAD response that doesn't change on every request (a list endpoint between writes, a lookup table), this saves the client (and the network) the cost of re-downloading a body it already has. See docs/api-standards.md.

### ETagMiddleware

```python
ETagMiddleware(app: Any, *, minimum_size: int = 0)
```

Pure ASGI middleware. Buffers a `GET`/`HEAD` response's full body (so it necessarily holds the whole thing in memory -- fine for a typical JSON API response, a poor fit in front of a large file download or a streaming response; scope this middleware to specific routes, or use :class:`~zeython.storage.Storage` for downloads instead of running it in front of everything, if that's a concern), computes a strong `ETag` (a SHA-256 hash of the body) for any `200` response at or above `minimum_size` bytes, and short-circuits to `304 Not Modified` when the request's `If-None-Match` already matches it.

Source code in `src/zeython/etag.py`

```python
def __init__(self, app: Any, *, minimum_size: int = 0) -> None:
    self.app = app
    self.minimum_size = minimum_size
```

### ETagServiceProvider

```python
ETagServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Registers :class:`ETagMiddleware` -- not registered by default::

```text
# main.py
app.register(ETagServiceProvider)
```

Configurable via `.env`:

- `ETAG_MINIMUM_SIZE` -- default `0` (every 200 response gets an ETag). Raise it to skip the hashing cost for tiny responses that aren't worth caching.

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

## gzip

Response compression: wires Starlette's own `GZipMiddleware` in as an opt-in provider, configurable via `.env` instead of a bare `app.add_middleware(GZipMiddleware, ...)` call. See docs/api-standards.md.

### GzipServiceProvider

```python
GzipServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Compresses any response at or above `GZIP_MINIMUM_SIZE` bytes whose client sent `Accept-Encoding: gzip` -- not registered by default::

```text
# main.py
app.register(GzipServiceProvider)
```

Configurable via `.env`:

- `GZIP_MINIMUM_SIZE` -- default `500`. Responses smaller than this aren't worth the CPU cost of compressing.
- `GZIP_COMPRESS_LEVEL` -- default `9` (Starlette's own default; 1 is fastest/least compression, 9 is slowest/most).

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

## request_id

Correlation IDs for tracing one request across a busy log stream.

A single request can produce several log lines -- received, a DB query, maybe a background job dispatched, the response sent -- and without something tying them together, reconstructing "what happened for this one request" from concurrent traffic is guesswork. `RequestIdMiddleware` stamps every request/response pair with an ID (the caller's own `X-Request-ID` if it sent one, so a request can be traced across multiple services that all honor the same header, otherwise a fresh UUID4) and makes it available to every log line emitted while handling that request.

### RequestIdLogFilter

Bases: `Filter`

Adds the current request's ID to every `LogRecord` as `request_id`.

Installed on the root logger's handlers automatically by :class:`RequestIdServiceProvider`, so `%(request_id)s` is available to any formatter -- `"-"` for a log line emitted outside of a request (startup, a scheduled job) rather than a missing attribute. Deliberately attached to each *handler*, not the logger itself: a `Logger.filter` only runs for records that logger originates directly, never for ones propagated up from a child logger (`uvicorn.error`, your own `__name__` loggers) -- which is most of them.

### RequestIdMiddleware

```python
RequestIdMiddleware(
    app: Any, *, header_name: str = DEFAULT_HEADER_NAME
)
```

Pure ASGI middleware: stamps every request/response with a correlation ID.

Sets the ID as a contextvar for the duration of the request -- readable via :func:`request_id` from any code running while handling it, including a logging filter -- and echoes it back as a response header so a client can correlate its own logs with the server's.

Source code in `src/zeython/request_id.py`

```python
def __init__(self, app: Any, *, header_name: str = DEFAULT_HEADER_NAME) -> None:
    self.app = app
    self.header_name = header_name
    self._header_key = header_name.lower().encode("latin-1")
```

### RequestIdServiceProvider

```python
RequestIdServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Registers :class:`RequestIdMiddleware` and wires up its logging context.

Registered by default in a generated project -- unlike :class:`~zeython.security_headers.SecurityHeadersServiceProvider`, there is no application-specific default to get wrong here: it only adds a response header and a piece of log context, never changes what a request is allowed to do.

- `REQUEST_ID_HEADER` -- default `X-Request-ID`.

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

### request_id

```python
request_id() -> str | None
```

The current request's correlation ID, or `None` outside a request.

Source code in `src/zeython/request_id.py`

```python
def request_id() -> str | None:
    """The current request's correlation ID, or ``None`` outside a request."""
    return _current_request_id.get()
```

## openapi

OpenAPI spec generation and an interactive Swagger UI, built from the app's actually-registered routes.

This is deliberately *not* FastAPI-style automatic request/response validation from type hints -- Zeython's handlers take a plain `request` and call `request.json()` themselves, and models validate via `__rules__` (see docs/validation.md), not typed request models. Rearchitecting that to get automatic schema inference would be a much bigger, separate change, and would fight the framework's existing conventions rather than describe them. What this module does instead: read the routes actually registered on the router (the same technique `zeython.mcp.introspect.describe_routes` uses) and build an OpenAPI document from them, enriched by an optional `@describe(...)` decorator for handlers that want a real summary, tags, or request/response schema instead of a generic placeholder.

### OpenApiServiceProvider

```python
OpenApiServiceProvider(
    app: Application,
    *,
    title: str,
    version: str = "1.0.0",
    description: str | None = None,
)
```

Bases: `ServiceProvider`

Serves a generated OpenAPI document and an interactive Swagger UI.

Not registered by default — opt in once your routes exist (register after `RouteServiceProvider`, order otherwise doesn't matter)::

```text
app.register(RouteServiceProvider(app, modules=("routes.web",)))
app.register(OpenApiServiceProvider(app, title="My API"))
```

`.env`:

- `OPENAPI_ENABLED` — default `true` once registered; set `false` to register the provider (so `generate_openapi` is still usable programmatically) without exposing the two routes, e.g. in production.
- `OPENAPI_JSON_PATH` — default `/openapi.json`
- `OPENAPI_DOCS_PATH` — default `/docs`

Swagger UI loads from a CDN — unlike the Tailwind Play CDN (see docs/frontend.md), this is a static asset bundle, not something recompiled per request, so there's no dev-only caveat for using it in production too.

Source code in `src/zeython/openapi.py`

```python
def __init__(self, app: Application, *, title: str, version: str = "1.0.0", description: str | None = None) -> None:
    super().__init__(app)
    self.title = title
    self.version = version
    self.description = description
```

### describe

```python
describe(
    *,
    summary: str | None = None,
    tags: list[str] | None = None,
    request_body: dict[str, Any] | None = None,
    responses: dict[int, dict[str, Any]] | None = None,
) -> Callable[[Endpoint], Endpoint]
```

Attach OpenAPI metadata to a route handler, read by :func:`generate_openapi`.

Without this, a route still appears in the generated spec — just with a generic "Successful response" 200 and no summary/tags::

```text
@describe(
    summary="List posts",
    tags=["posts"],
    responses={200: {"description": "The post list", "content": {
        "application/json": {"schema": {"type": "array", "items": model_schema(Post)}},
    }}},
)
async def index(self, request): ...
```

Works on both function-based routes and `Controller` methods — attaches to the underlying function, which bound-method attribute lookup falls through to automatically.

Source code in `src/zeython/openapi.py`

```python
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
```

### model_schema

```python
model_schema(
    model_cls: type[Model], *, exclude: tuple[str, ...] = ()
) -> dict[str, Any]
```

A JSON Schema object for `model_cls`'s mapped columns, for use in `@describe(request_body=...)`/`responses=...`.

Excludes `model_cls.__hidden__` (e.g. `password_hash`) automatically — the same fields :meth:`~zeython.db.Model.to_dict` never serializes shouldn't show up as "here's the shape of this response" either. This is documentation, not enforcement: nothing checks an actual response body against it.

Source code in `src/zeython/openapi.py`

```python
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
```

### generate_openapi

```python
generate_openapi(
    app: Application,
    *,
    title: str,
    version: str = "1.0.0",
    description: str | None = None,
) -> dict[str, Any]
```

Build an OpenAPI 3.0 document from every route currently on `app.router`.

Reads the router directly (the same technique `zeython.mcp.introspect.describe_routes` uses), not a separately maintained route list — the spec always reflects what's actually registered, not what the source *looks like* it registers.

Routes mounted via `Router.mount()`/`.include()` (`StaticFiles`, a nested sub-router) aren't recursed into and don't appear — this covers directly-registered routes only, a v1 scope limitation, not an oversight.

Source code in `src/zeython/openapi.py`

```python
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
```

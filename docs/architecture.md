# Architecture

## The pieces

| Component | Module | Role |
|---|---|---|
| `Application` | `zeython.application` | The ASGI entry point. Owns the container, config, and router; boots service providers; builds the underlying Starlette app lazily on first use. |
| `Container` | `zeython.container` | A type-hint-driven dependency injection container: `bind`, `singleton`, `instance`, `make`, and `call` (autowired function invocation). |
| `ServiceProvider` | `zeython.providers` | The seam where cross-cutting concerns register bindings (`register()`) and wire themselves up (`boot()`). |
| `Router` | `zeython.routing` | Decorator-based routing (`@app.get(...)`), route groups (`include`), and RESTful `resource()` registration — compiles to Starlette `Route`/`Mount` objects. |
| `Model` | `zeython.db.Model` | An async Active-Record base class: `create`, `find`, `all`, `find_by`, `paginate` (see [Database & Migrations](database.md#pagination)), `save`, `update`, `delete` (soft by default), `to_dict`, plus declarative validation via `__rules__` (see [Validation](validation.md)), overridable lifecycle hooks (`creating`/`created`/`updating`/`updated`/`deleting`/`deleted`, see [Model Events](model-events.md)), and safe relationship eager-loading via `include=` (see [Relationships](relationships.md)). |
| `transaction` | `zeython.db` | A `SAVEPOINT`-scoped nested transaction within the current session, for isolating part of a request's writes without ending it (see [Database & Migrations](database.md#transactions)). |
| `Database.read_replica()` | `zeython.db.Database` | Opens a session against a read replica (`DATABASE_READ_URL`) instead of the primary, for a read-heavy path that can tolerate lag -- falls back to the primary if no replica is configured (see [Database & Migrations](database.md#read-replicas)). |
| `N1QueryDetectionServiceProvider` | `zeython.n_plus_one` | Warns (dev-only, `APP_DEBUG`) when a request fires the same SQL statement shape suspiciously many times -- the N+1 query pattern (see [Relationships](relationships.md#detecting-n1s-automatically)). |
| `Config` | `zeython.config` | Layered `.env` + process-environment configuration with dot-path access (`config.get("database.url")`). |
| `Views` | `zeython.views` | Jinja2 rendering by convention from `resources/views/`, bound via `ViewServiceProvider` (see [Views](views.md)). |
| `CorsServiceProvider` | `zeython.providers` | Opt-in, `.env`-configured CORS support wrapping Starlette's `CORSMiddleware`. |
| `AuthServiceProvider` | `zeython.auth` | Session-based auth: signed-cookie sessions, password hashing, `login`/`logout`/`current_user`/`require_auth`, [CSRF protection](csrf.md) on by default (see [Authentication](authentication.md)). |
| `CsrfMiddleware` | `zeython.csrf` | Double-submit-cookie CSRF protection; bundled with `AuthServiceProvider`, or usable standalone (see [CSRF Protection](csrf.md)). |
| `SecurityHeadersServiceProvider` | `zeython.security_headers` | Opt-in `X-Frame-Options`/`X-Content-Type-Options`/`Referrer-Policy`/CSP/HSTS response headers, `.env`-configured; not registered by default (see [Security Headers](security-headers.md)). |
| `ApiAuthServiceProvider` | `zeython.api_auth` | Stateless bearer-token auth for non-cookie clients: `TokenManager.issue`/`.verify`, `require_api_auth`, signed with `itsdangerous` (no new dependency, no token table) (see [API Authentication](api-authentication.md)). |
| `Gate` | `zeython.authorization` | Named authorization abilities: `gate.define(...)`, resource-bound Policy classes (`gate.policy(...)`), a global bypass hook (`gate.before(...)`), role/permission checks (`HasRoles`, `Gate.role(...)`/`Gate.permission(...)`), and `authorize(request, ability, ...)` (403 on a failed check, 401 if not logged in at all) (see [Authorization](authorization.md)). |
| `OpenApiServiceProvider` | `zeython.openapi` | Generates an OpenAPI 3.0 document from the app's actually-registered routes and serves it plus a Swagger UI (`/openapi.json`, `/docs`); `@describe(...)` adds a real summary/tags/schema to a route (see [OpenAPI & API Docs](openapi.md)). |
| `GzipServiceProvider` / `ETagServiceProvider` | `zeython.gzip` / `zeython.etag` | Response compression and conditional-GET (`ETag`/`If-None-Match` → `304`) support; `API_PROBLEM_JSON=true` switches error responses to RFC 7807's `application/problem+json` shape (see [API Standards](api-standards.md)). |
| `PluginServiceProvider` | `zeython.plugins` | Discovers and registers every third-party provider declared under the `zeython.plugins` entry-point group by an installed package -- one line turns on discovery, not one line per plugin (see [Plugins](plugins.md)). |
| `LocalizationServiceProvider` | `zeython.localization` | Translation strings loaded from `resources/lang/{locale}.json`; `LocaleMiddleware` resolves each request's locale (`?lang=`, then `Accept-Language`, then a default) and makes it available to `t(request, key, ...)`/a `t` Jinja global without threading a request through every call (see [Localization](localization.md)). |
| `Storage` | `zeython.storage` | Backend-agnostic file storage (`LocalStorage` by default, `S3Storage` opt-in) with `store_upload()` for safe, validated uploads (see [File Storage](storage.md)). |
| `RateLimiter` | `zeython.rate_limit` | In-memory sliding-window rate limiting by default: `throttle()` per-route guard, opt-in blanket middleware, applied to auth by default; `RedisRateLimiter` for a shared, distributed limit (see [Rate Limiting](rate-limiting.md), [Redis](redis.md)). |
| `Cache` | `zeython.cache` | An in-memory TTL cache by default: `get`/`put`/`forget`/`has`/`flush`, plus `remember()` for get-or-compute; `RedisCache` for a cache shared across processes/machines (see [Caching](caching.md), [Redis](redis.md)). |
| `Queue` | `zeython.queue` | Background jobs: `Job` + `dispatch()`, `InMemoryQueue` (background task, no lifespan wiring needed) by default, `SyncQueue` for tests, `RedisQueue` (durable, retries with backoff, failed-jobs list, run via `zeython queue work`) for production (see [Background Jobs](queues.md)). |
| `Schedule` | `zeython.schedule` | Recurring tasks defined in code: `schedule.call(fn).daily()`/`.cron(...)`, run via `zeython schedule run` (one cron entry, however many tasks) -- not registered by default (see [Scheduling](scheduling.md)). |
| `Mailer` | `zeython.mail` | Outbound email: `LogMailer` by default (zero setup), `SmtpMailer` opt-in. A job's `handle()` can declare `mailer: Mailer` and get it autowired (see [Mail](mail.md)). |
| `AI` | `zeython.ai` | A swappable LLM client for your own app code: `complete()`, `EchoAI` by default (no credentials), `AnthropicAI` opt-in via the `ai` extra (see [AI](ai.md)). |
| MCP server | `zeython.mcp` | Read-only project introspection for AI coding agents (`zeython mcp`): real registered routes, real mapped models, app info, and search over the bundled docs — an opt-in `mcp` extra, not imported by the framework core (see [AI Agents](ai-agents.md)). |
| `Command` | `zeython.console` | The `app/Console/Commands/` extension point: one `Command` subclass per file, wired to the app's own container/config, run with `zeython command <name>` and listed with `zeython commands` (see [Console Commands](console-commands.md)). |
| `Factory` | `zeython.database.factory` | Model factories for tests and seeding: `make()`/`create()`/`create_many()`, sequence-based uniqueness, no bundled fake-data dependency (see [Factories & Seeders](database-seeding.md)). |
| `Seeder` | `zeython.database.seeder` | The `database/seeders/` extension point: `run()` inserts seed data (typically via a `Factory`), `self.call(...)` composes seeders, run with `zeython db seed` (see [Factories & Seeders](database-seeding.md)). |
| `HealthCheckServiceProvider` | `zeython.health` | Registers `/up`: `200`/`503` with a real database connectivity check when `Database` is bound -- what a load balancer or Kubernetes probe expects (see [Health Check](health-check.md)). |
| `RequestIdServiceProvider` | `zeython.request_id` | Stamps every request/response with a correlation ID (`X-Request-ID`, honoring one the caller already sent) and threads it into the logging context via `request_id()` and `%(request_id)s`; registered by default (see [Observability](observability.md)). |
| `JsonFormatter` | `zeython.logging` | One JSON object per log line instead of the default text line -- `LOG_FORMAT=json` (see [Observability](observability.md)). |
| `ErrorMonitoringServiceProvider` | `zeython.error_monitoring` | Reports unhandled request exceptions, exhausted job retries, and raising scheduled tasks to Sentry -- opt-in, requires the `sentry` extra and `SENTRY_DSN` (see [Error Monitoring](error-monitoring.md)). |
| `WebSocketHub` | `zeython.websockets` | Real-time handlers via `@app.websocket(...)`, built on Starlette's ASGI-native WebSocket support; `WebSocketHub` tracks connections and broadcasts to them, process-local by default (see [WebSockets](websockets.md)). |

## Logging

`Application()` calls `logging.basicConfig()` for you — `APP_DEBUG=true` →
root level `DEBUG`, otherwise `INFO` — and quiets a handful of noisy
third-party loggers (`aiosqlite`, `sqlalchemy.engine`, `asyncio`) to
`WARNING` so they don't drown out your own app's logs. This is skipped
entirely if the root logger already has a handler when `Application()` runs
(you called `logging.basicConfig()` yourself, or your deployment platform
did) — it never overrides an existing setup. Without this, INFO-level logs
(including background job failures — see [Background Jobs](queues.md)) are
silently dropped, since uvicorn only configures its own logger namespaces.

## Boot lifecycle

```python
from zeython import Application, DatabaseServiceProvider, RouteServiceProvider

app = Application()
app.register(DatabaseServiceProvider)
app.register(RouteServiceProvider(app, modules=("routes.web",)))
```

1. `Application()` loads `Config` from `.env`, and creates a `Container` and `Router`.
2. `app.register(provider)` calls the provider's `register()` immediately — this is
   where bindings go into the container. `RouteServiceProvider` imports your route
   modules here, which is how `@app.get("/")` decorators in `routes/web.py` end up
   registered.
3. On the **first** request (or the first `app.asgi` access), `Application` calls
   `boot()` on every registered provider, in registration order, then builds the
   underlying Starlette app from the final route list.

Splitting `register()` from `boot()` matters: a provider's `boot()` can safely
assume every other provider's bindings already exist, regardless of registration
order. `DatabaseServiceProvider`, for example, binds the `Database` object in
`register()` but only attaches the request-scoped session middleware in `boot()`.

## Request-scoped database sessions

Unlike opening a new session per query, Zeython opens exactly one
`AsyncSession` per HTTP request (via `DatabaseSessionMiddleware`), stores it in a
`contextvars.ContextVar`, and commits/rolls back automatically when the request
finishes. `Model` methods pull that session via `current_session()` — you never
pass a session object through your call stack:

```python
class User(Model):
    __tablename__ = "users"
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True)

async def show(self, request):
    user = await User.find(int(request.path_params["id"]))
```

Outside of a request (a script, a test, a REPL), open a session explicitly:

```python
async with database.session():
    user = await User.create(name="Ada", email="ada@example.com")
```

The whole session commits/rolls back around the request; `transaction()`
scopes a `SAVEPOINT` inside it, for a chunk of work that should roll back
on its own without ending the request — see [Transactions](database.md#transactions).

## Routing and controllers

```python
from zeython import Controller

class UserController(Controller):
    async def index(self, request): ...
    async def show(self, request): ...
    async def store(self, request): ...

app.router.resource("/users", UserController, only=("index", "show", "store"))
```

`resource()` maps `index`/`store`/`show`/`update`/`destroy` to the conventional
REST verbs and paths, the same mapping Laravel and Rails use. Function-based routes
via `@app.get("/path")` work exactly like Flask/FastAPI for everything else.

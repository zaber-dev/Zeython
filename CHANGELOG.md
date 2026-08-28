# Changelog

## 2.0.0 — Stable release

Zeython 2.0 went from a Flask + Discord bot application template you cloned
and edited in place, to an installable, async-first, batteries-included MVC
framework with its own CLI — full ORM, auth, authorization, background jobs,
caching, WebSockets, an admin panel, multi-tenancy, localization, and a
real end-to-end tutorial. This release also relicenses the project from
GPL-3.0 to MIT.

### Core

- Installable `zeython` package (`pip install zeython`) with a `src/` layout.
- `Application` — the ASGI entry point, boots service providers lazily.
- `Container` — type-hint-driven dependency injection (`bind`, `singleton`,
  `instance`, `make`, `call`).
- `ServiceProvider` — `register()`/`boot()` lifecycle.
- `Router` / `Controller` — decorator routing, route groups (`include`),
  and RESTful `resource()` registration. `Router.mount()` for arbitrary
  ASGI apps, `Router.websocket()` for WebSocket routes.
- `Model` — async Active-Record base class (SQLAlchemy 2.0 async) with soft
  deletes, audit timestamps, `to_dict()` serialization, safe relationship
  eager-loading (`include=`), lifecycle hooks (`creating`/`created`/etc.),
  pagination, and a dev-only N+1 query detector.
- `Config` — layered `.env` + process-environment configuration.
- HTTP exception hierarchy (`NotFoundException`, `ValidationException`,
  etc.) with a default JSON error handler and RFC 7807 `problem+json`
  responses.
- `transaction()` for `SAVEPOINT`-scoped nested transactions; read-replica
  support (`DATABASE_READ_URL`, `Database.read_replica()`); documented
  connection pooling (`DATABASE_POOL_SIZE`/`DATABASE_MAX_OVERFLOW`).
- Model validation (`__rules__`, built-in `Rule`s: `required`, `email`,
  `min_length`, `max_length`, `one_of`, `matches`).
- An application-level event dispatcher (`zeython.events`) — `emit()`,
  decoupled `listen()` handlers, an `EventServiceProvider` for wiring an
  app's own listeners in one place.
- Feature flags (`zeython.feature_flags`) — static `.env`-driven toggles
  and deterministic percentage rollouts, no database or Redis required;
  `zeython features` lists every defined flag and its current resolution.

### Auth, authorization & security

- Session-based authentication (`AuthServiceProvider`, `login`/`logout`,
  `require_auth`, `current_user`), plus bearer-token API authentication.
- Authorization: `Gate`, `authorize()`, Policy classes, a global
  `before()` hook, and role/permission checks (RBAC).
- CSRF protection, on by default with session auth.
- Rate limiting (`throttle()`, `RateLimitMiddleware`), on by default for
  auth endpoints; `RedisRateLimiter` for distributed deployments.
- Opt-in security response headers (`SecurityHeadersServiceProvider`) and
  WebSocket Origin protection against cross-site hijacking.
- Row-level multi-tenancy (`TenancyServiceProvider`, `as_tenant()`,
  `current_tenant_id()`) — a model opts in with a `tenant_id` column, no
  mixin required.
- Audit logging (`zeython.audit_log`) — `AuditObserver` records every
  create/update/delete of an attached model, with a per-field before/after
  diff, to a `record_model` you own; `AuditActorMiddleware` attributes each
  entry to whichever authentication scheme resolved the request's user,
  with `set_actor()` for background jobs and console commands.
- `SECURITY.md` documenting the vulnerability-reporting process.

### Data & background work

- `zeython.database.factory`/`seeder` — model factories and seeders,
  wired to `zeython make factory|seeder` and `zeython db seed`.
- Background jobs: `InMemoryQueue`/`SyncQueue` plus a durable
  `RedisQueue` with retries, capped exponential backoff, and a
  failed-jobs list; `dispatch()` with real container-based DI for
  `Job.handle()`.
- In-app task scheduler (`zeython.schedule`) — recurring jobs defined in
  code, no separate cron entry needed.
- Outbound mail (`zeython.mail`: `LogMailer`, `SmtpMailer`).
- Multi-channel notifications (`zeython.notifications`) — one `Notification`
  class describes its `mail`/`database`/`broadcast` rendering per
  recipient; `notify()` fires whichever channels it asks for. A failing
  channel is logged and reported, not raised, so one down channel doesn't
  block another.
- A caching layer (`zeython.cache`) plus `RedisCache` for distributed
  deployments.

### Building APIs & real-time

- OpenAPI spec generation and a Swagger UI (`zeython.openapi`).
- WebSocket support: real-time handlers, a broadcast hub
  (`WebSocketHub`), and per-IP connection limiting.
- `RedisWebSocketHub` — distributed broadcast across every process/container
  in a multi-instance deployment, via Redis pub/sub.
- gzip compression and ETags/conditional GETs.
- An MCP server (`zeython.mcp`) exposing route/model introspection and
  docs search to AI coding agents.

### Operability

- `/up` health check and a production-ready `Dockerfile`.
- `zeython down`/`up` maintenance mode (`zeython.maintenance`) — a flag-file
  503 with `Retry-After`, allowed IPs, and a bypass secret, mirroring
  Laravel's `artisan down`/`up`.
- Request/correlation-ID observability (`RequestIdServiceProvider`) and
  optional `LOG_FORMAT=json` structured logging.
- A request/query profiler for debug mode (`zeython.profiler`) —
  `X-Debug-Duration-Ms`/`X-Debug-Query-Count`/`X-Debug-Query-Time-Ms`
  headers, slow-query logging, and the queries a crashed request ran shown
  on its debug page.
- Sentry error monitoring (`zeython.error_monitoring`).
- A consolidated production-readiness checklist (`docs/production-checklist.md`).

### Extensibility & i18n

- A plugin registry for third-party packages (auto-discovered service
  providers, no per-package wiring).
- Localization: translation strings and per-request locale resolution.
- An auto-generated CRUD admin panel for registered models.
- Custom console commands (`app/Console/Commands/`, `zeython command`).

### CLI

- `zeython new`, `serve`, `make model|controller|middleware|provider|
  policy|notification|factory|seeder|job|command`,
  `db revision|migrate|downgrade|seed`, `queue work`, `schedule run`, `mcp`,
  `routes`, `about`, `features`, `down`, `up`.

### Testing & docs

- `zeython.testing.client` — an `httpx.AsyncClient` wired directly to the
  ASGI app for socket-free integration tests, plus `login_as()` and
  `transactional_session()` helpers.
- A generated project's own test suite runs against an isolated
  in-memory database (`tests/conftest.py`), never the dev server's file.
- A real, six-part, run-and-verified end-to-end tutorial (build TaskFlow,
  a small multi-project task tracker) alongside the topic-organized
  reference docs.
- Published benchmarks: Zeython vs. raw Starlette vs. FastAPI, with
  methodology and caveats disclosed.
- CI: lint (ruff), type-check (mypy), tests across Python 3.11–3.13
  (with a live Redis service container), and a scaffold smoke test that
  generates a project, migrates it, and runs its own test suite.
- `AGENTS.md` for AI coding agents working in Zeython codebases.

### Removed

- The Flask + Discord bot application template (`app/`, `config/`, `routes/`,
  `database/`, `vendor/`, `resources/`) that previously *was* the repository.
  Discord support is dropped entirely — Zeython is now a general-purpose web
  framework, not a Discord-bot-plus-website template.
- The synchronous, per-call `SessionLocal()` database access pattern.
- Documentation describing features that were stubs (OAuth "integration",
  virus-scanning hooks, etc.) rather than working code.

### Migrating from 1.x

There is no automated migration path — 1.x was an application, not a library.
To move a 1.x app forward: scaffold a new project with `zeython new`, then
port your Flask routes to `app/Controllers` + `routes/web.py` and your
SQLAlchemy models to `zeython.Model` subclasses in `app/Models`.

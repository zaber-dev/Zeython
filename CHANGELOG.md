# Changelog

## 1.0.0 — Initial release

Zeython is an installable, async-first, batteries-included MVC framework
with its own CLI — full ORM, auth, authorization, background jobs, caching,
WebSockets, an admin panel, multi-tenancy, localization, and a real
end-to-end tutorial. Licensed under MIT.

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
- Full-text search (`Model.search()`, `__searchable__`) — dispatches to
  SQLite FTS5 or Postgres `tsvector`/GIN depending on the connection's
  dialect, ranked most relevant first; `zeython.search` provides the
  one-time migration helpers (`create_fts5_index`, `create_tsvector_index`)
  that create and keep each index in sync, no new dependency or separate
  search service required.
- An application-level event dispatcher (`zeython.events`) — `emit()`,
  decoupled `listen()` handlers, an `EventServiceProvider` for wiring an
  app's own listeners in one place.
- Feature flags (`zeython.feature_flags`) — static `.env`-driven toggles
  and deterministic percentage rollouts, no database or Redis required;
  `zeython features` lists every defined flag and its current resolution.
- API versioning (`Router.version()`, `current_api_version()`,
  `deprecated()`) — group routes under a version prefix, read the active
  version from any handler, and flag an old one for removal with standard
  `Deprecation`/`Sunset` response headers.

### Auth, authorization & security

- Session-based authentication (`AuthServiceProvider`, `login`/`logout`,
  `require_auth`, `current_user`), plus bearer-token API authentication.
- OAuth2/OIDC login (`zeython.oauth`) — "Sign in with Google/GitHub/
  Microsoft", or any standards-compliant OIDC provider (Okta, Auth0,
  Keycloak) via `generic_oidc()`. Handles the CSRF-protected `state`
  round-trip and the code-for-token exchange; hands your app a normalized
  identity to find-or-create a user from, the same way Laravel Socialite
  does.
- Two-factor authentication (`zeython.mfa`) — RFC 6238 TOTP with no new
  dependency, one-time recovery codes, and a login-time challenge that
  gates `zeython.auth.login()` behind a second factor once a user enrolls.
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
  `Job.handle()`. A job that touches the database runs in its own
  session, opened and committed the same way a request's is -- not
  whatever session happened to be live wherever the job was pushed from.
- Job chaining and batching (`chain()`, `dispatch_batch()`) — run jobs
  strictly in order, or dispatch a group independently and fire a `then`
  job the moment they've all finished, on any queue driver
  (`InMemoryBatchTracker`/`RedisBatchTracker` picked automatically to
  match `QUEUE_DRIVER`).
- In-app task scheduler (`zeython.schedule`) — recurring jobs defined in
  code, no separate cron entry needed.
- Outbound mail (`zeython.mail`: `LogMailer`, `SmtpMailer`).
- Multi-channel notifications (`zeython.notifications`) — one `Notification`
  class describes its `mail`/`database`/`broadcast` rendering per
  recipient; `notify()` fires whichever channels it asks for. A failing
  channel is logged and reported, not raised, so one down channel doesn't
  block another.
- Outbound webhooks (`zeython.webhooks`) — subscribe a third party's URL to
  an event; `fire_webhook()` delivers an HMAC-SHA256-signed POST to every
  active subscriber through the existing job queue, with the queue's own
  retries/backoff and an optional per-attempt delivery log you own.
- A caching layer (`zeython.cache`) plus `RedisCache` for distributed
  deployments.

### Building APIs & real-time

- OpenAPI spec generation and a Swagger UI (`zeython.openapi`).
- A GraphQL endpoint (`zeython.graphql`, `pip install zeython[graphql]`) —
  executes a `graphql-core` schema you build, with an interactive GraphiQL
  UI in debug mode and every resolver's `info.context` carrying the
  request and the DI container.
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
- Prometheus-compatible metrics (`zeython.metrics`) — request counts and
  latency histograms at `/metrics` with zero new dependency, plus a
  `MetricsRegistry` for your own counters/gauges/histograms, grouped by
  route path template to keep label cardinality bounded.
- Optional OpenTelemetry distributed tracing (`zeython.tracing`,
  `pip install zeython[otel]`) — one span per request, W3C `traceparent`
  propagation, exception recording; bring your own exporter or use the
  console one to start.
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
  (with a live Redis service container), a coverage floor (~94% actual,
  enforced at 90%), and a scaffold smoke test that generates a project,
  migrates it, and runs its own test suite.
- `AGENTS.md` for AI coding agents working in Zeython codebases.
- A `py.typed` marker (PEP 561), actually shipped in the built wheel and
  verified there in CI — the `"Typing :: Typed"` classifier was previously
  aspirational only.


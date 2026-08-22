# Production Readiness Checklist

Everything below is documented in its own page already -- this is the one-page index for "am I actually ready to deploy this," pointing at the real docs instead of repeating them. Go through it once before a first production deploy, and again whenever you add something (a queue, a second replica, a new external API) that changes the answer.

## Configuration

- **`APP_ENV=production`, `APP_DEBUG=false`.** Debug mode leaks stack traces and internals into error responses -- a browser hitting a broken page gets a full source-level debug page (see [API Standards](https://zeython.zaber.dev/docs/api-standards/index.md)), an API client gets the equivalent in the JSON body. Fine locally, a disclosure bug in production. `zeython new` scaffolds both as development-friendly defaults; flip them in your deployment's `.env` or environment variables, not in the repo.
- **`APP_SECRET_KEY` is a real, unique secret**, not the value `zeython new` generated for local dev committed into version control. It signs the session cookie -- see [Authentication](https://zeython.zaber.dev/docs/authentication/index.md).
- **`DATABASE_URL` points at a real database**, not the default SQLite file. SQLite is fine for a single-container demo; anything with more than one app replica needs Postgres/MySQL so writes are visible across processes. See [Database & Migrations](https://zeython.zaber.dev/docs/database/index.md).
- **Migrations are applied**, not just written -- `alembic upgrade head` (the generated Docker image's `CMD` does this for you on a single-container deploy; see [Docker](https://zeython.zaber.dev/docs/docker/index.md)).

## Security

- **CSRF protection is on** -- it is by default for session auth, see [CSRF Protection](https://zeython.zaber.dev/docs/csrf/index.md). Don't disable it on a route just because a test was inconvenient.
- **Rate limiting is configured** on auth endpoints (on by default, see [Rate Limiting](https://zeython.zaber.dev/docs/rate-limiting/index.md)) and, if this is a public API, blanket-enabled across the rest of it too (`RATE_LIMIT_ENABLED=true`).
- **Security headers are registered** -- `SecurityHeadersServiceProvider` is opt-in, not on by default, because a wrong CSP silently breaks a real app. Decide your policy and register it; see [Security Headers](https://zeython.zaber.dev/docs/security-headers/index.md).
- **CORS is scoped to real origins**, not `*`, if `CorsServiceProvider` is registered at all. Wildcard origins on an authenticated API mean any site can read the response.
- **WebSocket origin checking** is on if you're not the only expected client -- see the Origin-check note in [WebSockets](https://zeython.zaber.dev/docs/websockets/index.md).
- **RBAC/authorization is actually enforced** on every route that needs it -- an undefined ability is a bug, not a silent deny (see [Authorization](https://zeython.zaber.dev/docs/authorization/index.md)), so audit routes for a missing `authorize()`/`Gate.allows()` call rather than trusting that one exists.
- **You've read [SECURITY.md](https://github.com/zaber-dev/Zeython/blob/main/SECURITY.md)** -- supported versions and how to report a vulnerability privately, for your own app as much as for the framework.

## Database

- **Connection pooling is sized for your deployment**, not left at SQLAlchemy's defaults if you're running multiple app processes against one database -- see [Connection pooling](https://zeython.zaber.dev/docs/database/#connection-pooling).
- **A read replica is wired up** (`DATABASE_READ_URL` + `Database.read_replica()`) if read load is the bottleneck, not before -- see [Read replicas](https://zeython.zaber.dev/docs/database/#read-replicas).
- **N+1 query detection has actually been run** against real traffic paths in dev (`APP_DEBUG=true`, `N1QueryDetectionServiceProvider`) at least once before shipping a new list/index endpoint -- see [Detecting N+1s automatically](https://zeython.zaber.dev/docs/relationships/#detecting-n1s-automatically).
- **Multi-step writes that must succeed or fail together use `transaction()`** (a `SAVEPOINT`-scoped nested transaction), not several unguarded writes hoping nothing fails in between -- see [Transactions](https://zeython.zaber.dev/docs/database/#transactions).

## Observability

- **Structured logging is on** if you ship to a log aggregator (Datadog, ELK, CloudWatch Logs Insights, Splunk) -- `LOG_FORMAT=json`, see [Structured (JSON) logging](https://zeython.zaber.dev/docs/observability/#structured-json-logging). Plain text is fine if a human is the only consumer.
- **`X-Request-ID` correlation is working end to end** -- it's on by default (`RequestIdServiceProvider`), but confirm your proxy/load balancer isn't stripping the header before it reaches the app. See [Request/Correlation IDs](https://zeython.zaber.dev/docs/observability/#requestcorrelation-ids).
- **Error monitoring is wired up** (Sentry via `ErrorMonitoringServiceProvider` + `SENTRY_DSN`) so an unhandled exception, an exhausted job retry, or a raising scheduled task reaches you instead of only a log line nobody's watching. See [Error Monitoring](https://zeython.zaber.dev/docs/error-monitoring/index.md).
- **`/up` is actually wired into your infrastructure's health check** -- a load balancer target group, a Kubernetes probe, an uptime monitor -- not just reachable by hand. See [Health Check](https://zeython.zaber.dev/docs/health-check/index.md).

## Background work

- **`QUEUE_DRIVER=redis`, not `memory`**, for any job whose loss on a crash or restart you can't tolerate (payment capture, anything with a side effect outside your database) -- see [Background Jobs](https://zeython.zaber.dev/docs/queues/index.md). The in-memory driver is fine for low-stakes work and local dev.
- **A `queue-worker` process is actually running** if you switched to the Redis driver -- jobs pushed to a durable queue with nothing consuming them just pile up. `docker-compose.yml` includes a commented-out service for this; see [Docker](https://zeython.zaber.dev/docs/docker/#postgres-redis).
- **A scheduler process is running** if `schedule.py` defines anything -- a host crontab entry, or the commented-out `scheduler` sidecar in `docker-compose.yml`. See [Scheduling](https://zeython.zaber.dev/docs/scheduling/index.md) and [Docker](https://zeython.zaber.dev/docs/docker/#scheduled-tasks).

## API standards

- **Response compression is on** for a JSON API with non-trivial payloads (`GzipServiceProvider`) -- opt-in, not registered by default. See [Compression (gzip)](https://zeython.zaber.dev/docs/api-standards/#compression-gzip).
- **Conditional GETs are on** if clients re-fetch the same resources often (`ETagServiceProvider`) -- know the memory trade-off (it buffers the full response body) before turning it on for large or streamed responses. See [Conditional requests (ETags)](https://zeython.zaber.dev/docs/api-standards/#conditional-requests-etags).
- **Error response shape matches what your clients expect** -- the default `{"error": ..., "status": ...}` shape, or RFC 7807 `application/problem+json` (`API_PROBLEM_JSON=true`) if you're integrating with tooling that expects the standard. Decide once, not per route. See [RFC 7807 error responses](https://zeython.zaber.dev/docs/api-standards/#rfc-7807-error-responses-applicationproblemjson).

## Testing

- **Tests that touch the database roll back between runs**, not leaving state for the next test to trip over -- see [Rolling back writes between tests](https://zeython.zaber.dev/docs/testing/#rolling-back-writes-between-tests).
- **Routes that require login are tested as an authenticated user**, not skipped because wiring up a real login flow in a test felt like too much -- see [Logging a test client in directly](https://zeython.zaber.dev/docs/testing/#logging-a-test-client-in-directly).
- **CI is actually green** on the branch you're deploying, not "green last time I looked."

## What this deliberately doesn't cover

This isn't a substitute for your own judgment

This checklist is about configuring and wiring up features the framework already ships -- it is not a substitute for your own judgment about your specific deployment: infrastructure choice, TLS termination, backup strategy, secrets management (a real secrets manager, not `.env` in production), and load testing are all yours to own. If a section above doesn't apply to your app (no background jobs, no public API), skip it -- this is a checklist to consult, not a form to fill out completely.

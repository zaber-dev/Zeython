# Zeython

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![CI](https://github.com/zaber-dev/Zeython/actions/workflows/ci.yml/badge.svg)](https://github.com/zaber-dev/Zeython/actions/workflows/ci.yml)

**Zeython** is an async-first, batteries-included MVC framework for Python —
a dependency injection container, a service-provider boot lifecycle, an
Active-Record-style async ORM, and a Laravel-style CLI, built on top of
[Starlette](https://www.starlette.io/) and [SQLAlchemy 2.0](https://docs.sqlalchemy.org/).

Zeython is created by **Md Mahedi Zaman Zaber**.

## Why Zeython

Python has excellent web *libraries*. It has very few opinionated, batteries-included
*frameworks* in the Django/Laravel/Rails sense — most teams end up hand-rolling the
same dependency injection container, request-scoped database session, and CLI
scaffolding on every project. Zeython does that assembly once:

- **Async all the way down** — request handling, the ORM, and migrations, with
  no bolted-on `asyncio.run` calls.
- **Request-scoped database sessions** via `contextvars`, not a session shared
  globally or a fresh one hand-rolled per call.
- **Convention over configuration** — controllers, models, and routes live in
  predictable places (`app/Controllers`, `app/Models`, `routes/`).
- **A real CLI** — `zeython new`, `zeython serve`, `zeython make:*`,
  `zeython db:*` cover project creation, code generation, and migrations.
- **Live API docs, from your actual routes** — a generated OpenAPI spec and
  Swagger UI at `/docs`, built by reading what's really registered, not a
  separately maintained spec file. See [docs/openapi.md](docs/openapi.md).
- **Real-time out of the box** — `@app.websocket(...)` handlers and a
  `WebSocketHub` broadcast registry, built on Starlette's native ASGI
  WebSocket support — no separate server. See [docs/websockets.md](docs/websockets.md).
- **AI-agent ready** — an MCP server (`zeython mcp`) gives coding agents
  direct tools to inspect a project's actual routes and database schema, and
  to search documentation bundled with the exact installed framework
  version, instead of guessing. See [docs/ai-agents.md](docs/ai-agents.md).
- **AI-capable apps** — `zeython.ai` binds an LLM client (`AI`) in the
  container for your own routes and jobs to call, zero-config by default
  (`EchoAI`, no credentials needed) and one line to switch to a real
  Anthropic-backed client. See [docs/ai.md](docs/ai.md).
- **Enterprise-grade security and compliance, out of the box** — RBAC-style
  authorization (`Gate`/Policies), row-level multi-tenancy, TOTP two-factor
  auth with recovery codes, "Sign in with Google/GitHub/Microsoft" or your
  own OIDC identity provider, SAML SSO for the enterprise IdPs that
  specifically require it, and an automatic per-field audit trail on any
  model — the features most frameworks leave you to bolt on yourself. See
  [Authorization](docs/authorization.md), [Multi-Tenancy](docs/multi-tenancy.md),
  [MFA](docs/mfa.md), [OAuth/SSO Login](docs/oauth.md), [SAML SSO](docs/saml.md),
  [Audit Logging](docs/audit-log.md).
- **Outbound webhooks with retries and HMAC signing, built in** — subscribe a
  third party's URL to an event, and delivery, retry-with-backoff, and a
  per-attempt audit trail all ride on the same background-job queue every
  other job uses. See [Webhooks](docs/webhooks.md).
- **Job chaining and batching, not just a queue** — run jobs strictly in
  order with `chain()`, or dispatch a group independently and fire a
  callback the moment they've all finished with `dispatch_batch()`, on
  any queue driver. See [Background Jobs](docs/queues.md).
- **Production observability, not just logs** — Prometheus-compatible
  metrics at `/metrics` (request counts, latency histograms, your own
  custom counters/gauges), with zero new dependency, plus opt-in
  OpenTelemetry distributed tracing with W3C `traceparent` propagation.
  See [Metrics](docs/metrics.md), [Tracing](docs/tracing.md).
- **Real full-text search, no new service** — `Model.search()` queries
  SQLite's FTS5 or Postgres's `tsvector`/GIN, whichever your database
  already ships, ranked most relevant first, kept in sync by the database
  itself. See [Full-Text Search](docs/search.md).
- **API versioning built into the router** — group routes by version with
  `Router.version()`, read the active one from any handler with
  `current_api_version()`, and flag an old one for removal with standard
  `Deprecation`/`Sunset` headers via `deprecated()`. See
  [API Standards](docs/api-standards.md#api-versioning).
- **GraphQL alongside your REST routes** — one `GraphQLServiceProvider`
  serves a schema you build with `graphql-core`, with an interactive
  GraphiQL UI in debug mode and every resolver's `info.context` carrying
  the request and the DI container. See [GraphQL](docs/graphql.md).
- **Idempotency keys, Stripe-style** — an `Idempotency-Key` header on a
  `POST`/`PUT`/`PATCH`/`DELETE` replays that request's first response
  instead of running it twice, so a client's retry after a dropped
  connection can't double-charge a card or create a duplicate row. See
  [Idempotency Keys](docs/idempotency.md).
- **Small, typed, tested core** — the framework itself ships full type hints
  ([PEP 561](https://peps.python.org/pep-0561/) `py.typed`) and a pytest
  suite of 700+ tests; it is not scaffolding wrapped around unfinished features.

## Quick start

Not yet on PyPI — install straight from GitHub:

```bash
pip install git+https://github.com/zaber-dev/Zeython.git
zeython new "My Blog"
cd my_blog
pip install -e .
cp .env.example .env
zeython serve
```

Visit `http://127.0.0.1:8000`.

## A taste of it

```python
# app/Models/post.py
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column
from zeython import Model

class Post(Model):
    __tablename__ = "posts"
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
```

```python
# app/Controllers/post_controller.py
from starlette.responses import JSONResponse
from zeython import Controller, NotFoundException
from app.Models.post import Post

class PostController(Controller):
    async def index(self, request):
        return JSONResponse([p.to_dict() for p in await Post.all()])

    async def show(self, request):
        post = await Post.find(int(request.path_params["id"]))
        if post is None:
            raise NotFoundException("Post not found")
        return JSONResponse(post.to_dict())

    async def store(self, request):
        data = await request.json()
        post = await Post.create(**data)
        return JSONResponse(post.to_dict(), status_code=201)
```

```python
# routes/web.py
from main import app
from app.Controllers.post_controller import PostController

app.router.resource("/posts", PostController)
```

```bash
zeython make model Post
zeython make controller Post
zeython db revision -m "add posts table"
zeython db migrate
```

## Project structure

```
my_blog/
├── app/
│   ├── Controllers/      # request handlers
│   ├── Models/           # async Active Record models
│   ├── Middleware/       # ASGI middleware
│   └── Console/Commands/ # custom `zeython command <name>` CLI commands
├── database/
│   ├── factories/        # model factories for tests/seeding
│   └── seeders/          # `zeython db seed`
├── routes/
│   └── web.py            # route definitions
├── migrations/            # Alembic migrations
├── tests/
├── main.py                # application entry point
├── alembic.ini
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## Documentation

Landing page: https://zeython.zaber.dev/
Full rendered docs (searchable, better navigation, generated API reference): https://zeython.zaber.dev/docs/

**Getting Started**
[Overview](docs/index.md) ·
[Getting Started](docs/getting-started.md) ·
[Architecture](docs/architecture.md)

**Tutorial**
[Build TaskFlow](docs/tutorial.md) — a guided, six-part walkthrough from an
empty scaffold to a tested, authenticated API

**The Basics**
[Database & Migrations](docs/database.md) ·
[Full-Text Search](docs/search.md) ·
[Relationships](docs/relationships.md) ·
[Validation](docs/validation.md) ·
[Model Events](docs/model-events.md) ·
[Factories & Seeders](docs/database-seeding.md) ·
[Views](docs/views.md) ·
[Frontend & CSS](docs/frontend.md)

**Security**
[Authentication](docs/authentication.md) ·
[OAuth/SSO Login](docs/oauth.md) ·
[SAML SSO](docs/saml.md) ·
[Two-Factor Auth (MFA)](docs/mfa.md) ·
[CSRF Protection](docs/csrf.md) ·
[Authorization](docs/authorization.md) ·
[API Authentication](docs/api-authentication.md) ·
[Security Headers](docs/security-headers.md) ·
[Rate Limiting](docs/rate-limiting.md) ·
[Multi-Tenancy](docs/multi-tenancy.md)

**Building APIs**
[OpenAPI & API Docs](docs/openapi.md) ·
[API Standards](docs/api-standards.md) ·
[GraphQL](docs/graphql.md) ·
[Idempotency Keys](docs/idempotency.md)

**Digging Deeper**
[CLI Reference](docs/cli.md) ·
[Console Commands](docs/console-commands.md) ·
[Plugins](docs/plugins.md) ·
[Localization](docs/localization.md) ·
[Events](docs/events.md) ·
[Notifications](docs/notifications.md) ·
[Audit Logging](docs/audit-log.md) ·
[Webhooks](docs/webhooks.md) ·
[Feature Flags](docs/feature-flags.md) ·
[Background Jobs](docs/queues.md) ·
[Scheduling](docs/scheduling.md) ·
[WebSockets](docs/websockets.md) ·
[Mail](docs/mail.md) ·
[Caching](docs/caching.md) ·
[Redis (Distributed)](docs/redis.md) ·
[File Storage](docs/storage.md) ·
[Admin Panel](docs/admin.md) ·
[AI](docs/ai.md) ·
[AI Agents](docs/ai-agents.md)

**Testing**
[Testing](docs/testing.md)

**Deployment & Operations**
[Health Check](docs/health-check.md) ·
[Maintenance Mode](docs/maintenance-mode.md) ·
[Observability](docs/observability.md) ·
[Metrics](docs/metrics.md) ·
[Tracing](docs/tracing.md) ·
[Profiling](docs/profiling.md) ·
[Error Monitoring](docs/error-monitoring.md) ·
[Docker](docs/docker.md) ·
[Production Checklist](docs/production-checklist.md) ·
[Benchmarks](docs/benchmarks.md)

## Framework development

Working on Zeython itself (not an app built with it):

```bash
git clone https://github.com/zaber-dev/Zeython.git
cd Zeython
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest
ruff check src tests
mypy src/zeython
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## For AI coding agents

See [AGENTS.md](AGENTS.md) for framework conventions written for agentic coding
tools (Claude Code, Cursor, Copilot Workspace, etc.) working in a Zeython codebase.

## Security

Found a vulnerability? Please don't open a public issue for it — see
[SECURITY.md](SECURITY.md) for how to report it privately.

## License

MIT. See [LICENSE](LICENSE).

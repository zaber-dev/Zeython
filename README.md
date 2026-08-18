# Zeython

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
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
- **Small, typed, tested core** — the framework itself ships full type hints
  and a pytest suite; it is not scaffolding wrapped around unfinished features.

## Quick start

```bash
pip install zeython
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

- [docs/index.md](docs/index.md) — overview
- [docs/getting-started.md](docs/getting-started.md)
- [docs/architecture.md](docs/architecture.md) — container, providers, router, ORM
- [docs/cli.md](docs/cli.md) — full CLI reference
- [docs/console-commands.md](docs/console-commands.md) — writing your own `zeython command <name>` CLI commands
- [docs/plugins.md](docs/plugins.md) — pip-installable packages that register their own service providers, no per-package wiring
- [docs/openapi.md](docs/openapi.md) — generated OpenAPI spec + Swagger UI at `/docs`
- [docs/api-standards.md](docs/api-standards.md) — gzip compression, ETags/conditional GETs, RFC 7807 `problem+json` errors
- [docs/database.md](docs/database.md) — models and migrations
- [docs/multi-tenancy.md](docs/multi-tenancy.md) — row-level tenant isolation, opt-in per model
- [docs/database-seeding.md](docs/database-seeding.md) — model factories and seeders
- [docs/relationships.md](docs/relationships.md) — defining and safely loading relationships in async code
- [docs/validation.md](docs/validation.md) — declarative model validation
- [docs/model-events.md](docs/model-events.md) — `creating`/`created`/`updating`/`updated`/`deleting`/`deleted` hooks
- [docs/views.md](docs/views.md)
- [docs/frontend.md](docs/frontend.md) — Tailwind out of the box (dev), moving to a compiled build
- [docs/localization.md](docs/localization.md) — translation strings, per-request locale resolution
- [docs/authentication.md](docs/authentication.md) — session auth, password hashing, route guards
- [docs/csrf.md](docs/csrf.md) — the double-submit-cookie check that comes with session auth automatically
- [docs/security-headers.md](docs/security-headers.md) — opt-in CSP/`X-Frame-Options`/HSTS response headers
- [docs/api-authentication.md](docs/api-authentication.md) — bearer tokens for clients that can't use cookies
- [docs/authorization.md](docs/authorization.md) — named abilities (`Gate`), `authorize()` route guards
- [docs/admin.md](docs/admin.md) — auto-generated CRUD UI for registered models
- [docs/storage.md](docs/storage.md) — validated uploads, local/S3 storage
- [docs/rate-limiting.md](docs/rate-limiting.md) — throttling routes, auth-endpoint defaults
- [docs/caching.md](docs/caching.md) — an in-memory TTL cache, and `remember()` for get-or-compute
- [docs/redis.md](docs/redis.md) — `RedisCache`/`RedisRateLimiter` for multi-process/multi-machine deployments
- [docs/queues.md](docs/queues.md) — background jobs, dispatching work off the request cycle
- [docs/scheduling.md](docs/scheduling.md) — recurring tasks defined in code, one cron entry total
- [docs/websockets.md](docs/websockets.md) — real-time handlers and the `WebSocketHub` broadcast registry
- [docs/mail.md](docs/mail.md) — sending email, log-only by default, SMTP when ready
- [docs/ai.md](docs/ai.md) — calling an LLM from your own app code
- [docs/ai-agents.md](docs/ai-agents.md) — the MCP server for AI coding agents
- [docs/health-check.md](docs/health-check.md) — `/up`, for load balancers and container orchestrators
- [docs/observability.md](docs/observability.md) — `X-Request-ID` correlation IDs and `LOG_FORMAT=json` structured logging
- [docs/error-monitoring.md](docs/error-monitoring.md) — reporting unhandled exceptions, failed jobs, and raising scheduled tasks to Sentry
- [docs/docker.md](docs/docker.md) — the generated Dockerfile/docker-compose.yml, and how to use them
- [docs/testing.md](docs/testing.md)
- [docs/benchmarks.md](docs/benchmarks.md) — Zeython vs. raw Starlette vs. FastAPI, methodology and caveats included
- [docs/production-checklist.md](docs/production-checklist.md) — the one-page index of what to check before a first deploy

Full rendered docs: https://zaber-dev.github.io/Zeython/

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

GNU General Public License v3.0. See [LICENSE](LICENSE).

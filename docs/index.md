# Zeython

Zeython is an async-first, batteries-included MVC framework for Python, built on
[Starlette](https://www.starlette.io/) and [SQLAlchemy 2.0](https://docs.sqlalchemy.org/).
It gives you a dependency injection container, a service-provider boot lifecycle, an
Active-Record-style async ORM, and a Laravel-style `zeython` CLI — the pieces most
hand-rolled Python web projects end up building themselves, done once and done well.

## Why Zeython

Python has excellent web *libraries* (Starlette, SQLAlchemy, Alembic, uvicorn) but
assembling them into a coherent, opinionated application structure is left as an
exercise to every team. Zeython is that assembly: a real framework with conventions,
not a template you copy and diverge from.

- **Async all the way down.** Request handling, the ORM, and migrations are async
  from the start — no bolted-on `asyncio.run` calls.
- **Request-scoped database sessions**, not a global session shared across requests
  or a fresh session hand-rolled per call.
- **Convention over configuration.** Controllers, models, and routes live in
  predictable places (`app/Controllers`, `app/Models`, `routes/`).
- **A real CLI.** `zeython new`, `zeython serve`, `zeython make:*`, and
  `zeython db:*` cover the whole day-to-day loop.

## Documentation

- [Getting Started](getting-started.md) — install the framework and scaffold your first project
- [Architecture](architecture.md) — how the container, providers, router, and ORM fit together
- [CLI Reference](cli.md) — every `zeython` command
- [Console Commands](console-commands.md) — writing your own `zeython command <name>` CLI commands
- [OpenAPI & API Docs](openapi.md) — generated spec + Swagger UI at `/docs`, from your actual routes
- [Database & Migrations](database.md) — the `Model` base class and Alembic workflow
- [Factories & Seeders](database-seeding.md) — generating model instances for tests, seeding demo/reference data
- [Relationships](relationships.md) — defining and safely loading relationships in async code
- [Validation](validation.md) — declarative model validation rules
- [Model Events](model-events.md) — `creating`/`created`/`updating`/`updated`/`deleting`/`deleted` hooks
- [Views](views.md) — server-rendered HTML with Jinja2
- [Frontend & CSS](frontend.md) — Tailwind out of the box (dev), moving to a compiled build
- [Authentication](authentication.md) — session-based login, password hashing, route guards
- [API Authentication](api-authentication.md) — bearer tokens for clients that can't use cookies
- [Authorization](authorization.md) — named abilities (`Gate`), `authorize()` route guards
- [File Storage](storage.md) — validated uploads, local storage, S3-compatible backends
- [Rate Limiting](rate-limiting.md) — throttling routes, the auth-endpoint defaults
- [Caching](caching.md) — an in-memory TTL cache, and `remember()` for get-or-compute
- [Redis (Distributed)](redis.md) — `RedisCache`/`RedisRateLimiter` for multi-process/multi-machine deployments
- [Background Jobs](queues.md) — dispatching work off the request/response cycle
- [Mail](mail.md) — sending email, log-only by default, SMTP when you're ready
- [AI](ai.md) — calling an LLM from your own app code
- [AI Agents](ai-agents.md) — the MCP server: route/model introspection and docs search for AI coding agents
- [Health Check](health-check.md) — `/up`, for load balancers and container orchestrators
- [Docker](docker.md) — the generated Dockerfile/docker-compose.yml, and how to use them
- [Testing](testing.md) — writing tests against a Zeython application

## Contributing

See [CONTRIBUTING.md](https://github.com/zaber-dev/Zeython/blob/main/CONTRIBUTING.md)
in the repository root.

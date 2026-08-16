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
- [Database & Migrations](database.md) — the `Model` base class and Alembic workflow
- [Relationships](relationships.md) — defining and safely loading relationships in async code
- [Validation](validation.md) — declarative model validation rules
- [Views](views.md) — server-rendered HTML with Jinja2
- [Authentication](authentication.md) — session-based login, password hashing, route guards
- [File Storage](storage.md) — validated uploads, local storage, S3-compatible backends
- [Rate Limiting](rate-limiting.md) — throttling routes, the auth-endpoint defaults
- [Caching](caching.md) — an in-memory TTL cache, and `remember()` for get-or-compute
- [Background Jobs](queues.md) — dispatching work off the request/response cycle
- [Mail](mail.md) — sending email, log-only by default, SMTP when you're ready
- [AI Agents](ai-agents.md) — the MCP server: route/model introspection and docs search for AI coding agents
- [Testing](testing.md) — writing tests against a Zeython application

## Contributing

See [CONTRIBUTING.md](https://github.com/zaber-dev/Zeython/blob/main/CONTRIBUTING.md)
in the repository root.

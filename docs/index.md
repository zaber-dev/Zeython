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

## Where to start

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } **Getting Started**

    ---

    Install the framework and scaffold your first project in under a minute.

    [:octicons-arrow-right-24: Getting Started](getting-started.md)

-   :material-map:{ .lg .middle } **Build TaskFlow**

    ---

    A guided, six-part tutorial from an empty scaffold to a tested,
    authenticated API — the fastest way to actually learn the framework.

    [:octicons-arrow-right-24: Start the tutorial](tutorial.md)

-   :material-sitemap:{ .lg .middle } **Architecture**

    ---

    How the container, service providers, router, and async ORM fit
    together.

    [:octicons-arrow-right-24: Read Architecture](architecture.md)

-   :material-book-open-variant:{ .lg .middle } **API Reference**

    ---

    Every public class and function, generated straight from docstrings.

    [:octicons-arrow-right-24: Browse the reference](reference/index.md)

</div>

Everything else — database, security, background jobs, deployment — is one
click away in the navigation above.

## Contributing

See [CONTRIBUTING.md](https://github.com/zaber-dev/Zeython/blob/main/CONTRIBUTING.md)
in the repository root.

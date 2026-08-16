# Zeython

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![CI](https://github.com/zaber-dev/Zeython/actions/workflows/ci.yml/badge.svg)](https://github.com/zaber-dev/Zeython/actions/workflows/ci.yml)

**Zeython** is an async-first, batteries-included MVC framework for Python —
a dependency injection container, a service-provider boot lifecycle, an
Active-Record-style async ORM, and a Laravel-style CLI, built on top of
[Starlette](https://www.starlette.io/) and [SQLAlchemy 2.0](https://docs.sqlalchemy.org/).

Zeython is created by **Md Mahedi Zaman Zaber**.

> **Note:** Zeython 2.0 is a from-scratch, breaking rewrite of the earlier
> Flask + Discord bot template. Nothing about that version carries forward —
> the framework is now an installable package, not a repo you clone and edit
> in place. See [CHANGELOG.md](CHANGELOG.md) for details.

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
│   └── Middleware/       # ASGI middleware
├── routes/
│   └── web.py            # route definitions
├── migrations/            # Alembic migrations
├── tests/
├── main.py                # application entry point
├── alembic.ini
└── .env.example
```

## Documentation

- [docs/index.md](docs/index.md) — overview
- [docs/getting-started.md](docs/getting-started.md)
- [docs/architecture.md](docs/architecture.md) — container, providers, router, ORM
- [docs/cli.md](docs/cli.md) — full CLI reference
- [docs/database.md](docs/database.md) — models and migrations
- [docs/relationships.md](docs/relationships.md) — defining and safely loading relationships in async code
- [docs/validation.md](docs/validation.md) — declarative model validation
- [docs/views.md](docs/views.md) — server-rendered HTML with Jinja2
- [docs/authentication.md](docs/authentication.md) — session auth, password hashing, route guards
- [docs/storage.md](docs/storage.md) — validated uploads, local/S3 storage
- [docs/rate-limiting.md](docs/rate-limiting.md) — throttling routes, auth-endpoint defaults
- [docs/queues.md](docs/queues.md) — background jobs, dispatching work off the request cycle
- [docs/mail.md](docs/mail.md) — sending email, log-only by default, SMTP when ready
- [docs/testing.md](docs/testing.md)

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

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).

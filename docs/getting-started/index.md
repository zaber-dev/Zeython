# Getting Started

## Requirements

- Python 3.11+

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install zeython
```

## Scaffold a project

```bash
zeython new "My Blog"
cd my_blog
pip install -e .
cp .env.example .env
```

This generates:

```text
my_blog/
├── app/
│   ├── Controllers/     # request handlers
│   ├── Models/          # async Active Record models
│   └── Middleware/       # ASGI middleware
├── routes/
│   └── web.py           # route definitions
├── migrations/           # Alembic migrations
├── tests/
├── main.py               # application entry point
├── alembic.ini
└── .env.example
```

## Run it

```bash
zeython serve
```

Visit `http://127.0.0.1:8000` — you should see a JSON welcome message. Try registering a user and listing them:

```bash
curl -X POST http://127.0.0.1:8000/register \
  -H 'Content-Type: application/json' \
  -d '{"name": "Ada", "email": "ada@example.com", "password": "hunter2"}'

curl http://127.0.0.1:8000/users
```

`/users` is paginated (see [Database & Migrations](https://zeython.zaber.dev/docs/database/#pagination)) — the response is `{"items": [...], "page": 1, "total": 1, ...}`, not a bare array.

Getting a database error?

A fresh scaffold ships with the `User` model but no migration file yet — generate and apply the initial one first:

```bash
zeython db revision -m "create users table"
zeython db migrate
```

## Next steps

- Follow the [Tutorial](https://zeython.zaber.dev/docs/tutorial/index.md) to build a real, tested, multi-model app from this same starting point — the fastest way to actually learn the framework.
- Read [Architecture](https://zeython.zaber.dev/docs/architecture/index.md) to understand the container, service providers, and router.
- Read [Database & Migrations](https://zeython.zaber.dev/docs/database/index.md) to add your own models.
- Read [CLI Reference](https://zeython.zaber.dev/docs/cli/index.md) for the full list of `zeython make:*` generators.

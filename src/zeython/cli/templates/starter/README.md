# {{ project_name }}

A [Zeython](https://github.com/zaber-dev/Zeython) application.

## Getting started

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env

zeython serve
```

Visit http://127.0.0.1:8000

## Project layout

- `app/Controllers` — request handlers
- `app/Models` — database models (async Active Record)
- `app/Middleware` — ASGI middleware
- `routes/web.py` — route definitions
- `migrations/` — Alembic database migrations
- `tests/` — pytest test suite

## Common commands

```bash
zeython serve                        # run the dev server with auto-reload
zeython make controller PostController
zeython make model Post
zeython db revision -m "add posts table"
zeython db migrate
pytest
```

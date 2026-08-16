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

```
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

Visit `http://127.0.0.1:8000` — you should see a JSON welcome message. Try
registering a user and listing them:

```bash
curl -X POST http://127.0.0.1:8000/register \
  -H 'Content-Type: application/json' \
  -d '{"name": "Ada", "email": "ada@example.com", "password": "hunter2"}'

curl http://127.0.0.1:8000/users
```

`/users` is paginated (see [Database & Migrations](database.md#pagination))
— the response is `{"items": [...], "page": 1, "total": 1, ...}`, not a
bare array.

If you get a database error, run the initial migration first:

```bash
zeython db migrate
```

## Next steps

- Read [Architecture](architecture.md) to understand the container, service providers, and router.
- Read [Database & Migrations](database.md) to add your own models.
- Read [CLI Reference](cli.md) for the full list of `zeython make:*` generators.

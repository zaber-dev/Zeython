# Part 1: Setup

## Scaffold the project

```bash
python -m venv .venv && source .venv/bin/activate
pip install zeython
zeython new "TaskFlow"
cd task_flow
pip install -e ".[dev]"
cp .env.example .env
```

`zeython new` generated a real, runnable project — not a single-file demo. (The `[dev]` extra pulls in `pytest`, `pytest-asyncio`, and `httpx` — the project ships with a passing test in `tests/test_home.py` already, and you'll write more of your own starting in [Part 6](https://zeython.zaber.dev/docs/tutorial-6-testing/index.md).) Look at what's there:

```text
task_flow/
├── app/
│   ├── Controllers/       # request handlers
│   ├── Models/            # async Active Record models
│   ├── Middleware/        # ASGI middleware
│   ├── Providers/         # your own service providers
│   ├── Jobs/               # background jobs
│   └── Console/Commands/   # custom `zeython command <name>` CLI commands
├── database/
│   ├── factories/          # model factories for tests/seeding
│   └── seeders/            # `zeython db seed`
├── routes/
│   └── web.py               # route definitions
├── migrations/               # Alembic migrations
├── tests/
├── main.py                   # application entry point -- start here
├── alembic.ini
└── .env.example
```

`main.py` is worth opening now. It's not hidden framework magic — it's plain Python that constructs an `Application`, registers the providers your app needs (`AuthServiceProvider`, `DatabaseServiceProvider`, `RouteServiceProvider`, ...), and a dozen more commented out that you can turn on later (rate limiting, an admin panel, localization). Everything your generated app does, it does because a line in `main.py` says so — see [Architecture](https://zeython.zaber.dev/docs/architecture/index.md) when you're ready for the full picture of how the container and providers fit together. For now, the short version: a **service provider** is where a piece of functionality (auth, the database, routing) gets wired into the app, and `main.py` is the list of which pieces you're using.

## Run it

A fresh scaffold ships with the `User` model already written but no migration file for it yet — `revision` autogenerates one by diffing your models against the (empty) database, `migrate` applies it:

```bash
zeython db revision -m "create users table"
zeython db migrate
zeython serve
```

Visit `http://127.0.0.1:8000` — you'll get a small JSON welcome payload. `zeython serve` auto-reloads on file changes, so leave it running for the rest of this tutorial.

## Try the auth that's already there

A generated project ships with a working `User` model and session authentication out of the box (see [Authentication](https://zeython.zaber.dev/docs/authentication/index.md) for the full picture later) — you get to use it for free instead of building login from scratch. One thing to know before the very first request: every unsafe method (`POST`/`PUT`/`PATCH`/`DELETE`) needs a CSRF token back via a header, even this one — see [CSRF Protection](https://zeython.zaber.dev/docs/csrf/index.md) for why. A safe `GET` hands you that token as a cookie, so grab it once and pass it back:

```bash
curl -sS -c cookies.txt http://127.0.0.1:8000/ > /dev/null
CSRF=$(grep csrf_token cookies.txt | awk '{print $NF}')

curl -sS -b cookies.txt -c cookies.txt -H "X-CSRF-Token: $CSRF" \
  -X POST http://127.0.0.1:8000/register \
  -H 'Content-Type: application/json' \
  -d '{"name": "Ada", "email": "ada@example.com", "password": "hunter2222"}'
```

```json
{"name":"Ada","email":"ada@example.com","id":1,"created_at":"...","updated_at":"...","is_deleted":false,"deleted_at":null}
```

`cookies.txt` now holds that CSRF cookie plus the session cookie `/register` set — you're logged in as Ada, and every following `curl` in this tutorial that passes `-b cookies.txt` will be authenticated as her (and, for unsafe methods, needs `-H "X-CSRF-Token: $CSRF"` alongside it — recompute `$CSRF` from `cookies.txt` if you're picking this up in a fresh terminal). Confirm it:

```bash
curl -sS -b cookies.txt http://127.0.0.1:8000/me
```

```json
{"name":"Ada","email":"ada@example.com","id":1,"created_at":"...","updated_at":"...","is_deleted":false,"deleted_at":null}
```

That's the whole account system you'd otherwise hand-roll — password hashing, a signed session cookie, CSRF protection on every unsafe request (Parts 2-4 reuse the same `$CSRF` this way; [Part 5](https://zeython.zaber.dev/docs/tutorial-5-auth/index.md) adds actual login *requirements* to TaskFlow's own routes) — already wired up, already tested, already documented.

Next: [Part 2 — Models](https://zeython.zaber.dev/docs/tutorial-2-models/index.md), where TaskFlow actually starts.

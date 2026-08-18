# Benchmarks

Three minimal apps -- Zeython, raw Starlette, FastAPI -- each with a
trivial `/json` route and a `/items` route that queries a 100-row SQLite
table, benchmarked with [`wrk`](https://github.com/wg/wrk). Published
results and methodology notes: [docs/benchmarks.md](../docs/benchmarks.md).

## Running it yourself

```bash
cd benchmarks
python -m venv .venv && source .venv/bin/activate
pip install -e ..              # Zeython itself, editable
pip install fastapi uvicorn    # the two reference apps
cp .env.example .env           # DATABASE_URL for zeython_app.py

python seed.py                 # creates benchmark.db, 100 rows in `items`

# one at a time -- each app needs the port to itself
python zeython_app.py                        # :8000
uvicorn starlette_app:app --port 8001         # :8001
uvicorn fastapi_app:app --port 8002           # :8002
```

Then, against whichever app is running:

```bash
wrk -t4 -c50 -d10s http://127.0.0.1:8000/json
wrk -t4 -c50 -d10s http://127.0.0.1:8000/items
```

`wrk` isn't a Zeython or Python dependency -- install it separately
(`apt install wrk`, `brew install wrk`, or build from source).

## What each app actually does

- **`zeython_app.py`** -- a real Zeython app: `DatabaseServiceProvider`
  registered, `/items` goes through `Item.all()` (the framework's own
  Active Record API, request-scoped session and all).
- **`starlette_app.py`** -- no framework beyond Starlette itself: a
  plain SQLAlchemy async engine, a session opened and closed by hand per
  request. The "what you'd hand-roll without a framework" floor.
- **`fastapi_app.py`** -- the same plain SQLAlchemy access pattern, on
  FastAPI instead of raw Starlette. Requires `pip install fastapi`
  (not a Zeython dependency -- this file exists purely as a reference
  point).

All three query the *same* `benchmark.db` (created once by `seed.py`
from Zeython's own `Item(Model)`, so it has Model's usual
`created_at`/`updated_at`/`is_deleted`/`deleted_at` columns alongside
`id`/`name` -- Starlette's and FastAPI's own `Item` classes just don't
declare those extra columns, which is fine, they select a subset).

# Benchmarks

Numbers from one run, on one machine, benchmarked with [`wrk`](https://github.com/wg/wrk) against three minimal apps in the repo's [`benchmarks/`](https://github.com/zaber-dev/Zeython/tree/main/benchmarks) directory: Zeython, raw Starlette (no framework, hand-rolled SQLAlchemy session per request), and FastAPI (the same hand-rolled data access, on a different framework). **Run them yourself** before trusting these for anything that matters — see `benchmarks/README.md` for exact commands. Absolute request/sec numbers are only meaningful on the machine that produced them; what's more likely to transfer is the *shape* of the difference between rows.

## Environment

- 4 vCPU, 15 GB RAM, Linux, single uvicorn process (no `--workers`) for every app — a deliberately unglamorous, shared sandbox, not dedicated benchmarking hardware.
- Python 3.11.15, FastAPI 0.141.1, Starlette (Zeython's pinned version), SQLAlchemy 2.0.52, uvicorn 0.52.3, wrk 4.1.0.
- `/json`: a static `{"hello": "world"}`, no database at all — isolates routing/response overhead.
- `/items`: `SELECT * FROM items` (100 rows, SQLite via `aiosqlite`).

## `/json` — no database involved

`wrk -t4 -c50 -d10s`

| App             | Req/sec | Avg latency |
| --------------- | ------- | ----------- |
| Starlette (raw) | 11,094  | 4.56 ms     |
| FastAPI         | 7,190   | 6.90 ms     |
| Zeython         | 4,279   | 11.81 ms    |

Zeython is slower than raw Starlette here, and that's expected, not a bug: `DatabaseServiceProvider` opens a real database session for *every* request — including this one, which never touches the database — via `async with self.database.session():` wrapping the whole request (see [Architecture](https://zeython.zaber.dev/docs/architecture/#request-scoped-database-sessions)). That's the cost of "a session is just always there, no per-route plumbing" as a default; an app that's mostly non-DB routes and cares about this specific number could look at making that session lazier, but today it's unconditional.

## `/items` — a real (if tiny) database query

`wrk -t4 -c50 -d10s`

| App             | Req/sec | Avg latency |
| --------------- | ------- | ----------- |
| Starlette (raw) | 155     | 303 ms      |
| FastAPI         | 132     | 360 ms      |
| Zeython         | 104     | 449 ms      |

The gap between apps *shrinks* once real SQLite I/O enters the picture — all three converge into the same rough band, a long way down from the `/json` numbers above. That's not framework overhead disappearing; it's `aiosqlite` becoming the bottleneck: each connection is served by a single background thread, so 50 concurrent requests queue up behind however many connections are actually open, regardless of which async framework is asking. At lower concurrency (`wrk -t2 -c5 -d8s`) all three land in a tighter 170–256 req/sec band, consistent with that read — SQLite/`aiosqlite` under concurrent access, not the web framework, is what's actually being measured once a query is involved. A real Postgres/MySQL deployment (see [Connection pooling](https://zeython.zaber.dev/docs/database/#connection-pooling)) would tell a different story here; this benchmark doesn't attempt one.

## Reading this honestly

- Zeython pays a real, measurable per-request tax for its request-scoped session default. If your app is overwhelmingly non-database routes at very high RPS, that's a genuine cost to know about going in.
- Once a database query is actually in the request path, the choice of database/driver dominates far more than which of these three you picked — don't let the `/json` gap above stand in for "how fast will my actual app be."
- This is not a TechEmpower-style exhaustive suite (no pipelining, no Postgres, no multi-worker `--workers N`, one machine, one run). Treat it as a starting point for your own measurement, not a verdict.

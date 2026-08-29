# Idempotency Keys

`zeython.idempotency` replays a mutating request's first response instead of running it again, for a client that must safely retry a `POST`/`PUT`/ `PATCH`/`DELETE` it can't tell succeeded or not — a dropped connection, a timeout, a proxy that gave up waiting. Without this, a naive retry can double-charge a card, double-send an email, or create a duplicate row; with it, the retry gets back exactly what the first attempt produced, without running the handler a second time.

Opt-in per request, the same way Stripe's API works: a request without an `Idempotency-Key` header is never touched.

## Setup

```python
# main.py
from zeython import Application, IdempotencyServiceProvider

app = Application()
app.register(IdempotencyServiceProvider(app))
```

```bash
curl -X POST http://localhost:8000/orders \
  -H 'Idempotency-Key: 8f14e45f-ceea-467e-9578-...' \
  -H 'Content-Type: application/json' \
  -d '{"amount": 2000}'
```

Send the same key again — from a genuine retry, or by hand to see it work — and the response comes back identical, with an added `Idempotency-Replayed: true` header, and the handler never runs a second time:

```bash
curl -X POST http://localhost:8000/orders \
  -H 'Idempotency-Key: 8f14e45f-ceea-467e-9578-...' \
  -H 'Content-Type: application/json' \
  -d '{"amount": 2000}'
# same body, same status code, + Idempotency-Replayed: true
```

Generating the key is the client's job, not the server's — usually a UUID minted once per logical operation (e.g. once when a "place order" button is clicked, reused across every retry of that same click, but never reused for the *next* order).

## Which requests this covers

By default: `POST`, `PUT`, `PATCH`, `DELETE` — the methods that aren't already naturally idempotent. `GET`/`HEAD`/`OPTIONS` are never touched, even with the header set, since retrying a `GET` is always safe on its own. Narrow it further if you only want this on specific operations (payments, say) rather than every mutating request:

```python
IdempotencyServiceProvider(app, methods=["POST"])
```

Records are scoped per method *and* path, so the same key value used against two different endpoints doesn't collide.

## A replayed key with a different body

If a repeated `Idempotency-Key` shows up with a **different** request body than the first time, that's almost always a client bug — reusing a key across two logically different operations — not a legitimate retry. This raises `ConflictException` (409) instead of silently returning a response for the wrong request:

```json
{"error": "Idempotency-Key '8f14e45f-...' was already used with a different request body.", "status": 409}
```

## Concurrent retries

A key that arrives again **while the first request with that key is still being processed** — a client that retries eagerly, before the first attempt has even finished — waits for it to finish, then replays its result, rather than running the operation a second time in parallel. This is correct within one worker process. Across multiple processes or machines, only the *stored result* is shared (see below); two processes racing on a brand-new key can both start processing it before either finishes — the same in-process-only limitation [`RateLimiter`](https://zeython.zaber.dev/docs/rate-limiting/#the-default-limiter-is-process-local) and [`Cache`](https://zeython.zaber.dev/docs/caching/index.md) already document for their default backends, not something new here.

## The default store is process-local

`IdempotencyServiceProvider` uses its own [`InMemoryCache`](https://zeython.zaber.dev/docs/caching/index.md) by default — correct for a single process, and a real limitation once you run multiple workers or machines: a retry that lands on a *different* process than the one that handled the original request won't find the stored response, and will process the request again. Share a [`RedisCache`](https://zeython.zaber.dev/docs/redis/index.md) instead for a store every process/machine sees:

```python
from zeython import Cache, IdempotencyServiceProvider, RedisCache

cache = RedisCache(app.config.get("redis.url"))
app.register(IdempotencyServiceProvider(app, cache=cache))
```

## Configuration

```python
IdempotencyServiceProvider(
    app,
    cache=None,                              # default: a fresh InMemoryCache()
    methods=["POST", "PUT", "PATCH", "DELETE"],  # default
    ttl=86400.0,                              # default: 24 hours
    header="Idempotency-Key",                 # default
)
```

`ttl` is how long a stored response stays replayable — after it expires, the same key is treated as brand new and the request runs again. 24 hours matches the retention window Stripe's own API documents; shorten it if your operations are retried on a much tighter loop, or lengthen it for something a client might reasonably retry a day later.

## Scope limits

- The request body is buffered in memory to compute its hash (for the conflict check above) and to replay it to your handler — the same trade-off [`ETagServiceProvider`](https://zeython.zaber.dev/docs/api-standards/#conditional-requests-etags) makes on the response side. Fine for a typical JSON request body; not a fit in front of a large streamed upload.
- There's no automatic cleanup beyond `ttl` — a very high-cardinality key space (a fresh UUID per request, correctly used) naturally self-limits since old entries simply expire; this isn't a request-deduplication cache meant to hold every request ever made indefinitely.

## API reference

See [`zeython.idempotency`](https://zeython.zaber.dev/docs/reference/http-api/index.md) for the full API.

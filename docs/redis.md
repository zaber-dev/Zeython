# Redis (Distributed Cache & Rate Limiting)

`InMemoryCache` and `InMemoryRateLimiter` are process-local by design —
correct and fast for a single worker, and a real limitation once you run
more than one: multiple worker processes or multiple machines each cache
and count independently, so a value written by one worker is invisible to
another, and an effective rate limit multiplies by worker count. `RedisCache`
and `RedisRateLimiter` are the opt-in, shared alternative — same
interfaces, backed by a Redis instance every worker points at.

## Setup

```bash
pip install zeython[redis]
```

```python
from zeython import Cache, RateLimiter, RedisCache, RedisRateLimiter

app.container.singleton(Cache, lambda: RedisCache(config.get("redis.url")))
app.container.singleton(RateLimiter, lambda: RedisRateLimiter(config.get("redis.url")))
```

Bind them directly instead of registering `CacheServiceProvider`/
`RateLimitServiceProvider` — those always bind the in-memory default.
`config.get("redis.url")` reads `REDIS_URL` from `.env`
(`redis://localhost:6379/0`, or your provider's connection string).

## RedisCache

Same `get`/`put`/`forget`/`has`/`flush`/`remember` interface as
`InMemoryCache`, with two real differences:

- **Values must be JSON-safe.** `InMemoryCache` holds any Python object in
  process memory; `RedisCache` JSON-encodes values to send them over the
  network, so only `dict`/`list`/`str`/`int`/`float`/`bool`/`None` survive
  the round trip. Cache a model's `to_dict()`, not the model instance
  itself.
- **`flush()` doesn't touch anything else on the same Redis.** Every key
  is namespaced under a prefix (default `"zeython:cache:"`), and `flush()`
  only clears that namespace via `SCAN`, never `FLUSHDB` — safe to point
  at a Redis instance shared with sessions, rate limiting, or anything
  else, without wiping their data too.

## RedisRateLimiter

Same `hit()` interface as `InMemoryRateLimiter`, but a different algorithm:
fixed-window (`INCR` + `EXPIRE`) rather than sliding-window-log. This is
the standard, well-known Redis rate-limiting pattern — and its standard
trade-off: a client can get up to `2x limit` requests through across a
window boundary (a burst just before the window resets, then another just
after). Accept that, or implement a sliding-window version yourself if you
need the tighter guarantee `InMemoryRateLimiter` provides.

Also namespaced under a prefix (default `"zeython:ratelimit:"`), same
reasoning as `RedisCache`.

## What isn't here: a Redis-backed Queue

`zeython.queue.Job` instances are deliberately never serialized — the
docs for `InMemoryQueue` are explicit that this is what lets a job's
constructor take anything, not just JSON-safe values. A Redis-backed queue
needs jobs to survive crossing a network boundary, which means picking a
serialization format and changing what a `Job` is allowed to hold — a
real design decision, not a drop-in swap the way `Cache`/`RateLimiter`
are. If you need a durable, distributed queue today, reach for a
purpose-built one (Celery, RQ, Dramatiq) rather than a half-fit Redis
`Queue` implementation; `Queue` stays an interface you can implement
against whichever one you pick.

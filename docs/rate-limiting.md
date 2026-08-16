# Rate Limiting

`zeython.rate_limit` gives you a `RateLimiter` bound in the container (an
in-memory sliding-window limiter by default), a `throttle()` guard for
protecting specific routes, and an opt-in blanket middleware for the whole
API.

## Why this exists by default on login/register

Without rate limiting, `/login` is a password oracle: an attacker can try
credentials as fast as the network allows. `zeython new` throttles the
generated `AuthController.login` and `.register` out of the box — 5 attempts
per minute per IP for login, 5 per hour for register. This is table stakes
for an auth endpoint, not an optional extra.

## Protecting a specific route

```python
from zeython.rate_limit import throttle

async def login(self, request):
    await throttle(request, limit=5, window=60)   # 5 requests/minute per IP
    ...
```

Raises `TooManyRequestsException` (429, with a `Retry-After` header) once
the limit is hit — already rendered as JSON by the framework's default
error handler, same as any other `HTTPException`.

### Custom keys

By default the key is the client's IP. Namespace it per-endpoint (so
`/login` and `/register` don't share a counter) or scope it to something
other than IP:

```python
from zeython.rate_limit import client_ip, throttle

await throttle(request, key=f"login:{client_ip(request)}", limit=5, window=60)
await throttle(request, key=f"login:{email}", limit=5, window=60)  # per-account instead of per-IP
```

## Blanket limiting across the whole API

Opt-in via `.env` — `RateLimitServiceProvider` is registered by every
generated app already, this just turns the middleware on:

```env
RATE_LIMIT_ENABLED=true
RATE_LIMIT_MAX_REQUESTS=60
RATE_LIMIT_WINDOW_SECONDS=60
```

This applies to every request regardless of route, independent of any
`throttle()` calls in your handlers — the two compose (a request can be
rejected by either).

## The default limiter is process-local

`InMemoryRateLimiter` counts hits in memory. That's correct and fast for a
single process, and a real limitation once you run multiple worker
processes or machines — each counts independently, so the *effective* limit
multiplies by worker count. For a distributed limit, implement `RateLimiter`
against a shared store (Redis `INCR`+`EXPIRE` is the usual choice) and bind
it in place of the default:

```python
from zeython import RateLimiter

app.container.singleton(RateLimiter, lambda: MyRedisRateLimiter(redis_client))
```

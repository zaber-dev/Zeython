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

## Response headers

Every response a `throttle()` call or the blanket middleware actually
limited — allowed or rejected — carries the standard headers GitHub's,
Stripe's, and Laravel's APIs send, so well-behaved clients can back off
before they get a 429 instead of learning the hard way:

| Header | Meaning |
|---|---|
| `X-RateLimit-Limit` | The `limit` passed to `throttle()` (or `RATE_LIMIT_MAX_REQUESTS`). |
| `X-RateLimit-Remaining` | Requests left in the current window. |
| `X-RateLimit-Reset` | Unix timestamp when the window resets. |
| `Retry-After` | 429 responses only — seconds to wait before retrying. |

This is handled automatically by `RateLimitHeadersMiddleware`, which
`RateLimitServiceProvider` registers unconditionally — it only ever
touches a response that a rate limiter already ran against, so a route
that never calls `throttle()` and isn't covered by the blanket middleware
sees no `X-RateLimit-*` headers at all.

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
multiplies by worker count. For a distributed limit shared across every
process, bind `RedisRateLimiter` in place of the default (requires the
`redis` extra: `pip install zeython[redis]`):

```python
from zeython.rate_limit import RateLimiter, RedisRateLimiter

app.container.singleton(RateLimiter, lambda: RedisRateLimiter(config.get("redis.url")))
```

Implement `RateLimiter` yourself instead if you need a different backend or
algorithm — it's a one-method interface (`hit(key, *, limit, window)`).

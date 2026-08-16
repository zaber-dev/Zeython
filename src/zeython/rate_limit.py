"""Rate limiting: an in-memory sliding-window limiter by default, a
per-route ``throttle()`` guard, and an opt-in blanket middleware.

The in-memory backend is process-local by design — correct for a single
worker, and a real (if common) limitation once you run multiple processes
or machines, where each would count independently. That's a documented
trade-off, not an oversight: :class:`RedisRateLimiter` is the opt-in,
shared alternative for when you need distributed limits.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import JSONResponse

from zeython.exceptions import TooManyRequestsException
from zeython.providers import ServiceProvider


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: float  #: seconds until the next hit would be allowed; 0 if allowed


class RateLimiter(ABC):
    """Counts hits against a key within a rolling time window."""

    @abstractmethod
    async def hit(self, key: str, *, limit: int, window: float) -> RateLimitResult:
        """Record a hit for ``key`` and report whether it's within ``limit`` per ``window`` seconds."""


class InMemoryRateLimiter(RateLimiter):
    """A sliding-window-log limiter, correct and simple, scoped to one process.

    Each key keeps a deque of hit timestamps; on every call, timestamps older
    than the window are dropped before counting. A single lock serializes
    hits — fine here since each check is a handful of in-memory operations,
    not I/O.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._clock = clock

    async def hit(self, key: str, *, limit: int, window: float) -> RateLimitResult:
        async with self._lock:
            now = self._clock()
            bucket = self._hits[key]
            cutoff = now - window

            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                retry_after = max(bucket[0] + window - now, 0.0)
                return RateLimitResult(allowed=False, remaining=0, retry_after=retry_after)

            bucket.append(now)
            return RateLimitResult(allowed=True, remaining=max(limit - len(bucket), 0), retry_after=0.0)


class RedisRateLimiter(RateLimiter):
    """A Redis-backed :class:`RateLimiter`, shared across every process/machine
    pointed at the same Redis — the limitation :class:`InMemoryRateLimiter`'s
    docstring names. Requires the ``redis`` extra (``pip install zeython[redis]``).

    Fixed-window (``INCR`` + ``EXPIRE``), not sliding-window-log like
    ``InMemoryRateLimiter`` — the standard, well-known Redis rate-limiting
    pattern, and its standard trade-off: a client can get up to ``2x limit``
    requests through across a window boundary (e.g. a burst just before the
    window resets, then another just after). Accept that, or implement a
    sliding-window version yourself if you need the tighter guarantee.

    All keys are namespaced under ``prefix`` (default ``"zeython:ratelimit:"``)
    — safe to point at a Redis instance shared with other subsystems.
    """

    def __init__(self, url: str, *, prefix: str = "zeython:ratelimit:") -> None:
        try:
            from redis.asyncio import Redis
        except ImportError as exc:
            raise ImportError(
                "RedisRateLimiter requires the redis package. Install it with: pip install zeython[redis]"
            ) from exc

        self._client = Redis.from_url(url)
        self._prefix = prefix

    async def hit(self, key: str, *, limit: int, window: float) -> RateLimitResult:
        redis_key = f"{self._prefix}{key}"
        count = await self._client.incr(redis_key)
        if count == 1:
            # Only the request that starts a new window sets its expiry --
            # a crash between INCR and EXPIRE could in principle leave a key
            # with no expiry (a well-known, generally-accepted risk of the
            # two-call INCR+EXPIRE pattern); a stray un-expiring key just
            # means that one key's window never resets, not a security hole.
            await self._client.expire(redis_key, max(int(window), 1))

        if count > limit:
            ttl = await self._client.ttl(redis_key)
            return RateLimitResult(allowed=False, remaining=0, retry_after=float(max(ttl, 0)))

        return RateLimitResult(allowed=True, remaining=max(limit - count, 0), retry_after=0.0)


def client_ip(request: Request) -> str:
    """The connecting client's IP, or ``"unknown"`` if the ASGI server didn't report one."""
    return request.client.host if request.client else "unknown"


async def throttle(request: Request, *, key: str | None = None, limit: int, window: float) -> None:
    """Raise :class:`~zeython.exceptions.TooManyRequestsException` past ``limit`` hits per ``window`` seconds.

    Defaults to limiting per client IP; pass ``key`` to scope it differently
    (e.g. ``f"login:{client_ip(request)}"`` to namespace it separately from
    other throttled endpoints, or ``f"login:{email}"`` to limit attempts per
    account regardless of source IP). Call at the top of any handler you
    want to protect::

        async def login(self, request):
            await throttle(request, limit=5, window=60)  # 5 attempts/minute per IP
    """
    limiter: RateLimiter = request.app.state.container.make(RateLimiter)
    effective_key = key or f"ip:{client_ip(request)}"
    result = await limiter.hit(effective_key, limit=limit, window=window)

    if not result.allowed:
        retry_after = int(result.retry_after) + 1
        raise TooManyRequestsException(
            f"Too many requests. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )


class RateLimitMiddleware:
    """Pure ASGI middleware applying a blanket per-IP limit to every request."""

    def __init__(self, app: object, *, limiter: RateLimiter, limit: int, window: float) -> None:
        self.app = app
        self.limiter = limiter
        self.limit = limit
        self.window = window

    async def __call__(self, scope: dict, receive: object, send: object) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)  # type: ignore[operator]
            return

        client = scope.get("client")
        key = f"ip:{client[0]}" if client else "ip:unknown"
        result = await self.limiter.hit(key, limit=self.limit, window=self.window)

        if not result.allowed:
            retry_after = int(result.retry_after) + 1
            response = JSONResponse(
                {"error": "Too many requests.", "status": 429},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)  # type: ignore[arg-type]
            return

        await self.app(scope, receive, send)  # type: ignore[operator]


class RateLimitServiceProvider(ServiceProvider):
    """Binds a :class:`RateLimiter` into the container. :class:`InMemoryRateLimiter`
    (process-local) by default.

    The limiter is always available for :func:`throttle` calls in your own
    handlers. The blanket, all-routes middleware is opt-in via ``.env``:

    - ``RATE_LIMIT_ENABLED`` — default ``false``
    - ``RATE_LIMIT_MAX_REQUESTS`` — default ``60``
    - ``RATE_LIMIT_WINDOW_SECONDS`` — default ``60``

    For a shared, distributed limiter, bind :class:`RedisRateLimiter`
    instead of registering this provider::

        app.container.singleton(RateLimiter, lambda: RedisRateLimiter(config.get("redis.url")))
    """

    def register(self) -> None:
        limiter = InMemoryRateLimiter()
        self.container.singleton(RateLimiter, lambda: limiter)

    def boot(self) -> None:
        if not bool(self.config.get("rate_limit.enabled", False)):
            return

        limiter = self.container.make(RateLimiter)
        self.app.add_middleware(
            RateLimitMiddleware,
            limiter=limiter,
            limit=int(self.config.get("rate_limit.max_requests", 60)),
            window=float(self.config.get("rate_limit.window_seconds", 60)),
        )


__all__ = [
    "RateLimiter",
    "InMemoryRateLimiter",
    "RedisRateLimiter",
    "RateLimitResult",
    "throttle",
    "client_ip",
    "RateLimitMiddleware",
    "RateLimitServiceProvider",
]

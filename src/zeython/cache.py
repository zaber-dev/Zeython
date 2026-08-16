"""Caching: an in-memory TTL cache by default, and ``remember()`` for the
common "check cache, else compute and store" pattern.

Like :class:`~zeython.rate_limit.RateLimiter`, the default backend is
process-local — correct for a single worker, and a real (if common)
limitation once you run multiple processes or machines, where each would
cache independently. :class:`RedisCache` is the opt-in, shared alternative.
"""

from __future__ import annotations

import asyncio
import json
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from zeython.providers import ServiceProvider

_MISSING = object()


class Cache(ABC):
    """Get/put/forget keyed values, with optional per-entry expiry."""

    @abstractmethod
    async def get(self, key: str, default: Any = None) -> Any:
        """The value stored for ``key``, or ``default`` if missing or expired."""

    @abstractmethod
    async def put(self, key: str, value: Any, *, ttl: float | None = None) -> None:
        """Store ``value`` under ``key``. ``ttl`` is seconds until expiry; ``None`` never expires."""

    @abstractmethod
    async def forget(self, key: str) -> None:
        """Remove ``key``, if present. A no-op if it isn't."""

    @abstractmethod
    async def has(self, key: str) -> bool:
        """Whether ``key`` currently holds an unexpired value."""

    @abstractmethod
    async def flush(self) -> None:
        """Remove everything."""

    async def remember(self, key: str, ttl: float | None, callback: Callable[[], Awaitable[Any]]) -> Any:
        """Return the cached value for ``key``, computing and storing it via ``callback`` on a miss.

        The common get-or-compute pattern in one call::

            posts = await cache.remember("posts:recent", 60, lambda: Post.all())

        ``callback`` only runs on a miss — a cache hit never calls it.
        """
        value = await self.get(key, _MISSING)
        if value is not _MISSING:
            return value
        value = await callback()
        await self.put(key, value, ttl=ttl)
        return value


@dataclass
class _Entry:
    value: Any
    expires_at: float | None  #: a `_clock()` timestamp; `None` never expires


class InMemoryCache(Cache):
    """A process-local dict cache, correct and simple.

    Expired entries are evicted lazily, on access — there's no background
    sweep, so an entry that's put and never read again sits in memory until
    the process restarts. Fine for typical cache sizes (route/query
    results, computed aggregates); not a fit for caching unboundedly many
    distinct keys.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._entries: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()
        self._clock = clock

    async def get(self, key: str, default: Any = None) -> Any:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return default
            if entry.expires_at is not None and entry.expires_at <= self._clock():
                del self._entries[key]
                return default
            return entry.value

    async def put(self, key: str, value: Any, *, ttl: float | None = None) -> None:
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be positive (or None for no expiry)")
        expires_at = self._clock() + ttl if ttl is not None else None
        async with self._lock:
            self._entries[key] = _Entry(value=value, expires_at=expires_at)

    async def forget(self, key: str) -> None:
        async with self._lock:
            self._entries.pop(key, None)

    async def has(self, key: str) -> bool:
        return await self.get(key, _MISSING) is not _MISSING

    async def flush(self) -> None:
        async with self._lock:
            self._entries.clear()


class RedisCache(Cache):
    """A Redis-backed :class:`Cache`, shared across every process/machine
    pointed at the same Redis — the limitation :class:`InMemoryCache`'s
    docstring names. Requires the ``redis`` extra (``pip install zeython[redis]``).

    Values are JSON-encoded to cross the network as bytes. Unlike
    ``InMemoryCache``, which can hold any Python object in process memory,
    only JSON-safe values (``dict``/``list``/``str``/``int``/``float``/
    ``bool``/``None``) survive the round trip here — cache a model's
    ``to_dict()``, not the model instance itself.

    All keys are namespaced under ``prefix`` (default ``"zeython:cache:"``),
    and :meth:`flush` only clears that namespace (via ``SCAN``, not
    ``FLUSHDB``) — safe to point at a Redis instance shared with other
    subsystems (sessions, rate limiting) without wiping their data too.
    """

    def __init__(self, url: str, *, prefix: str = "zeython:cache:") -> None:
        try:
            from redis.asyncio import Redis
        except ImportError as exc:
            raise ImportError(
                "RedisCache requires the redis package. Install it with: pip install zeython[redis]"
            ) from exc

        self._client = Redis.from_url(url)
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def get(self, key: str, default: Any = None) -> Any:
        raw = await self._client.get(self._key(key))
        if raw is None:
            return default
        return json.loads(raw)

    async def put(self, key: str, value: Any, *, ttl: float | None = None) -> None:
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be positive (or None for no expiry)")
        payload = json.dumps(value)
        if ttl is not None:
            await self._client.set(self._key(key), payload, px=int(ttl * 1000))
        else:
            await self._client.set(self._key(key), payload)

    async def forget(self, key: str) -> None:
        await self._client.delete(self._key(key))

    async def has(self, key: str) -> bool:
        return bool(await self._client.exists(self._key(key)))

    async def flush(self) -> None:
        # SCAN, not KEYS/FLUSHDB: doesn't block Redis on a large keyspace,
        # and only touches this cache's own namespace.
        async for redis_key in self._client.scan_iter(match=f"{self._prefix}*"):
            await self._client.delete(redis_key)


class CacheServiceProvider(ServiceProvider):
    """Binds a :class:`Cache` into the container. :class:`InMemoryCache` (process-local) by default.

    For a shared cache, bind :class:`RedisCache` instead of registering
    this provider::

        app.container.singleton(Cache, lambda: RedisCache(config.get("redis.url")))
    """

    def register(self) -> None:
        cache = InMemoryCache()
        self.container.singleton(Cache, lambda: cache)


__all__ = ["Cache", "InMemoryCache", "RedisCache", "CacheServiceProvider"]

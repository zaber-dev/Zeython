"""Tests for RedisCache/RedisRateLimiter -- skipped if the `redis` extra
isn't installed, or if no Redis server is reachable at TEST_REDIS_URL
(default redis://localhost:6379/15 -- db 15, to stay out of the way of
anything else that might be using db 0).
"""

import asyncio
import os
import tempfile

import pytest
import pytest_asyncio
from starlette.responses import JSONResponse

pytest.importorskip("redis")

from zeython.application import Application  # noqa: E402
from zeython.cache import RedisCache  # noqa: E402
from zeython.config import Config  # noqa: E402
from zeython.idempotency import IdempotencyServiceProvider  # noqa: E402
from zeython.rate_limit import RedisRateLimiter  # noqa: E402
from zeython.testing import client  # noqa: E402

REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")


@pytest_asyncio.fixture(autouse=True)
async def _require_redis() -> None:
    from redis.asyncio import Redis

    client = Redis.from_url(REDIS_URL)
    try:
        await client.ping()
    except Exception:
        pytest.skip(f"No Redis server reachable at {REDIS_URL}")
    finally:
        await client.aclose()


# -- RedisCache ---------------------------------------------------------------------


@pytest_asyncio.fixture
async def cache():
    instance = RedisCache(REDIS_URL, prefix="zeython-test:cache:")
    yield instance
    await instance.flush()


async def test_get_returns_default_for_a_missing_key(cache: RedisCache) -> None:
    assert await cache.get("missing") is None
    assert await cache.get("missing", "fallback") == "fallback"


async def test_put_then_get_roundtrips_json_safe_values(cache: RedisCache) -> None:
    await cache.put("dict", {"n": 1, "s": "hi", "list": [1, 2, 3], "nested": {"ok": True}})
    await cache.put("none", None)
    await cache.put("bool", False)

    assert await cache.get("dict") == {"n": 1, "s": "hi", "list": [1, 2, 3], "nested": {"ok": True}}
    # None is a valid *stored* value, distinct from "missing" -- has() disambiguates.
    assert await cache.has("none")
    assert await cache.get("none", "sentinel") is None
    assert await cache.get("bool") is False


async def test_has_reflects_presence(cache: RedisCache) -> None:
    assert not await cache.has("key")
    await cache.put("key", "value")
    assert await cache.has("key")


async def test_forget_removes_the_key(cache: RedisCache) -> None:
    await cache.put("key", "value")
    await cache.forget("key")
    assert await cache.get("key") is None


async def test_ttl_expires_the_key(cache: RedisCache) -> None:
    await cache.put("key", "value", ttl=0.2)
    assert await cache.get("key") == "value"
    await asyncio.sleep(0.4)
    assert await cache.get("key") is None


async def test_put_rejects_a_non_positive_ttl(cache: RedisCache) -> None:
    with pytest.raises(ValueError):
        await cache.put("key", "value", ttl=0)


async def test_flush_only_clears_this_caches_own_prefix(cache: RedisCache) -> None:
    other = RedisCache(REDIS_URL, prefix="zeython-test:other-cache:")
    try:
        await cache.put("mine", "value")
        await other.put("not-mine", "value")

        await cache.flush()

        assert await cache.get("mine") is None
        assert await other.get("not-mine") == "value"  # untouched -- flush() is not FLUSHDB
    finally:
        await other.flush()


async def test_two_cache_instances_share_the_same_backend(cache: RedisCache) -> None:
    # The whole point of RedisCache over InMemoryCache: a value written by
    # one process (here, one instance) is visible from a different one.
    other = RedisCache(REDIS_URL, prefix="zeython-test:cache:")

    await cache.put("shared", "written-by-cache")

    assert await other.get("shared") == "written-by-cache"


async def test_remember_works_against_the_redis_backend(cache: RedisCache) -> None:
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        return "computed"

    first = await cache.remember("key", 60, compute)
    second = await cache.remember("key", 60, compute)

    assert first == second == "computed"
    assert calls == 1


# -- RedisRateLimiter -----------------------------------------------------------------


@pytest_asyncio.fixture
async def limiter():
    instance = RedisRateLimiter(REDIS_URL, prefix="zeython-test:ratelimit:")
    yield instance
    async for redis_key in instance._client.scan_iter(match="zeython-test:ratelimit:*"):
        await instance._client.delete(redis_key)


async def test_allows_hits_up_to_the_limit(limiter: RedisRateLimiter) -> None:
    for _ in range(3):
        result = await limiter.hit("key", limit=3, window=60)
        assert result.allowed

    denied = await limiter.hit("key", limit=3, window=60)
    assert not denied.allowed
    assert denied.remaining == 0


async def test_remaining_count_decreases_with_each_hit(limiter: RedisRateLimiter) -> None:
    first = await limiter.hit("key", limit=5, window=60)
    second = await limiter.hit("key", limit=5, window=60)

    assert first.remaining == 4
    assert second.remaining == 3


async def test_window_expiry_allows_further_hits(limiter: RedisRateLimiter) -> None:
    for _ in range(2):
        assert (await limiter.hit("key", limit=2, window=1)).allowed
    assert not (await limiter.hit("key", limit=2, window=1)).allowed

    await asyncio.sleep(1.3)

    assert (await limiter.hit("key", limit=2, window=1)).allowed


async def test_different_keys_are_independent(limiter: RedisRateLimiter) -> None:
    for _ in range(3):
        assert (await limiter.hit("a", limit=3, window=60)).allowed

    assert not (await limiter.hit("a", limit=3, window=60)).allowed
    assert (await limiter.hit("b", limit=3, window=60)).allowed


async def test_two_limiter_instances_share_the_same_backend(limiter: RedisRateLimiter) -> None:
    other = RedisRateLimiter(REDIS_URL, prefix="zeython-test:ratelimit:")

    for _ in range(3):
        await limiter.hit("shared", limit=3, window=60)

    # A different instance sees the same count -- this is what
    # InMemoryRateLimiter cannot do across processes.
    denied = await other.hit("shared", limit=3, window=60)
    assert not denied.allowed


# -- IdempotencyMiddleware against RedisCache ------------------------------------------


async def test_idempotency_middleware_replays_across_a_shared_redis_cache(cache: RedisCache) -> None:
    # The point of RedisCache over InMemoryCache here: a record written by
    # processing a request through one Application instance is visible to
    # a *different* Application instance backed by the same Redis -- the
    # thing InMemoryCache can't do across processes.
    calls: list[int] = []

    def _build_app(tmp_path):
        app = Application(Config.load(tmp_path))
        app.register(IdempotencyServiceProvider(app, cache=cache))

        @app.post("/orders")
        async def create_order(request):
            calls.append(len(calls) + 1)
            return JSONResponse({"call": len(calls)}, status_code=201)

        return app

    with tempfile.TemporaryDirectory() as tmp_path:
        first_app = _build_app(tmp_path)
        second_app = _build_app(tmp_path)

        async with client(first_app) as http:
            first = await http.post("/orders", json={}, headers={"Idempotency-Key": "shared-key"})

        async with client(second_app) as http:
            second = await http.post("/orders", json={}, headers={"Idempotency-Key": "shared-key"})

    assert len(calls) == 1
    assert first.json() == second.json() == {"call": 1}
    assert second.headers["Idempotency-Replayed"] == "true"

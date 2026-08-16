from pathlib import Path

from zeython.application import Application
from zeython.cache import Cache, CacheServiceProvider, InMemoryCache
from zeython.config import Config

# -- InMemoryCache ------------------------------------------------------------------


class _FakeClock:
    """A controllable clock so TTL-expiry tests don't need real sleeps."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def test_get_returns_default_for_a_missing_key() -> None:
    cache = InMemoryCache()
    assert await cache.get("missing") is None
    assert await cache.get("missing", "fallback") == "fallback"


async def test_put_then_get_returns_the_stored_value() -> None:
    cache = InMemoryCache()
    await cache.put("key", {"n": 1})
    assert await cache.get("key") == {"n": 1}


async def test_has_reflects_presence() -> None:
    cache = InMemoryCache()
    assert not await cache.has("key")
    await cache.put("key", "value")
    assert await cache.has("key")


async def test_forget_removes_the_key() -> None:
    cache = InMemoryCache()
    await cache.put("key", "value")
    await cache.forget("key")
    assert await cache.get("key") is None


async def test_forget_is_a_no_op_for_a_missing_key() -> None:
    cache = InMemoryCache()
    await cache.forget("never-existed")  # must not raise


async def test_flush_clears_everything() -> None:
    cache = InMemoryCache()
    await cache.put("a", 1)
    await cache.put("b", 2)
    await cache.flush()
    assert await cache.get("a") is None
    assert await cache.get("b") is None


async def test_entry_without_ttl_never_expires() -> None:
    clock = _FakeClock()
    cache = InMemoryCache(clock=clock)
    await cache.put("key", "value")
    clock.advance(10_000)
    assert await cache.get("key") == "value"


async def test_entry_expires_after_its_ttl() -> None:
    clock = _FakeClock()
    cache = InMemoryCache(clock=clock)
    await cache.put("key", "value", ttl=10)

    clock.advance(9.999)
    assert await cache.get("key") == "value"

    clock.advance(0.002)  # past the ttl
    assert await cache.get("key") is None


async def test_put_rejects_a_non_positive_ttl() -> None:
    cache = InMemoryCache()
    try:
        await cache.put("key", "value", ttl=0)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


# -- Cache.remember() -----------------------------------------------------------------


async def test_remember_computes_and_stores_on_a_miss() -> None:
    cache = InMemoryCache()
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        return "computed"

    value = await cache.remember("key", 60, compute)

    assert value == "computed"
    assert calls == 1
    assert await cache.get("key") == "computed"


async def test_remember_does_not_recompute_on_a_hit() -> None:
    cache = InMemoryCache()
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        return calls

    first = await cache.remember("key", 60, compute)
    second = await cache.remember("key", 60, compute)

    assert first == 1
    assert second == 1
    assert calls == 1


async def test_remember_recomputes_after_expiry() -> None:
    clock = _FakeClock()
    cache = InMemoryCache(clock=clock)
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        return calls

    await cache.remember("key", 10, compute)
    clock.advance(10.001)
    second = await cache.remember("key", 10, compute)

    assert second == 2
    assert calls == 2


# -- CacheServiceProvider -------------------------------------------------------------


async def test_cache_is_available_in_the_container(tmp_path: Path) -> None:
    app = Application(Config.load(tmp_path))
    app.register(CacheServiceProvider)
    assert isinstance(app.container.make(Cache), InMemoryCache)


async def test_cache_is_a_singleton(tmp_path: Path) -> None:
    app = Application(Config.load(tmp_path))
    app.register(CacheServiceProvider)
    assert app.container.make(Cache) is app.container.make(Cache)

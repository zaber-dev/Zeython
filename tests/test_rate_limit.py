from pathlib import Path

from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.rate_limit import InMemoryRateLimiter, RateLimiter, RateLimitServiceProvider, throttle
from zeython.testing import client

# -- InMemoryRateLimiter -----------------------------------------------------------


class _FakeClock:
    """A controllable clock so window-expiry tests don't need real sleeps."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def test_allows_hits_up_to_the_limit() -> None:
    limiter = InMemoryRateLimiter(clock=_FakeClock())

    for _ in range(3):
        result = await limiter.hit("key", limit=3, window=60)
        assert result.allowed

    denied = await limiter.hit("key", limit=3, window=60)
    assert not denied.allowed
    assert denied.remaining == 0
    assert denied.retry_after > 0


async def test_remaining_count_decreases_with_each_hit() -> None:
    limiter = InMemoryRateLimiter(clock=_FakeClock())

    first = await limiter.hit("key", limit=5, window=60)
    second = await limiter.hit("key", limit=5, window=60)

    assert first.remaining == 4
    assert second.remaining == 3


async def test_window_expiry_allows_further_hits() -> None:
    clock = _FakeClock()
    limiter = InMemoryRateLimiter(clock=clock)

    for _ in range(2):
        assert (await limiter.hit("key", limit=2, window=10)).allowed
    assert not (await limiter.hit("key", limit=2, window=10)).allowed

    clock.advance(10.001)  # past the window

    assert (await limiter.hit("key", limit=2, window=10)).allowed


async def test_different_keys_are_independent() -> None:
    limiter = InMemoryRateLimiter(clock=_FakeClock())

    for _ in range(3):
        assert (await limiter.hit("a", limit=3, window=60)).allowed

    # "a" is now exhausted, but "b" starts fresh
    assert not (await limiter.hit("a", limit=3, window=60)).allowed
    assert (await limiter.hit("b", limit=3, window=60)).allowed


# -- throttle() guard ---------------------------------------------------------------


def _make_app(tmp_path: Path) -> Application:
    app = Application(Config.load(tmp_path))
    app.register(RateLimitServiceProvider)
    return app


async def test_throttle_allows_within_limit(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    @app.get("/ping")
    async def ping(request):
        await throttle(request, key="test", limit=3, window=60)
        return JSONResponse({"ok": True})

    async with client(app) as http:
        for _ in range(3):
            response = await http.get("/ping")
            assert response.status_code == 200


async def test_throttle_returns_429_with_retry_after_header(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    @app.get("/ping")
    async def ping(request):
        await throttle(request, key="test", limit=2, window=60)
        return JSONResponse({"ok": True})

    async with client(app) as http:
        await http.get("/ping")
        await http.get("/ping")
        response = await http.get("/ping")

    assert response.status_code == 429
    assert "retry-after" in {k.lower() for k in response.headers}
    assert response.json()["status"] == 429


async def test_throttle_defaults_to_per_ip_key(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    @app.get("/ping")
    async def ping(request):
        await throttle(request, limit=1, window=60)
        return JSONResponse({"ok": True})

    async with client(app) as http:
        first = await http.get("/ping")
        second = await http.get("/ping")

    assert first.status_code == 200
    assert second.status_code == 429


# -- RateLimitMiddleware (opt-in, blanket) -------------------------------------------


async def test_middleware_disabled_by_default(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    @app.get("/ping")
    async def ping(request):
        return JSONResponse({"ok": True})

    async with client(app) as http:
        for _ in range(10):
            response = await http.get("/ping")
            assert response.status_code == 200


async def test_middleware_enforces_blanket_limit_when_enabled(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "RATE_LIMIT_ENABLED=true\nRATE_LIMIT_MAX_REQUESTS=3\nRATE_LIMIT_WINDOW_SECONDS=60\n"
    )
    app = _make_app(tmp_path)

    @app.get("/ping")
    async def ping(request):
        return JSONResponse({"ok": True})

    async with client(app) as http:
        statuses = [(await http.get("/ping")).status_code for _ in range(4)]

    assert statuses == [200, 200, 200, 429]


async def test_rate_limiter_is_available_in_the_container(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    assert isinstance(app.container.make(RateLimiter), InMemoryRateLimiter)

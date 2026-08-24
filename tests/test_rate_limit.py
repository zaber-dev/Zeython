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


async def test_tracked_key_count_is_bounded_by_max_tracked_keys() -> None:
    # Regression guard: an idle key's now-empty bucket is only ever
    # cleaned up by another hit() call for that *same* key -- without a
    # bound, a flood of distinct keys (e.g. one per attacker-controlled
    # email/IP, exactly the key pattern throttle()'s own docstring
    # suggests) would grow the limiter's internal dict without limit,
    # one abandoned entry per attempt.
    limiter = InMemoryRateLimiter(clock=_FakeClock(), max_tracked_keys=10)

    for i in range(1000):
        await limiter.hit(f"attacker-key-{i}", limit=5, window=60)

    assert len(limiter._hits) <= 10


async def test_eviction_under_the_cap_does_not_break_an_active_keys_limit() -> None:
    limiter = InMemoryRateLimiter(clock=_FakeClock(), max_tracked_keys=2)

    await limiter.hit("keep-me", limit=3, window=60)
    # Push "keep-me" out of the cap by touching two other keys.
    await limiter.hit("other-1", limit=3, window=60)
    await limiter.hit("other-2", limit=3, window=60)

    # "keep-me" was evicted, so it now starts a fresh window instead of
    # continuing its old one -- the accepted trade-off, not a crash or a
    # permanently-stuck limiter.
    result = await limiter.hit("keep-me", limit=3, window=60)
    assert result.allowed
    assert result.remaining == 2


async def test_different_keys_are_independent() -> None:
    limiter = InMemoryRateLimiter(clock=_FakeClock())

    for _ in range(3):
        assert (await limiter.hit("a", limit=3, window=60)).allowed

    # "a" is now exhausted, but "b" starts fresh
    assert not (await limiter.hit("a", limit=3, window=60)).allowed
    assert (await limiter.hit("b", limit=3, window=60)).allowed


async def test_result_reports_limit_and_reset_after() -> None:
    clock = _FakeClock()
    limiter = InMemoryRateLimiter(clock=clock)

    first = await limiter.hit("key", limit=2, window=10)
    assert first.limit == 2
    assert first.reset_after == 10  # window resets 10s after this, the only hit so far

    clock.advance(1)
    second = await limiter.hit("key", limit=2, window=10)
    assert second.allowed
    assert second.reset_after == 9  # still measured from the first hit

    denied = await limiter.hit("key", limit=2, window=10)
    assert not denied.allowed
    assert denied.limit == 2
    assert denied.reset_after == denied.retry_after == 9


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


async def test_throttle_sets_ratelimit_headers_on_allowed_response(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    @app.get("/ping")
    async def ping(request):
        await throttle(request, key="test", limit=3, window=60)
        return JSONResponse({"ok": True})

    async with client(app) as http:
        response = await http.get("/ping")

    assert response.headers["X-RateLimit-Limit"] == "3"
    assert response.headers["X-RateLimit-Remaining"] == "2"
    assert int(response.headers["X-RateLimit-Reset"]) > 0


async def test_throttle_sets_ratelimit_headers_on_429_response(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    @app.get("/ping")
    async def ping(request):
        await throttle(request, key="test", limit=1, window=60)
        return JSONResponse({"ok": True})

    async with client(app) as http:
        await http.get("/ping")
        response = await http.get("/ping")

    assert response.status_code == 429
    assert response.headers["X-RateLimit-Limit"] == "1"
    assert response.headers["X-RateLimit-Remaining"] == "0"
    assert int(response.headers["X-RateLimit-Reset"]) > 0


async def test_ratelimit_headers_absent_when_throttle_never_called(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    @app.get("/ping")
    async def ping(request):
        return JSONResponse({"ok": True})

    async with client(app) as http:
        response = await http.get("/ping")

    assert "X-RateLimit-Limit" not in response.headers


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


async def test_middleware_sets_ratelimit_headers_on_allowed_and_429_responses(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "RATE_LIMIT_ENABLED=true\nRATE_LIMIT_MAX_REQUESTS=2\nRATE_LIMIT_WINDOW_SECONDS=60\n"
    )
    app = _make_app(tmp_path)

    @app.get("/ping")
    async def ping(request):
        return JSONResponse({"ok": True})

    async with client(app) as http:
        allowed = await http.get("/ping")
        await http.get("/ping")
        denied = await http.get("/ping")

    assert allowed.headers["X-RateLimit-Limit"] == "2"
    assert allowed.headers["X-RateLimit-Remaining"] == "1"

    assert denied.status_code == 429
    assert denied.headers["X-RateLimit-Limit"] == "2"
    assert denied.headers["X-RateLimit-Remaining"] == "0"


async def test_blanket_middleware_and_throttle_do_not_share_a_counter(tmp_path: Path) -> None:
    # Regression guard: the blanket middleware and throttle()'s own
    # default key both used to be exactly f"ip:{ip}" -- identical, not
    # just similarly shaped. A request to a throttle()-protected route
    # would hit the same counter this middleware had just hit for that
    # same request (double-counting one request against one shared
    # budget), and unrelated traffic to *other* routes would eat into a
    # route's own dedicated throttle() allowance.
    # A high blanket limit -- deliberately not the thing under test here,
    # only there so it never itself denies a request and muddy the result.
    (tmp_path / ".env").write_text(
        "RATE_LIMIT_ENABLED=true\nRATE_LIMIT_MAX_REQUESTS=100\nRATE_LIMIT_WINDOW_SECONDS=60\n"
    )
    app = _make_app(tmp_path)

    @app.get("/other")
    async def other(request):
        return JSONResponse({"ok": True})

    @app.get("/login")
    async def login(request):
        await throttle(request, limit=5, window=60)
        return JSONResponse({"ok": True})

    async with client(app) as http:
        # Plain traffic to an unrelated route -- each of these still hits
        # the blanket middleware's own counter.
        await http.get("/other")
        await http.get("/other")
        await http.get("/other")

        # /login's own throttle() counter must be untouched by that --
        # its very first hit, reporting the full remaining budget.
        login_response = await http.get("/login")

    assert login_response.status_code == 200
    assert login_response.headers["X-RateLimit-Limit"] == "5"
    assert login_response.headers["X-RateLimit-Remaining"] == "4"


async def test_rate_limiter_is_available_in_the_container(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    assert isinstance(app.container.make(RateLimiter), InMemoryRateLimiter)

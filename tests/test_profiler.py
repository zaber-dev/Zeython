"""Tests for zeython.profiler -- an opt-in, APP_DEBUG-only record of the
SQL queries a request ran, exposed via X-Debug-* response headers.
"""

import logging
from pathlib import Path

import pytest
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.db import Model
from zeython.db.session import Database
from zeython.profiler import DEFAULT_SLOW_QUERY_MS, RequestProfilerServiceProvider, current_queries
from zeython.providers import DatabaseServiceProvider
from zeython.testing import client


class ProfilerWidget(Model):
    __tablename__ = "profiler_test_widgets"
    name: Mapped[str] = mapped_column(String(100))


async def _make_app(tmp_path: Path, *, debug: bool = True, slow_query_ms: float | None = None) -> Application:
    lines = ["APP_SECRET_KEY=test\nDATABASE_URL=sqlite+aiosqlite:///:memory:\n"]
    lines.append(f"APP_DEBUG={'true' if debug else 'false'}\n")
    if slow_query_ms is not None:
        lines.append(f"PROFILER_SLOW_QUERY_MS={slow_query_ms}\n")
    (tmp_path / ".env").write_text("".join(lines))

    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)
    app.register(RequestProfilerServiceProvider(app))

    database = app.container.make(Database)
    async with database.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)

    return app


async def test_debug_headers_reflect_the_queries_a_request_ran(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    @app.get("/widgets")
    async def widgets(request):
        async with app.container.make(Database).session():
            await ProfilerWidget.create(name="a")
            await ProfilerWidget.create(name="b")
            await ProfilerWidget.all()
        return JSONResponse({"ok": True})

    async with client(app) as http:
        response = await http.get("/widgets")

    assert response.status_code == 200
    assert int(response.headers["X-Debug-Query-Count"]) >= 3  # 2 inserts + 1 select, at least
    assert float(response.headers["X-Debug-Query-Time-Ms"]) >= 0
    assert float(response.headers["X-Debug-Duration-Ms"]) >= 0


async def test_no_debug_headers_when_app_debug_is_false(tmp_path: Path) -> None:
    app = await _make_app(tmp_path, debug=False)

    @app.get("/ping")
    async def ping(request):
        return JSONResponse({"ok": True})

    async with client(app) as http:
        response = await http.get("/ping")

    assert "X-Debug-Query-Count" not in response.headers


async def test_query_count_is_zero_for_a_request_that_touches_no_database(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    @app.get("/ping")
    async def ping(request):
        return JSONResponse({"ok": True})

    async with client(app) as http:
        response = await http.get("/ping")

    assert response.headers["X-Debug-Query-Count"] == "0"
    assert response.headers["X-Debug-Query-Time-Ms"] == "0.00"


async def test_current_queries_is_visible_from_inside_the_handler(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    seen = {}

    @app.get("/widgets")
    async def widgets(request):
        async with app.container.make(Database).session():
            await ProfilerWidget.create(name="a")
        seen["count"] = len(current_queries())
        return JSONResponse({"ok": True})

    async with client(app) as http:
        await http.get("/widgets")

    assert seen["count"] >= 1


async def test_current_queries_is_empty_outside_a_request() -> None:
    assert current_queries() == []


async def test_a_crashed_requests_queries_do_not_leak_into_later_requests(tmp_path: Path) -> None:
    # Regression guard: a crash used to leave the contextvar bound to that
    # request's query list forever (deliberately, so the crash handler
    # could still read it) -- but since a later successful request's own
    # reset() just unwinds back to that same stale binding instead of
    # clearing it, the leaked list would keep reappearing indefinitely.
    # An inline ASGITransport call has no per-request asyncio Task
    # boundary, so this is directly observable within one test -- the same
    # reason this uses raise_app_exceptions=False directly rather than
    # zeython.testing.client(): Starlette's ServerErrorMiddleware always
    # re-raises after sending its response (so a real server can log it,
    # or a test client can opt into seeing it), which httpx would
    # otherwise turn into a raised exception here instead of a response.
    import httpx

    app = await _make_app(tmp_path)

    @app.get("/boom")
    async def boom(request):
        async with app.container.make(Database).session():
            await ProfilerWidget.create(name="a")
        raise RuntimeError("kaboom")

    @app.get("/ok")
    async def ok(request):
        return JSONResponse({"ok": True})

    transport = httpx.ASGITransport(app=app.asgi, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        crash_response = await http.get("/boom")
        assert crash_response.status_code == 500
        assert crash_response.json().get("queries")  # the crash's own queries, still reported

        await http.get("/ok")
        await http.get("/ok")

    # Back in the ambient context (this test function's own asyncio Task,
    # the same one the client ran every request on above) -- must not
    # still see the crashed request's queries two clean requests later.
    assert current_queries() == []


async def test_query_count_is_scoped_per_request_not_cumulative(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    @app.get("/widgets")
    async def widgets(request):
        async with app.container.make(Database).session():
            await ProfilerWidget.create(name="a")
        return JSONResponse({"ok": True})

    async with client(app) as http:
        counts = []
        for _ in range(3):
            response = await http.get("/widgets")
            counts.append(int(response.headers["X-Debug-Query-Count"]))

    # Same handler, same work every time -- if the counter accumulated
    # across requests instead of resetting, later counts would be higher.
    assert len(set(counts)) == 1


async def test_slow_query_is_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    app = await _make_app(tmp_path, slow_query_ms=0)  # every query is "slow" at a 0ms threshold

    @app.get("/widgets")
    async def widgets(request):
        async with app.container.make(Database).session():
            await ProfilerWidget.create(name="a")
        return JSONResponse({"ok": True})

    with caplog.at_level(logging.WARNING, logger="zeython.profiler"):
        async with client(app) as http:
            await http.get("/widgets")

    warnings = [r for r in caplog.records if r.name == "zeython.profiler"]
    assert warnings
    assert all("Slow query on /widgets" in w.message for w in warnings)


async def test_no_slow_query_warning_under_the_default_threshold(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    app = await _make_app(tmp_path)  # DEFAULT_SLOW_QUERY_MS (100ms) -- an in-memory sqlite insert is nowhere close

    @app.get("/widgets")
    async def widgets(request):
        async with app.container.make(Database).session():
            await ProfilerWidget.create(name="a")
        return JSONResponse({"ok": True})

    with caplog.at_level(logging.WARNING, logger="zeython.profiler"):
        async with client(app) as http:
            await http.get("/widgets")

    assert not [r for r in caplog.records if r.name == "zeython.profiler"]


def test_default_slow_query_threshold_is_100ms() -> None:
    assert DEFAULT_SLOW_QUERY_MS == 100.0

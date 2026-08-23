"""Tests for DatabaseSessionMiddleware's commit/rollback decision --
specifically that it's driven by the actual response status, not just
whether an exception propagated past this middleware.

Regression coverage for a real bug: Starlette's own ExceptionMiddleware
sits *inside* every user-added middleware (including this one) and fully
handles any registered exception class -- including every zeython
HTTPException subclass (ValidationException, NotFoundException, etc.) --
building and sending the response itself without ever re-raising past
this middleware. Before this fix, DatabaseSessionMiddleware only rolled
back when an exception actually reached it, so `self.app(...)` returning
normally (as it does for a "handled" HTTPException) always committed --
silently persisting writes made earlier in a request the handler meant to
abort. Verified via a real ASGI round-trip (zeython.testing.client()),
not a direct handler call, since the bug is specifically about how
Starlette's own middleware stack behaves.
"""

from pathlib import Path

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from starlette.responses import JSONResponse, RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER

from zeython.application import Application
from zeython.config import Config
from zeython.db import Model
from zeython.db.session import Database
from zeython.exceptions import NotFoundException, ValidationException
from zeython.providers import DatabaseServiceProvider
from zeython.testing import client


class Widget(Model):
    __tablename__ = "session_mw_widgets"

    name: Mapped[str] = mapped_column(String(100))


async def _make_app(tmp_path: Path) -> Application:
    (tmp_path / ".env").write_text("APP_SECRET_KEY=test\nDATABASE_URL=sqlite+aiosqlite:///:memory:\n")
    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)

    database = app.container.make(Database)
    async with database.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)

    return app


async def test_a_normal_successful_request_commits(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    @app.post("/widgets")
    async def create(request):
        await Widget.create(name="kept")
        return JSONResponse({"ok": True}, status_code=201)

    async with client(app) as http:
        response = await http.post("/widgets")
        assert response.status_code == 201

    database = app.container.make(Database)
    async with database.session():
        assert [w.name for w in await Widget.all()] == ["kept"]


async def test_raising_a_zeython_http_exception_after_a_write_rolls_it_back(tmp_path: Path) -> None:
    # The core regression: ValidationException is handled entirely by
    # Starlette's inner ExceptionMiddleware, which never re-raises past
    # DatabaseSessionMiddleware -- so this must not be silently committed.
    app = await _make_app(tmp_path)

    @app.post("/widgets")
    async def create(request):
        await Widget.create(name="should-not-be-kept")
        raise ValidationException({"name": ["nope"]})

    async with client(app) as http:
        response = await http.post("/widgets")
        assert response.status_code == 422

    database = app.container.make(Database)
    async with database.session():
        assert await Widget.all() == []


async def test_raising_not_found_after_a_write_rolls_it_back(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    @app.post("/widgets")
    async def create(request):
        await Widget.create(name="should-not-be-kept")
        raise NotFoundException("nope")

    async with client(app) as http:
        response = await http.post("/widgets")
        assert response.status_code == 404

    database = app.container.make(Database)
    async with database.session():
        assert await Widget.all() == []


async def test_a_genuinely_unhandled_exception_after_a_write_still_rolls_it_back(tmp_path: Path) -> None:
    # Pre-existing behavior (not the regression itself) -- must keep working.
    import httpx

    app = await _make_app(tmp_path)

    @app.post("/widgets")
    async def create(request):
        await Widget.create(name="should-not-be-kept")
        raise ValueError("kaboom")

    transport = httpx.ASGITransport(app=app.asgi, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        response = await http.post("/widgets")
        assert response.status_code == 500

    database = app.container.make(Database)
    async with database.session():
        assert await Widget.all() == []


async def test_a_redirect_response_after_a_write_still_commits(tmp_path: Path) -> None:
    # status < 400 covers 3xx too -- the post/redirect/get pattern
    # shouldn't have its write rolled back just because it isn't a 2xx.
    app = await _make_app(tmp_path)

    @app.post("/widgets")
    async def create(request):
        await Widget.create(name="kept")
        return RedirectResponse("/widgets", status_code=HTTP_303_SEE_OTHER)

    async with client(app) as http:
        response = await http.post("/widgets", follow_redirects=False)
        assert response.status_code == 303

    database = app.container.make(Database)
    async with database.session():
        assert [w.name for w in await Widget.all()] == ["kept"]

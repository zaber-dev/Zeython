"""Tests for the newer zeython.testing helpers: login_as() and
transactional_session().
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.auth import Authenticatable, AuthServiceProvider, require_auth
from zeython.config import Config
from zeython.db import Model
from zeython.db.session import Database, current_session
from zeython.providers import DatabaseServiceProvider
from zeython.testing import client, login_as, transactional_session


class HelperUser(Model, Authenticatable):
    __tablename__ = "helper_users"
    __hidden__ = ("password_hash",)

    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))


class HelperWidget(Model):
    __tablename__ = "helper_widgets"

    name: Mapped[str] = mapped_column(String(100))


async def _make_app(tmp_path: Path) -> Application:
    (tmp_path / ".env").write_text(
        "APP_SECRET_KEY=test-only-secret-not-for-production\nDATABASE_URL=sqlite+aiosqlite:///:memory:\n"
    )
    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)
    app.register(AuthServiceProvider(app, user_model=HelperUser))

    database = app.container.make(Database)
    async with database.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)

    @app.get("/me")
    async def me(request):
        user = await require_auth(request)
        return JSONResponse({"email": user.email})

    return app


# -- login_as() -----------------------------------------------------------------------


async def test_login_as_authenticates_the_client_without_a_real_login_post(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with app.container.make(Database).session():
        user = HelperUser(email="ada@example.com")
        user.set_password("hunter2")
        await user.save()

    async with client(app) as http:
        login_as(http, app, user)
        response = await http.get("/me")

    assert response.status_code == 200
    assert response.json() == {"email": "ada@example.com"}


async def test_without_login_as_the_same_route_requires_authentication(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/me")

    assert response.status_code == 401


async def test_login_as_produces_a_cookie_a_real_login_would_also_accept(tmp_path: Path) -> None:
    # Round-trips through the real login()/require_auth() machinery, not
    # just a check that *some* cookie got set -- confirms the signed
    # cookie login_as() builds is byte-for-byte compatible with what
    # SessionMiddleware itself would produce and later accept.
    from zeython.auth import login

    app = await _make_app(tmp_path)

    async with app.container.make(Database).session():
        user = HelperUser(email="real-login@example.com")
        user.set_password("hunter2")
        await user.save()

    @app.post("/manual-login")
    async def manual_login(request):
        login(request, user)
        return JSONResponse({"ok": True})

    async with client(app) as real_login_client:
        await real_login_client.get("/")  # primes CSRF cookie
        await real_login_client.post("/manual-login")
        real_response = await real_login_client.get("/me")

    async with client(app) as helper_client:
        login_as(helper_client, app, user)
        helper_response = await helper_client.get("/me")

    assert real_response.status_code == helper_response.status_code == 200
    assert real_response.json() == helper_response.json()


# -- transactional_session() -----------------------------------------------------------


@pytest_asyncio.fixture
async def widget_database() -> AsyncIterator[Database]:
    db = Database("sqlite+aiosqlite:///:memory:")
    async with db.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)
    yield db
    await db.dispose()


async def test_writes_inside_are_visible_to_queries_in_the_same_block(widget_database: Database) -> None:
    async with transactional_session(widget_database):
        await HelperWidget.create(name="visible-within-the-block")
        names = {w.name for w in await HelperWidget.all()}

    assert names == {"visible-within-the-block"}


async def test_writes_do_not_persist_past_the_block(widget_database: Database) -> None:
    async with transactional_session(widget_database):
        await HelperWidget.create(name="should-not-persist")

    async with widget_database.session():
        assert await HelperWidget.all() == []


async def test_writes_do_not_persist_even_when_the_block_raises(widget_database: Database) -> None:
    import pytest

    with pytest.raises(ValueError, match="boom"):
        async with transactional_session(widget_database):
            await HelperWidget.create(name="should-also-not-persist")
            raise ValueError("boom")

    async with widget_database.session():
        assert await HelperWidget.all() == []


async def test_transactional_session_yields_the_current_session(widget_database: Database) -> None:
    async with transactional_session(widget_database) as session:
        assert session is current_session()

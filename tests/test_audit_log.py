"""Tests for zeython.audit_log -- an automatic changelog of who created,
updated, or deleted which model records, and what changed, built on the
existing Observer system.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from starlette.responses import JSONResponse

from zeython.api_auth import ApiAuthServiceProvider, TokenManager
from zeython.application import Application
from zeython.audit_log import (
    AuditLogServiceProvider,
    AuditObserver,
    audit_trail,
    current_actor,
    set_actor,
)
from zeython.auth import AuthServiceProvider, login
from zeython.config import Config
from zeython.db import Model
from zeython.db.session import Database
from zeython.providers import DatabaseServiceProvider
from zeython.testing import client


class AuditUser(Model):
    __tablename__ = "audit_test_users"

    email: Mapped[str] = mapped_column(String(255))


class AuditedThing(Model):
    __tablename__ = "audit_test_things"
    __hidden__ = ("secret",)

    name: Mapped[str] = mapped_column(String(255))
    secret: Mapped[str] = mapped_column(String(255), default="")


class AuditLogRecord(Model):
    __tablename__ = "audit_test_records"

    auditable_type: Mapped[str] = mapped_column(String(255))
    auditable_id: Mapped[int] = mapped_column(Integer)
    event: Mapped[str] = mapped_column(String(50))
    changes: Mapped[dict] = mapped_column(JSON)
    actor_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


@pytest.fixture(autouse=True)
def _reset_observers() -> None:
    AuditedThing.__observers__ = []
    AuditLogRecord.__observers__ = []


@pytest_asyncio.fixture
async def database() -> AsyncIterator[Database]:
    db = Database("sqlite+aiosqlite:///:memory:")
    async with db.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)
    yield db
    await db.dispose()


@asynccontextmanager
async def session_scope(database: Database):
    async with database.session() as session:
        yield session


# -- AuditObserver: created/updated/deleted -------------------------------------------


async def test_created_event_records_every_non_hidden_field(database: Database) -> None:
    AuditedThing.observe(AuditObserver(AuditLogRecord))

    async with session_scope(database):
        thing = await AuditedThing.create(name="Widget", secret="shh")
        entries = await AuditLogRecord.all()

    assert len(entries) == 1
    entry = entries[0]
    assert entry.auditable_type == "AuditedThing"
    assert entry.auditable_id == thing.id
    assert entry.event == "created"
    assert entry.changes == {"name": {"old": None, "new": "Widget"}}


async def test_updated_event_records_only_changed_fields(database: Database) -> None:
    AuditedThing.observe(AuditObserver(AuditLogRecord))

    async with session_scope(database):
        thing = await AuditedThing.create(name="Widget", secret="shh")
        await thing.update(name="Widget Two")
        entries = await AuditLogRecord.all()

    updated_entries = [e for e in entries if e.event == "updated"]
    assert len(updated_entries) == 1
    assert updated_entries[0].changes == {"name": {"old": "Widget", "new": "Widget Two"}}


async def test_updated_event_with_no_actual_change_writes_no_row(database: Database) -> None:
    AuditedThing.observe(AuditObserver(AuditLogRecord))

    async with session_scope(database):
        thing = await AuditedThing.create(name="Widget")
        await thing.update(name="Widget")  # same value -- nothing actually changed
        entries = await AuditLogRecord.all()

    assert [e.event for e in entries] == ["created"]


async def test_soft_deleted_event_records_last_known_values(database: Database) -> None:
    AuditedThing.observe(AuditObserver(AuditLogRecord))

    async with session_scope(database):
        thing = await AuditedThing.create(name="Widget", secret="shh")
        await thing.delete(soft=True)
        entries = await AuditLogRecord.all()

    deleted_entries = [e for e in entries if e.event == "deleted"]
    assert len(deleted_entries) == 1
    assert deleted_entries[0].changes == {"name": {"old": "Widget", "new": None}}


async def test_hard_deleted_event_records_last_known_values(database: Database) -> None:
    # The whole point of capturing this in deleted() rather than reading
    # the row back later -- a hard-deleted row is actually gone.
    AuditedThing.observe(AuditObserver(AuditLogRecord))

    async with session_scope(database):
        thing = await AuditedThing.create(name="Widget")
        await thing.delete(soft=False)
        entries = await AuditLogRecord.all()

    deleted_entries = [e for e in entries if e.event == "deleted"]
    assert deleted_entries[0].changes == {"name": {"old": "Widget", "new": None}}


async def test_hidden_fields_are_never_recorded(database: Database) -> None:
    AuditedThing.observe(AuditObserver(AuditLogRecord))

    async with session_scope(database):
        thing = await AuditedThing.create(name="Widget", secret="shh")
        await thing.update(secret="different-secret")
        entries = await AuditLogRecord.all()

    for entry in entries:
        assert "secret" not in entry.changes


async def test_attaching_observer_to_its_own_record_model_raises(database: Database) -> None:
    # Regression guard against the infinite-recursion footgun: auditing
    # the audit log's own table would make every entry's creation write
    # another entry, without end.
    AuditLogRecord.observe(AuditObserver(AuditLogRecord))

    with pytest.raises(RuntimeError, match="itself"):
        async with session_scope(database):
            await AuditLogRecord.create(
                auditable_type="X", auditable_id=1, event="created", changes={}
            )


# -- current_actor() / set_actor() -----------------------------------------------------


async def test_current_actor_is_none_by_default() -> None:
    assert current_actor() is None


async def test_set_actor_stores_type_and_id(database: Database) -> None:
    async with session_scope(database):
        user = await AuditUser.create(email="ada@example.com")
        set_actor(user)
        assert current_actor() == ("AuditUser", user.id)

        set_actor(None)
        assert current_actor() is None


async def test_audit_entries_are_attributed_to_the_current_actor(database: Database) -> None:
    AuditedThing.observe(AuditObserver(AuditLogRecord))

    async with session_scope(database):
        user = await AuditUser.create(email="ada@example.com")
        set_actor(user)
        await AuditedThing.create(name="Widget")
        entries = await AuditLogRecord.all()

    assert entries[0].actor_type == "AuditUser"
    assert entries[0].actor_id == user.id


# -- audit_trail() ----------------------------------------------------------------------


async def test_audit_trail_returns_this_records_entries_oldest_first(database: Database) -> None:
    AuditedThing.observe(AuditObserver(AuditLogRecord))

    async with session_scope(database):
        thing = await AuditedThing.create(name="Widget")
        other = await AuditedThing.create(name="Other")
        await thing.update(name="Widget renamed")

        trail = await audit_trail(AuditLogRecord, thing)

    assert [entry.event for entry in trail] == ["created", "updated"]
    assert all(entry.auditable_id == thing.id for entry in trail)
    assert other.id != thing.id  # sanity: the other record's entry isn't included


# -- AuditActorMiddleware / AuditLogServiceProvider (HTTP) -----------------------------


async def _make_app(tmp_path: Path) -> Application:
    (tmp_path / ".env").write_text(
        "APP_SECRET_KEY=test-only-secret-not-for-production\nDATABASE_URL=sqlite+aiosqlite:///:memory:\n"
    )
    app = Application(Config.load(tmp_path))
    # Registered *first*, deliberately -- add_middleware() prepends, so
    # the most recently registered middleware wraps outermost. Every
    # later middleware-adding provider (Database, Auth, ApiAuth) then
    # ends up wrapping *around* AuditActorMiddleware, pushing it inward
    # regardless of how many more get added afterward -- exactly what it
    # needs: it reads request.session/current_api_user() (which needs a
    # database session already open) and current_user() (which needs
    # SessionMiddleware to have already parsed the cookie). See
    # AuditLogServiceProvider's own docstring.
    app.register(AuditLogServiceProvider)
    app.register(DatabaseServiceProvider)
    app.register(AuthServiceProvider(app, user_model=AuditUser))
    app.register(ApiAuthServiceProvider(app, user_model=AuditUser))

    database = app.container.make(Database)
    async with database.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)

    AuditedThing.observe(AuditObserver(AuditLogRecord))

    @app.post("/things")
    async def create_thing(request):
        thing = await AuditedThing.create(name="Widget")
        return JSONResponse({"id": thing.id}, status_code=201)

    @app.get("/whoami")
    async def whoami(request):
        actor = current_actor()
        return JSONResponse({"actor": list(actor) if actor else None})

    return app


async def test_actor_is_set_from_session_auth(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    database = app.container.make(Database)

    async with database.session():
        user = await AuditUser.create(email="ada@example.com")
        login_id = user.id

    async def _do_login(request):
        user = await AuditUser.find(login_id)
        login(request, user)
        return JSONResponse({"ok": True})

    # Registered before entering client(app) below -- app.asgi is built
    # (and cached) on first access, when the transport is constructed.
    app.post("/login")(_do_login)

    async with client(app) as http:
        await http.get("/whoami")  # primes the CSRF cookie -- see docs/csrf.md
        await http.post("/login")
        response = await http.post("/things")
        assert response.status_code == 201

    async with database.session():
        entries = await AuditLogRecord.all()

    assert entries[-1].actor_type == "AuditUser"
    assert entries[-1].actor_id == login_id


async def test_actor_is_set_from_api_token_when_no_session(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    database = app.container.make(Database)

    async with database.session():
        user = await AuditUser.create(email="bob@example.com")
        manager = app.container.make(TokenManager)
        token = manager.issue(user)
        user_id = user.id

    async with client(app) as http:
        response = await http.post("/things", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 201

    async with database.session():
        entries = await AuditLogRecord.all()

    assert entries[-1].actor_type == "AuditUser"
    assert entries[-1].actor_id == user_id


async def test_actor_is_anonymous_with_no_authentication(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    database = app.container.make(Database)

    async with client(app) as http:
        await http.get("/whoami")  # primes the CSRF cookie
        response = await http.post("/things")
        assert response.status_code == 201

    async with database.session():
        entries = await AuditLogRecord.all()

    assert entries[-1].actor_type is None
    assert entries[-1].actor_id is None


async def test_actor_does_not_leak_between_requests(tmp_path: Path) -> None:
    # Regression guard: AuditActorMiddleware must reset the contextvar for
    # every request, not just set it once -- otherwise an authenticated
    # request's actor would keep showing up on later, unrelated
    # (unauthenticated) requests sharing the same asyncio Task.
    app = await _make_app(tmp_path)
    database = app.container.make(Database)

    async with database.session():
        user = await AuditUser.create(email="carol@example.com")
        user_id = user.id

    async def _do_login(request):
        user = await AuditUser.find(user_id)
        login(request, user)
        return JSONResponse({"ok": True})

    app.post("/login")(_do_login)

    async with client(app) as http:
        await http.get("/whoami")  # primes the CSRF cookie
        await http.post("/login")
        authenticated = await http.get("/whoami")
        assert authenticated.json()["actor"] == ["AuditUser", user_id]

    # A fresh client -- no session cookie at all -- must not see the
    # previous client's actor leaking through the shared middleware state.
    async with client(app) as fresh_http:
        anonymous = await fresh_http.get("/whoami")
        assert anonymous.json()["actor"] is None

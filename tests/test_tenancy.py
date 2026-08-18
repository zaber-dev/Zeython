"""Tests for zeython.tenancy -- row-level multi-tenancy.

Uses a real database (in-memory SQLite) for the Model-scoping tests, the
same pattern test_db_model.py uses, since the whole point is verifying
real cross-tenant query isolation, not just that a contextvar gets set.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest_asyncio
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.db import Model
from zeython.db.session import Database
from zeython.tenancy import TenancyServiceProvider, TenantMiddleware, as_tenant, current_tenant_id
from zeython.testing import client


class TenantScopedNote(Model):
    __tablename__ = "tenant_scoped_notes"

    tenant_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    body: Mapped[str] = mapped_column(String(255))


class UnscopedNote(Model):
    """No tenant_id column at all -- the control case."""

    __tablename__ = "unscoped_notes"

    body: Mapped[str] = mapped_column(String(255))


@pytest_asyncio.fixture
async def database() -> AsyncIterator[Database]:
    db = Database("sqlite+aiosqlite:///:memory:")
    async with db.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)
    yield db
    await db.dispose()


@asynccontextmanager
async def session_scope(database: Database):
    async with database.session():
        yield


# -- current_tenant_id / as_tenant -----------------------------------------------------------


def test_current_tenant_id_is_none_outside_any_context() -> None:
    assert current_tenant_id() is None


def test_as_tenant_sets_and_resets_the_contextvar() -> None:
    assert current_tenant_id() is None
    with as_tenant("acme"):
        assert current_tenant_id() == "acme"
    assert current_tenant_id() is None


def test_as_tenant_nests() -> None:
    with as_tenant("outer"):
        with as_tenant("inner"):
            assert current_tenant_id() == "inner"
        assert current_tenant_id() == "outer"


# -- Model scoping -------------------------------------------------------------------------


async def test_a_model_without_tenant_id_is_unaffected(database: Database) -> None:
    async with session_scope(database):
        await UnscopedNote.create(body="note one")
        with as_tenant("acme"):
            notes = await UnscopedNote.all()
        assert len(notes) == 1


async def test_all_returns_only_the_current_tenants_rows(database: Database) -> None:
    async with session_scope(database):
        with as_tenant("acme"):
            await TenantScopedNote.create(body="acme note")
        with as_tenant("globex"):
            await TenantScopedNote.create(body="globex note")

        with as_tenant("acme"):
            acme_notes = await TenantScopedNote.all()
        with as_tenant("globex"):
            globex_notes = await TenantScopedNote.all()

    assert [n.body for n in acme_notes] == ["acme note"]
    assert [n.body for n in globex_notes] == ["globex note"]


async def test_all_returns_everything_when_no_tenant_is_set(database: Database) -> None:
    async with session_scope(database):
        with as_tenant("acme"):
            await TenantScopedNote.create(body="acme note")
        with as_tenant("globex"):
            await TenantScopedNote.create(body="globex note")

        all_notes = await TenantScopedNote.all()

    assert {n.body for n in all_notes} == {"acme note", "globex note"}


async def test_find_cannot_read_another_tenants_row_by_id(database: Database) -> None:
    async with session_scope(database):
        with as_tenant("acme"):
            acme_note = await TenantScopedNote.create(body="acme secret")

        with as_tenant("globex"):
            leaked = await TenantScopedNote.find(acme_note.id)

    assert leaked is None


async def test_find_by_is_scoped(database: Database) -> None:
    async with session_scope(database):
        with as_tenant("acme"):
            await TenantScopedNote.create(body="shared body")
        with as_tenant("globex"):
            await TenantScopedNote.create(body="shared body")

        with as_tenant("acme"):
            results = await TenantScopedNote.find_by(body="shared body")

    assert len(results) == 1


async def test_paginate_total_reflects_only_the_current_tenant(database: Database) -> None:
    async with session_scope(database):
        with as_tenant("acme"):
            for i in range(3):
                await TenantScopedNote.create(body=f"note {i}")
        with as_tenant("globex"):
            await TenantScopedNote.create(body="other tenant's note")

        with as_tenant("acme"):
            page = await TenantScopedNote.paginate(page=1, per_page=20)

    assert page.total == 3


async def test_save_auto_assigns_tenant_id_on_create(database: Database) -> None:
    async with session_scope(database):
        with as_tenant("acme"):
            note = await TenantScopedNote.create(body="auto-assigned")
        assert note.tenant_id == "acme"


async def test_save_does_not_override_an_explicitly_set_tenant_id(database: Database) -> None:
    async with session_scope(database):
        with as_tenant("acme"):
            note = await TenantScopedNote.create(body="explicit", tenant_id="globex")
        assert note.tenant_id == "globex"


async def test_save_leaves_tenant_id_unset_outside_any_tenant_context(database: Database) -> None:
    async with session_scope(database):
        note = await TenantScopedNote.create(body="no tenant context")
    assert note.tenant_id is None


async def test_update_does_not_reassign_tenant_id(database: Database) -> None:
    async with session_scope(database):
        with as_tenant("acme"):
            note = await TenantScopedNote.create(body="original")
        with as_tenant("globex"):
            await note.update(body="edited while scoped to a different tenant")
    assert note.tenant_id == "acme"


# -- TenantMiddleware / TenancyServiceProvider ----------------------------------------------


async def test_middleware_resolves_a_sync_resolver(tmp_path) -> None:
    app = Application(Config.load(tmp_path))
    app.add_middleware(TenantMiddleware, resolver=lambda request: request.query_params.get("tenant"))

    @app.get("/")
    async def index(request):
        return JSONResponse({"tenant": current_tenant_id()})

    async with client(app) as http:
        response = await http.get("/?tenant=acme")

    assert response.json()["tenant"] == "acme"


async def test_middleware_resolves_an_async_resolver(tmp_path) -> None:
    async def resolve(request):
        return request.headers.get("x-tenant-id")

    app = Application(Config.load(tmp_path))
    app.add_middleware(TenantMiddleware, resolver=resolve)

    @app.get("/")
    async def index(request):
        return JSONResponse({"tenant": current_tenant_id()})

    async with client(app) as http:
        response = await http.get("/", headers={"X-Tenant-ID": "globex"})

    assert response.json()["tenant"] == "globex"


async def test_middleware_leaves_tenant_none_when_the_resolver_finds_nothing(tmp_path) -> None:
    app = Application(Config.load(tmp_path))
    app.add_middleware(TenantMiddleware, resolver=lambda request: None)

    @app.get("/")
    async def index(request):
        return JSONResponse({"tenant": current_tenant_id()})

    async with client(app) as http:
        response = await http.get("/")

    assert response.json()["tenant"] is None


async def test_tenancy_service_provider_wires_the_middleware(tmp_path) -> None:
    app = Application(Config.load(tmp_path))
    app.register(TenancyServiceProvider(app, resolver=lambda request: "acme"))

    @app.get("/")
    async def index(request):
        return JSONResponse({"tenant": current_tenant_id()})

    async with client(app) as http:
        response = await http.get("/")

    assert response.json()["tenant"] == "acme"


async def test_tenant_is_isolated_per_request_not_leaked_across_requests(tmp_path) -> None:
    app = Application(Config.load(tmp_path))
    app.add_middleware(TenantMiddleware, resolver=lambda request: request.query_params.get("tenant"))

    @app.get("/")
    async def index(request):
        return JSONResponse({"tenant": current_tenant_id()})

    async with client(app) as http:
        first = await http.get("/?tenant=acme")
        second = await http.get("/")

    assert first.json()["tenant"] == "acme"
    assert second.json()["tenant"] is None

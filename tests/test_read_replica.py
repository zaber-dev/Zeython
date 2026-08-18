"""Tests for Database(read_url=...)/read_replica() -- routing reads to a
second engine while writes go through the primary (see docs/database.md).
"""

import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from zeython.application import Application
from zeython.config import Config
from zeython.db import Model
from zeython.db.session import Database, current_session
from zeython.providers import DatabaseServiceProvider


class ReplicaWidget(Model):
    __tablename__ = "replica_widgets"

    name: Mapped[str] = mapped_column(String(100))


@pytest_asyncio.fixture
async def database() -> AsyncIterator[Database]:
    db = Database("sqlite+aiosqlite:///:memory:")
    async with db.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)
    yield db
    await db.dispose()


async def test_without_read_url_read_replica_falls_back_to_the_primary(database: Database) -> None:
    assert database.read_engine is None
    assert database.read_session_factory is None

    async with database.session():
        await ReplicaWidget.create(name="via-primary")

    async with database.read_replica():
        widgets = await ReplicaWidget.all()

    assert [w.name for w in widgets] == ["via-primary"]


async def test_read_replica_yields_the_current_session(database: Database) -> None:
    async with database.read_replica() as session:
        assert session is current_session()


async def test_with_a_real_second_engine_reads_and_writes_are_genuinely_separate(tmp_path: Path) -> None:
    # Two distinct SQLite files stand in for a primary and a replica --
    # unlike a real Postgres/MySQL replica, nothing replicates data
    # between them, so this proves read_replica() really opens a session
    # against the *other* engine, not just a differently-named session
    # against the same one.
    primary_path = tmp_path / "primary.db"
    replica_path = tmp_path / "replica.db"

    db = Database(f"sqlite+aiosqlite:///{primary_path}", read_url=f"sqlite+aiosqlite:///{replica_path}")
    assert db.read_engine is not None
    async with db.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)
    async with db.read_engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)

    async with db.session():
        await ReplicaWidget.create(name="only-on-primary")

    async with db.read_replica():
        # Nothing replicated it -- these are genuinely different files.
        assert await ReplicaWidget.all() == []

    async with db.read_replica() as session:
        session.add(ReplicaWidget(name="only-on-replica"))
        await session.flush()

    async with db.session():
        names = {w.name for w in await ReplicaWidget.all()}
    assert names == {"only-on-primary"}  # the replica-side insert never reached the primary file

    await db.dispose()


async def test_read_replica_does_not_commit(tmp_path: Path) -> None:
    # No commit() in read_replica() -- a write attempted there (which a
    # real replica would reject at the database level anyway) isn't
    # persisted even within the replica session's own connection once
    # it closes, since nothing flushed it and there's no commit to make
    # it durable.
    db = Database("sqlite+aiosqlite:///:memory:")
    async with db.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)

    async with db.read_replica() as session:
        session.add(ReplicaWidget(name="never-committed"))
        # No explicit flush/commit -- read_replica() doesn't commit on exit.

    async with db.session():
        assert await ReplicaWidget.all() == []

    await db.dispose()


async def test_dispose_also_disposes_the_read_engine() -> None:
    from unittest.mock import AsyncMock, patch

    from sqlalchemy.ext.asyncio import AsyncEngine

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db = Database(
            f"sqlite+aiosqlite:///{tmp_path / 'primary.db'}",
            read_url=f"sqlite+aiosqlite:///{tmp_path / 'replica.db'}",
        )
        assert db.read_engine is not None

        with patch.object(AsyncEngine, "dispose", new_callable=AsyncMock) as mock_dispose:
            await db.dispose()

        assert mock_dispose.await_count == 2  # both the primary and the read engine


# -- DatabaseServiceProvider wiring ---------------------------------------------------


async def test_provider_binds_a_read_replica_when_database_read_url_is_set(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "APP_SECRET_KEY=test\n"
        "DATABASE_URL=sqlite+aiosqlite:///:memory:\n"
        "DATABASE_READ_URL=sqlite+aiosqlite:///:memory:\n"
    )
    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)

    database = app.container.make(Database)

    assert database.read_engine is not None
    assert database.read_url == "sqlite+aiosqlite:///:memory:"


async def test_provider_binds_no_read_replica_by_default(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("APP_SECRET_KEY=test\nDATABASE_URL=sqlite+aiosqlite:///:memory:\n")
    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)

    database = app.container.make(Database)

    assert database.read_engine is None

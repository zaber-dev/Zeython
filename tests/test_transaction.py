"""Tests for zeython.db.transaction() -- a SAVEPOINT-scoped nested
transaction within the current session, for isolating a chunk of work's
rollback from the rest of a request without ending it (see
docs/database.md).
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from zeython.db import Model, transaction
from zeython.db.session import Database, current_session


class Widget(Model):
    __tablename__ = "txn_widgets"

    name: Mapped[str] = mapped_column(String(100))


@pytest_asyncio.fixture
async def database() -> AsyncIterator[Database]:
    db = Database("sqlite+aiosqlite:///:memory:")
    async with db.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)
    yield db
    await db.dispose()


async def test_transaction_requires_an_active_session() -> None:
    with pytest.raises(RuntimeError, match="No active database session"):
        async with transaction():
            pass


async def test_a_failure_inside_transaction_rolls_back_only_its_own_writes(database: Database) -> None:
    async with database.session():
        await Widget.create(name="before")

        with pytest.raises(ValueError, match="boom"):
            async with transaction():
                await Widget.create(name="should-be-rolled-back")
                raise ValueError("boom")

        # The failure was caught by pytest.raises -- the request/session
        # keeps going, and writes made after it aren't affected either.
        await Widget.create(name="after")

    async with database.session():
        names = {widget.name for widget in await Widget.all()}

    assert names == {"before", "after"}


async def test_transaction_commits_its_writes_when_the_block_succeeds(database: Database) -> None:
    async with database.session(), transaction():
        await Widget.create(name="committed-via-transaction")

    async with database.session():
        names = {widget.name for widget in await Widget.all()}

    assert names == {"committed-via-transaction"}


async def test_transaction_yields_the_current_session(database: Database) -> None:
    async with database.session(), transaction() as session:
        assert session is current_session()


async def test_nested_transactions_can_be_stacked(database: Database) -> None:
    async with database.session(), transaction():
        await Widget.create(name="outer")
        with pytest.raises(ValueError, match="inner failure"):
            async with transaction():
                await Widget.create(name="inner-rolled-back")
                raise ValueError("inner failure")

    async with database.session():
        names = {widget.name for widget in await Widget.all()}

    assert names == {"outer"}


async def test_an_uncaught_failure_inside_transaction_also_rolls_back_the_whole_session(
    database: Database,
) -> None:
    # transaction() doesn't change what happens if you *don't* catch the
    # error -- letting it propagate still rolls back the entire session,
    # same as without transaction() at all (see docs/database.md).
    with pytest.raises(ValueError, match="boom"):
        async with database.session():
            await Widget.create(name="before-uncaught-failure")
            async with transaction():
                await Widget.create(name="inside-uncaught-failure")
                raise ValueError("boom")

    async with database.session():
        assert await Widget.all() == []

import os

# Real process env vars win over `.env` (see zeython.config.Config), so this
# routes every test at a fresh in-memory database instead of the file your
# dev server uses -- otherwise `pytest` would collide with whatever rows
# `zeython serve` already wrote (duplicate emails, leftover soft-deletes,
# a NOT NULL column your dev data doesn't have yet).
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest_asyncio  # noqa: E402

from main import app  # noqa: E402
from zeython.db.session import Database  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def _reset_database():
    """Give every test a clean schema, no leftover rows from the last one."""
    database = app.container.make(Database)
    await database.drop_all()
    await database.create_all()
    yield

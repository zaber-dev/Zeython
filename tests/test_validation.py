from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from zeython.db import Model
from zeython.db.session import Database
from zeython.exceptions import ValidationException
from zeython.validation import email, max_length, required


class Account(Model):
    __tablename__ = "accounts"
    __rules__ = {
        "name": [required()],
        "email": [required(), email()],
        "bio": [max_length(10)],
    }

    name: Mapped[str] = mapped_column(String(255), nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=True)
    bio: Mapped[str] = mapped_column(String(255), nullable=True)


@pytest_asyncio.fixture
async def database() -> AsyncIterator[Database]:
    db = Database("sqlite+aiosqlite:///:memory:")
    async with db.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)
    yield db
    await db.dispose()


async def test_create_succeeds_when_rules_pass(database: Database) -> None:
    async with database.session():
        account = await Account.create(name="Ada", email="ada@example.com")
        assert account.id is not None


async def test_create_raises_validation_exception_on_missing_required_field(database: Database) -> None:
    async with database.session():
        try:
            await Account.create(email="ada@example.com")
            raise AssertionError("expected ValidationException")
        except ValidationException as exc:
            assert "name" in exc.errors


async def test_create_raises_on_invalid_email(database: Database) -> None:
    async with database.session():
        try:
            await Account.create(name="Ada", email="not-an-email")
            raise AssertionError("expected ValidationException")
        except ValidationException as exc:
            assert "email" in exc.errors


async def test_update_reruns_validation(database: Database) -> None:
    async with database.session():
        account = await Account.create(name="Ada", email="ada@example.com")

        try:
            await account.update(bio="this bio is way too long")
            raise AssertionError("expected ValidationException")
        except ValidationException as exc:
            assert "bio" in exc.errors


def test_validate_returns_errors_without_raising() -> None:
    account = Account(email="not-an-email")
    errors = account.validate()

    assert "name" in errors
    assert "email" in errors


def test_valid_instance_has_no_errors() -> None:
    account = Account(name="Ada", email="ada@example.com")
    assert account.validate() == {}

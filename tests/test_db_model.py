from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from zeython.db import Model
from zeython.db.session import Database


class Article(Model):
    __tablename__ = "articles"

    title: Mapped[str] = mapped_column(String(255))


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


async def test_create_and_find(database: Database) -> None:
    async with session_scope(database):
        created = await Article.create(title="Hello World")
        assert created.id is not None

    async with session_scope(database):
        found = await Article.find(created.id)
        assert found is not None
        assert found.title == "Hello World"


async def test_soft_delete_excludes_from_default_queries(database: Database) -> None:
    async with session_scope(database):
        article = await Article.create(title="Temporary")
        article_id = article.id

    async with session_scope(database):
        article = await Article.find(article_id)
        await article.delete(soft=True)

    async with session_scope(database):
        assert await Article.find(article_id) is None
        assert await Article.find(article_id, include_deleted=True) is not None


async def test_find_by_filters_on_fields(database: Database) -> None:
    async with session_scope(database):
        await Article.create(title="Match")
        await Article.create(title="Other")

    async with session_scope(database):
        results = await Article.find_by(title="Match")
        assert len(results) == 1
        assert results[0].title == "Match"


async def test_to_dict_serializes_columns(database: Database) -> None:
    async with session_scope(database):
        article = await Article.create(title="Serialized")
        data = article.to_dict()

    assert data["title"] == "Serialized"
    assert "id" in data
    assert "created_at" in data


async def test_model_methods_require_an_active_session() -> None:
    with pytest.raises(RuntimeError):
        await Article.find(1)

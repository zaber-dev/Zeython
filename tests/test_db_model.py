from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from zeython.db import Model
from zeython.db.session import Database
from zeython.validation import required


class Article(Model):
    __tablename__ = "articles"

    title: Mapped[str] = mapped_column(String(255))


class Widget(Model):
    """Records which lifecycle hooks fired, and in what order."""

    __tablename__ = "widgets"

    name: Mapped[str] = mapped_column(String(255))

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.events: list[str] = []

    async def saving(self) -> None:
        self.events.append("saving")

    async def saved(self) -> None:
        self.events.append("saved")

    async def creating(self) -> None:
        self.events.append("creating")
        self.name = self.name.strip()

    async def created(self) -> None:
        self.events.append("created")

    async def updating(self) -> None:
        self.events.append("updating")

    async def updated(self) -> None:
        self.events.append("updated")

    async def deleting(self) -> None:
        self.events.append("deleting")

    async def deleted(self) -> None:
        self.events.append("deleted")


class SlugPost(Model):
    """Derives `slug` from `title` in `creating()`, before `__rules__` validates it."""

    __tablename__ = "slug_posts"
    __rules__ = {"slug": [required()]}

    title: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), default="")

    async def creating(self) -> None:
        if not self.slug:
            self.slug = self.title.lower().replace(" ", "-")


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


# -- Lifecycle hooks ------------------------------------------------------------------


async def test_creating_and_created_fire_only_on_the_first_save(database: Database) -> None:
    async with session_scope(database):
        widget = Widget(name="  Widget A  ")
        assert widget.events == []

        await widget.save()

        assert widget.events == ["saving", "creating", "created", "saved"]
        assert widget.name == "Widget A"  # mutated by creating() before flush


async def test_updating_and_updated_fire_on_a_subsequent_save(database: Database) -> None:
    async with session_scope(database):
        widget = await Widget.create(name="Original")
        widget.events.clear()

        await widget.update(name="Changed")

        assert widget.events == ["saving", "updating", "updated", "saved"]


async def test_deleting_and_deleted_fire_around_delete(database: Database) -> None:
    async with session_scope(database):
        widget = await Widget.create(name="ToDelete")
        widget.events.clear()

        await widget.delete()

        assert widget.events == ["deleting", "deleted"]


async def test_creating_hook_runs_before_validation(database: Database) -> None:
    # SlugPost.creating() derives `slug` from `title`; __rules__ requires
    # `slug`. If hooks ran after validate_or_raise() instead of before,
    # this would raise ValidationException on an empty slug.
    async with session_scope(database):
        post = await SlugPost.create(title="Hello World")
        assert post.slug == "hello-world"


# -- paginate() -------------------------------------------------------------------


async def test_paginate_returns_the_requested_page_and_metadata(database: Database) -> None:
    async with session_scope(database):
        for i in range(25):
            await Article.create(title=f"Article {i}")

    async with session_scope(database):
        page = await Article.paginate(page=1, per_page=10)
        assert len(page.items) == 10
        assert page.page == 1
        assert page.per_page == 10
        assert page.total == 25
        assert page.total_pages == 3
        assert page.has_next is True
        assert page.has_prev is False


async def test_paginate_last_page_has_the_remainder_and_no_next(database: Database) -> None:
    async with session_scope(database):
        for i in range(25):
            await Article.create(title=f"Article {i}")

    async with session_scope(database):
        page = await Article.paginate(page=3, per_page=10)
        assert len(page.items) == 5
        assert page.has_next is False
        assert page.has_prev is True


async def test_paginate_excludes_soft_deleted_rows_from_items_and_total(database: Database) -> None:
    async with session_scope(database):
        first = await Article.create(title="Keep")
        second = await Article.create(title="Delete me")
        await second.delete()

    async with session_scope(database):
        page = await Article.paginate(page=1, per_page=10)
        assert page.total == 1
        assert [item.id for item in page.items] == [first.id]


async def test_paginate_rejects_a_non_positive_page_or_per_page(database: Database) -> None:
    async with session_scope(database):
        with pytest.raises(ValueError):
            await Article.paginate(page=0)
        with pytest.raises(ValueError):
            await Article.paginate(per_page=0)

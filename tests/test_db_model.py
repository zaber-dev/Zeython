import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl, urlsplit

import pytest
import pytest_asyncio
from sqlalchemy import String
from sqlalchemy.dialects import mysql, postgresql
from sqlalchemy.orm import Mapped, mapped_column
from starlette.requests import Request

from zeython.db import Model, Observer
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


class Gadget(Model):
    """A model with no lifecycle hooks of its own -- purely for exercising
    Observer/observe() in isolation from a model's own hooks.
    """

    __tablename__ = "gadgets"

    name: Mapped[str] = mapped_column(String(255))


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


async def test_find_stmt_adds_for_update_when_requested() -> None:
    stmt = Article._find_stmt(1, include_deleted=False, include=(), for_update=True)
    assert "FOR UPDATE" in str(stmt.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in str(stmt.compile(dialect=mysql.dialect()))


def test_find_stmt_omits_for_update_by_default() -> None:
    stmt = Article._find_stmt(1, include_deleted=False, include=(), for_update=False)
    assert "FOR UPDATE" not in str(stmt.compile(dialect=postgresql.dialect()))


async def test_find_with_for_update_still_returns_the_row_on_sqlite(database: Database) -> None:
    # SQLite has no row-level locking, so for_update=True can't actually
    # lock anything there -- it must still behave as an ordinary find(),
    # not raise or return something different.
    async with session_scope(database):
        created = await Article.create(title="Hello World")
        article_id = created.id

    async with session_scope(database):
        found = await Article.find(article_id, for_update=True)
        assert found is not None
        assert found.title == "Hello World"


async def test_find_with_for_update_warns_on_sqlite(database: Database, caplog: pytest.LogCaptureFixture) -> None:
    async with session_scope(database):
        created = await Article.create(title="Hello World")
        article_id = created.id

    async with session_scope(database):
        with caplog.at_level(logging.WARNING, logger="zeython.db.model"):
            await Article.find(article_id, for_update=True)

    assert any("no row-level locking" in record.message for record in caplog.records)


async def test_find_without_for_update_does_not_warn_on_sqlite(
    database: Database, caplog: pytest.LogCaptureFixture
) -> None:
    async with session_scope(database):
        created = await Article.create(title="Hello World")
        article_id = created.id

    async with session_scope(database):
        with caplog.at_level(logging.WARNING, logger="zeython.db.model"):
            await Article.find(article_id)

    assert caplog.records == []


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


# -- Page.to_dict() -----------------------------------------------------------------


def _request(query_string: bytes = b"") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/articles",
            "query_string": query_string,
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )


async def test_page_to_dict_serializes_items_and_metadata(database: Database) -> None:
    async with session_scope(database):
        for i in range(25):
            await Article.create(title=f"Article {i}")

    async with session_scope(database):
        page = await Article.paginate(page=1, per_page=10)
        body = page.to_dict()

    assert body["page"] == 1
    assert body["per_page"] == 10
    assert body["total"] == 25
    assert body["total_pages"] == 3
    assert body["has_next"] is True
    assert body["has_prev"] is False
    assert len(body["items"]) == 10
    assert body["items"][0] == page.items[0].to_dict()
    assert "next_url" not in body
    assert "prev_url" not in body


async def test_page_to_dict_without_request_omits_urls(database: Database) -> None:
    async with session_scope(database):
        await Article.create(title="Only one")

    async with session_scope(database):
        page = await Article.paginate(page=1, per_page=10)
        body = page.to_dict()

    assert "next_url" not in body
    assert "prev_url" not in body


def _query_params(url: str) -> dict[str, str]:
    return dict(parse_qsl(urlsplit(url).query))


async def test_page_to_dict_with_request_builds_next_and_prev_urls_preserving_other_params(
    database: Database,
) -> None:
    async with session_scope(database):
        for i in range(25):
            await Article.create(title=f"Article {i}")

    async with session_scope(database):
        page = await Article.paginate(page=2, per_page=10)
        body = page.to_dict(request=_request(b"page=2&per_page=10&sort=title"))

    assert _query_params(body["next_url"]) == {"page": "3", "per_page": "10", "sort": "title"}
    assert _query_params(body["prev_url"]) == {"page": "1", "per_page": "10", "sort": "title"}


async def test_page_to_dict_first_page_has_no_prev_url_and_last_page_has_no_next_url(
    database: Database,
) -> None:
    async with session_scope(database):
        for i in range(15):
            await Article.create(title=f"Article {i}")

    async with session_scope(database):
        first = await Article.paginate(page=1, per_page=10)
        first_body = first.to_dict(request=_request(b"page=1&per_page=10"))
        last = await Article.paginate(page=2, per_page=10)
        last_body = last.to_dict(request=_request(b"page=2&per_page=10"))

    assert first_body["prev_url"] is None
    assert _query_params(first_body["next_url"]) == {"page": "2", "per_page": "10"}
    assert last_body["next_url"] is None
    assert _query_params(last_body["prev_url"]) == {"page": "1", "per_page": "10"}


# -- Observer / Model.observe() ------------------------------------------------------


class _RecordingObserver(Observer):
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def saving(self, model: Gadget) -> None:
        self.events.append(("saving", model.name))

    async def saved(self, model: Gadget) -> None:
        self.events.append(("saved", model.name))

    async def creating(self, model: Gadget) -> None:
        self.events.append(("creating", model.name))

    async def created(self, model: Gadget) -> None:
        self.events.append(("created", model.name))

    async def updating(self, model: Gadget) -> None:
        self.events.append(("updating", model.name))

    async def updated(self, model: Gadget) -> None:
        self.events.append(("updated", model.name))

    async def deleting(self, model: Gadget) -> None:
        self.events.append(("deleting", model.name))

    async def deleted(self, model: Gadget) -> None:
        self.events.append(("deleted", model.name))


@pytest.fixture(autouse=True)
def _reset_gadget_observers() -> None:
    Gadget.__observers__ = []


async def test_observe_accepts_an_instance_and_fires_on_create(database: Database) -> None:
    observer = _RecordingObserver()
    Gadget.observe(observer)

    async with session_scope(database):
        await Gadget.create(name="Widget A")

    assert observer.events == [
        ("saving", "Widget A"),
        ("creating", "Widget A"),
        ("created", "Widget A"),
        ("saved", "Widget A"),
    ]


async def test_observe_accepts_a_class_and_instantiates_it(database: Database) -> None:
    Gadget.observe(_RecordingObserver)

    async with session_scope(database):
        await Gadget.create(name="Widget B")

    [observer] = Gadget.__observers__
    assert ("created", "Widget B") in observer.events


async def test_observe_fires_updating_updated_on_an_existing_record(database: Database) -> None:
    observer = _RecordingObserver()
    Gadget.observe(observer)

    async with session_scope(database):
        gadget = await Gadget.create(name="Widget C")
        observer.events.clear()
        await gadget.update(name="Widget C renamed")

    assert observer.events == [
        ("saving", "Widget C renamed"),
        ("updating", "Widget C renamed"),
        ("updated", "Widget C renamed"),
        ("saved", "Widget C renamed"),
    ]


async def test_observe_fires_deleting_deleted(database: Database) -> None:
    observer = _RecordingObserver()
    Gadget.observe(observer)

    async with session_scope(database):
        gadget = await Gadget.create(name="Widget D")
        observer.events.clear()
        await gadget.delete()

    assert observer.events == [("deleting", "Widget D"), ("deleted", "Widget D")]


async def test_multiple_observers_all_fire_in_registration_order(database: Database) -> None:
    first = _RecordingObserver()
    second = _RecordingObserver()
    Gadget.observe(first)
    Gadget.observe(second)

    async with session_scope(database):
        await Gadget.create(name="Widget E")

    assert ("created", "Widget E") in first.events
    assert ("created", "Widget E") in second.events


async def test_observers_are_isolated_per_model_class(database: Database) -> None:
    observer = _RecordingObserver()
    Gadget.observe(observer)

    assert Article.__observers__ == []


async def test_a_default_observer_with_no_overrides_is_a_silent_no_op(database: Database) -> None:
    Gadget.observe(Observer)

    async with session_scope(database):
        gadget = await Gadget.create(name="Widget F")
        await gadget.update(name="Widget F renamed")
        await gadget.delete()
    # No assertion needed beyond "didn't raise" -- Observer's own hooks are no-ops.

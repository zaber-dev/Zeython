"""Tests for zeython.n_plus_one -- an opt-in, APP_DEBUG-only warning when
a request fires the same SQL statement shape suspiciously many times.
"""

import logging
from pathlib import Path

import pytest
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.db import Model
from zeython.db.session import Database
from zeython.n_plus_one import N1QueryDetectionServiceProvider
from zeython.providers import DatabaseServiceProvider
from zeython.testing import client


class N1Author(Model):
    __tablename__ = "n1_test_authors"
    name: Mapped[str] = mapped_column(String(100))


class N1Book(Model):
    __tablename__ = "n1_test_books"
    title: Mapped[str] = mapped_column(String(100))
    author_id: Mapped[int] = mapped_column(ForeignKey("n1_test_authors.id"))
    author: Mapped[N1Author] = relationship()


async def _make_app(tmp_path: Path, *, debug: bool = True, threshold: int | None = None) -> Application:
    lines = ["APP_SECRET_KEY=test\nDATABASE_URL=sqlite+aiosqlite:///:memory:\n"]
    lines.append(f"APP_DEBUG={'true' if debug else 'false'}\n")
    if threshold is not None:
        lines.append(f"N1_QUERY_THRESHOLD={threshold}\n")
    (tmp_path / ".env").write_text("".join(lines))

    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)
    app.register(N1QueryDetectionServiceProvider(app))

    database = app.container.make(Database)
    async with database.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)

    async with database.session():
        author = await N1Author.create(name="Ada")
        for i in range(15):
            await N1Book.create(title=f"Book {i}", author_id=author.id)

    return app


async def test_warns_when_the_same_statement_runs_more_than_the_threshold(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    app = await _make_app(tmp_path, threshold=10)

    @app.get("/books")
    async def books(request):
        results = []
        for book in await N1Book.all():
            # The N+1 pattern: fetching the relationship one row at a time
            # instead of N1Book.all(include=("author",)).
            fetched = await N1Book.find(book.id, include=("author",))
            results.append(fetched.author.name)
        return JSONResponse(results)

    with caplog.at_level(logging.WARNING, logger="zeython.n_plus_one"):
        async with client(app) as http:
            response = await http.get("/books")

    assert response.status_code == 200
    warnings = [r for r in caplog.records if r.name == "zeython.n_plus_one"]
    # Two separate statement shapes both ran once per row (fetching each
    # book, then each book's author) -- both are legitimately N+1, so both
    # warn.
    assert len(warnings) == 2
    assert all("/books" in w.message and "15 times" in w.message for w in warnings)


async def test_no_warning_when_under_the_threshold(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    app = await _make_app(tmp_path, threshold=100)

    @app.get("/books")
    async def books(request):
        for book in await N1Book.all():
            await N1Book.find(book.id, include=("author",))
        return JSONResponse({"ok": True})

    with caplog.at_level(logging.WARNING, logger="zeython.n_plus_one"):
        async with client(app) as http:
            await http.get("/books")

    assert not [r for r in caplog.records if r.name == "zeython.n_plus_one"]


async def test_no_warning_for_a_repeated_insert_loop(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # Real E2E finding: a bulk-create loop repeats the same INSERT
    # statement shape just as much as a genuine N+1 SELECT loop does, but
    # it isn't the pattern this exists to catch, and "eager-load it
    # instead" would be nonsensical advice for an INSERT -- only SELECTs
    # count.
    app = await _make_app(tmp_path, threshold=3)

    @app.get("/create-many")
    async def create_many(request):
        author = (await N1Author.all())[0]
        for i in range(20):
            await N1Book.create(title=f"New {i}", author_id=author.id)
        return JSONResponse({"ok": True})

    with caplog.at_level(logging.WARNING, logger="zeython.n_plus_one"):
        async with client(app) as http:
            await http.get("/create-many")

    assert not [r for r in caplog.records if r.name == "zeython.n_plus_one"]


async def test_no_warning_when_app_debug_is_false(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    app = await _make_app(tmp_path, debug=False, threshold=10)

    @app.get("/books")
    async def books(request):
        for book in await N1Book.all():
            await N1Book.find(book.id, include=("author",))
        return JSONResponse({"ok": True})

    with caplog.at_level(logging.WARNING, logger="zeython.n_plus_one"):
        async with client(app) as http:
            await http.get("/books")

    assert not [r for r in caplog.records if r.name == "zeython.n_plus_one"]


async def test_counting_is_scoped_per_request_not_cumulative(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Five queries per request, threshold ten -- no single request trips
    # it even after several requests, proving the counter resets each time
    # rather than accumulating forever across the process lifetime.
    app = await _make_app(tmp_path, threshold=10)

    @app.get("/some-books")
    async def some_books(request):
        for book in (await N1Book.all())[:5]:
            await N1Book.find(book.id, include=("author",))
        return JSONResponse({"ok": True})

    with caplog.at_level(logging.WARNING, logger="zeython.n_plus_one"):
        async with client(app) as http:
            for _ in range(4):
                await http.get("/some-books")

    assert not [r for r in caplog.records if r.name == "zeython.n_plus_one"]

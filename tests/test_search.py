"""Tests for zeython.search + Model.search().

The SQLite path runs against a real in-memory database: the FTS5 index is
created the same way a migration would (via create_fts5_index()), proving
the triggers really do keep it in sync with ordinary ORM writes, not just
that the SQL text looks right. The Postgres path has no live server to
run against in this environment (see test_database_pooling.py for the
same constraint elsewhere in this suite), so it's covered at the
SQL-generation level instead, via Model._search_sql().
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy import String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from zeython.db import Model
from zeython.db.session import Database
from zeython.search import (
    create_fts5_index,
    create_tsvector_index,
    drop_fts5_index,
    drop_tsvector_index,
)


class SearchPost(Model):
    __tablename__ = "search_posts"
    __searchable__ = ("title", "body")

    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)


class UnsearchablePost(Model):
    __tablename__ = "unsearchable_posts"

    title: Mapped[str] = mapped_column(String(255))


class _SyncOpAdapter:
    """Adapts a plain SQLAlchemy sync `Connection` to the `op.execute(sql)`
    interface `create_fts5_index`/`create_tsvector_index` expect from
    Alembic's `op` -- lets tests apply the exact same DDL a real migration
    would, without actually running Alembic.
    """

    def __init__(self, connection: object) -> None:
        self._connection = connection

    def execute(self, sql: str) -> None:
        self._connection.execute(text(sql))  # type: ignore[attr-defined]


@pytest_asyncio.fixture
async def database() -> AsyncIterator[Database]:
    db = Database("sqlite+aiosqlite:///:memory:")
    async with db.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)
        await connection.run_sync(lambda sync_conn: create_fts5_index(_SyncOpAdapter(sync_conn), "search_posts", ["title", "body"]))
    yield db
    await db.dispose()


@asynccontextmanager
async def session_scope(database: Database):
    async with database.session() as session:
        yield session


# -- Model.search() against a real SQLite FTS5 index -----------------------------


async def test_search_finds_matching_rows_ranked_by_relevance(database: Database) -> None:
    async with session_scope(database):
        await SearchPost.create(title="Async ORM basics", body="An introduction to async database access.")
        await SearchPost.create(title="Cooking pasta", body="A recipe with garlic and olive oil.")
        await SearchPost.create(
            title="Async everywhere", body="Async database sessions, async queues, async everything in this framework."
        )

    async with session_scope(database):
        results = await SearchPost.search("async")

    assert [r.title for r in results] == ["Async everywhere", "Async ORM basics"]


async def test_search_matches_across_multiple_searchable_columns(database: Database) -> None:
    async with session_scope(database):
        await SearchPost.create(title="Weekly update", body="This week we shipped full-text search.")

    async with session_scope(database):
        by_title = await SearchPost.search("weekly")
        by_body = await SearchPost.search("shipped")

    assert [r.title for r in by_title] == ["Weekly update"]
    assert [r.title for r in by_body] == ["Weekly update"]


async def test_search_returns_nothing_for_a_non_matching_query(database: Database) -> None:
    async with session_scope(database):
        await SearchPost.create(title="Hello", body="World")

    async with session_scope(database):
        assert await SearchPost.search("nonexistent") == []


async def test_search_index_stays_in_sync_on_update(database: Database) -> None:
    async with session_scope(database):
        post = await SearchPost.create(title="Draft title", body="Draft body.")
        post_id = post.id

    async with session_scope(database):
        post = await SearchPost.find(post_id)
        await post.update(title="Published title", body="Published body about zeython.")

    async with session_scope(database):
        assert [r.title for r in await SearchPost.search("draft")] == []
        assert [r.title for r in await SearchPost.search("zeython")] == ["Published title"]


async def test_search_index_stays_in_sync_on_delete(database: Database) -> None:
    async with session_scope(database):
        post = await SearchPost.create(title="Removable", body="This will be hard-deleted.")
        post_id = post.id

    async with session_scope(database):
        post = await SearchPost.find(post_id)
        await post.delete(soft=False)

    async with session_scope(database):
        assert await SearchPost.search("removable") == []


async def test_search_excludes_soft_deleted_rows_by_default(database: Database) -> None:
    async with session_scope(database):
        post = await SearchPost.create(title="Soft deleted post", body="Should not appear in results.")
        post_id = post.id

    async with session_scope(database):
        post = await SearchPost.find(post_id)
        await post.delete(soft=True)

    async with session_scope(database):
        assert await SearchPost.search("soft") == []
        assert [r.title for r in await SearchPost.search("soft", include_deleted=True)] == ["Soft deleted post"]


async def test_search_respects_limit(database: Database) -> None:
    async with session_scope(database):
        for i in range(5):
            await SearchPost.create(title=f"Matching post {i}", body="matching")

    async with session_scope(database):
        results = await SearchPost.search("matching", limit=2)

    assert len(results) == 2


async def test_search_raises_when_searchable_is_not_configured(database: Database) -> None:
    async with session_scope(database):
        with pytest.raises(RuntimeError, match="__searchable__"):
            await UnsearchablePost.search("anything")


async def test_search_with_a_blank_query_returns_nothing_without_touching_the_database(database: Database) -> None:
    async with session_scope(database):
        await SearchPost.create(title="Hello", body="World")

    async with session_scope(database):
        assert await SearchPost.search("") == []
        assert await SearchPost.search("   ") == []


@pytest.mark.parametrize(
    "query",
    ['"', 'foo"bar', "a OR", "(unbalanced", "col:foo", 'a b"c', "AND", "*"],
)
async def test_search_treats_fts5_special_characters_as_literal_text_not_syntax(
    database: Database, query: str
) -> None:
    # Every one of these strings is ordinary user input a search box has
    # to survive (a stray quote, a colon, unbalanced parens, the word
    # "AND") -- unquoted, FTS5 parses them as its own query mini-language
    # and raises a syntax error instead of treating them as text to
    # search for. Not raising is the whole assertion; matching nothing is
    # the correct, boring result for a query that matches no document.
    async with session_scope(database):
        await SearchPost.create(title="Hello", body="World")

    async with session_scope(database):
        assert await SearchPost.search(query) == []


async def test_search_with_a_leading_hyphen_does_not_raise_and_still_tokenizes(database: Database) -> None:
    # Unquoted, a leading "-" is FTS5's NOT operator and "-hello" alone
    # raises a syntax error (no left-hand term to negate). Quoted, it's
    # just punctuation the tokenizer strips like any other, so "-hello"
    # is searched -- and found -- as the word "hello".
    async with session_scope(database):
        await SearchPost.create(title="Hello", body="World")

    async with session_scope(database):
        assert [r.title for r in await SearchPost.search("-hello")] == ["Hello"]


async def test_search_multi_word_query_still_matches_regardless_of_term_order(database: Database) -> None:
    async with session_scope(database):
        await SearchPost.create(title="Async ORM basics", body="An introduction to async database access.")

    async with session_scope(database):
        # Quoting each term individually must not turn "async database"
        # into a single adjacent phrase -- it should still AND together
        # as two independent terms the way an unquoted multi-word MATCH
        # already does.
        assert [r.title for r in await SearchPost.search("database async")] == ["Async ORM basics"]


def test_drop_fts5_index_removes_table_and_triggers() -> None:
    executed: list[str] = []

    class _RecordingOp:
        def execute(self, sql: str) -> None:
            executed.append(sql)

    drop_fts5_index(_RecordingOp(), "search_posts")

    assert any("DROP TABLE IF EXISTS search_posts_fts" in stmt for stmt in executed)
    assert any("DROP TRIGGER IF EXISTS search_posts_fts_ai" in stmt for stmt in executed)
    assert any("DROP TRIGGER IF EXISTS search_posts_fts_ad" in stmt for stmt in executed)
    assert any("DROP TRIGGER IF EXISTS search_posts_fts_au" in stmt for stmt in executed)


def test_create_fts5_index_issues_expected_ddl() -> None:
    executed: list[str] = []

    class _RecordingOp:
        def execute(self, sql: str) -> None:
            executed.append(sql)

    create_fts5_index(_RecordingOp(), "posts", ["title", "body"])

    assert "CREATE VIRTUAL TABLE posts_fts USING fts5(title, body, content='posts', content_rowid='id')" in executed
    assert "INSERT INTO posts_fts(rowid, title, body) SELECT id, title, body FROM posts" in executed
    assert any(stmt.startswith("CREATE TRIGGER posts_fts_ai AFTER INSERT") for stmt in executed)
    assert any(stmt.startswith("CREATE TRIGGER posts_fts_ad AFTER DELETE") for stmt in executed)
    assert any(stmt.startswith("CREATE TRIGGER posts_fts_au AFTER UPDATE") for stmt in executed)


def test_create_tsvector_index_issues_expected_ddl() -> None:
    executed: list[str] = []

    class _RecordingOp:
        def execute(self, sql: str) -> None:
            executed.append(sql)

    create_tsvector_index(_RecordingOp(), "posts", ["title", "body"])

    assert any(
        stmt == "ALTER TABLE posts ADD COLUMN search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', coalesce(title, '') || ' ' || coalesce(body, ''))) STORED"
        for stmt in executed
    )
    assert "CREATE INDEX ix_posts_search_vector ON posts USING GIN (search_vector)" in executed


def test_create_tsvector_index_honors_language_and_column_name() -> None:
    executed: list[str] = []

    class _RecordingOp:
        def execute(self, sql: str) -> None:
            executed.append(sql)

    create_tsvector_index(_RecordingOp(), "posts", ["title"], language="french", column_name="tsv")

    assert any("to_tsvector('french', coalesce(title, ''))" in stmt for stmt in executed)
    assert "CREATE INDEX ix_posts_tsv ON posts USING GIN (tsv)" in executed


def test_drop_tsvector_index_removes_index_and_column() -> None:
    executed: list[str] = []

    class _RecordingOp:
        def execute(self, sql: str) -> None:
            executed.append(sql)

    drop_tsvector_index(_RecordingOp(), "posts")

    assert "DROP INDEX IF EXISTS ix_posts_search_vector" in executed
    assert "ALTER TABLE posts DROP COLUMN IF EXISTS search_vector" in executed


# -- Model._search_sql() -- dialect dispatch, including postgres (no live server) --


def test_search_sql_raises_when_searchable_is_not_configured() -> None:
    with pytest.raises(RuntimeError, match="__searchable__"):
        UnsearchablePost._search_sql("sqlite", include_deleted=False)


def test_search_sql_raises_for_an_unsupported_dialect() -> None:
    with pytest.raises(RuntimeError, match="doesn't support the 'mysql'"):
        SearchPost._search_sql("mysql", include_deleted=False)


def test_search_sql_sqlite_excludes_soft_deleted_by_default() -> None:
    sql = SearchPost._search_sql("sqlite", include_deleted=False)
    assert "search_posts_fts MATCH :query" in sql
    assert "search_posts.is_deleted = 0" in sql
    assert "ORDER BY rank LIMIT :limit" in sql


def test_search_sql_sqlite_include_deleted_omits_the_filter() -> None:
    sql = SearchPost._search_sql("sqlite", include_deleted=True)
    assert "is_deleted" not in sql


def test_search_sql_postgresql_uses_tsvector_and_ts_rank() -> None:
    sql = SearchPost._search_sql("postgresql", include_deleted=False)
    assert "search_vector @@ plainto_tsquery(:language, :query)" in sql
    assert "is_deleted = false" in sql
    assert "ORDER BY ts_rank(search_vector, plainto_tsquery(:language, :query)) DESC LIMIT :limit" in sql


def test_search_sql_postgresql_include_deleted_omits_the_filter() -> None:
    sql = SearchPost._search_sql("postgresql", include_deleted=True)
    assert "is_deleted" not in sql


# -- Model._quote_fts5_terms() -----------------------------------------------------


def test_quote_fts5_terms_quotes_each_whitespace_separated_term() -> None:
    assert SearchPost._quote_fts5_terms("async database") == '"async" "database"'


def test_quote_fts5_terms_doubles_embedded_quotes() -> None:
    assert SearchPost._quote_fts5_terms('foo"bar') == '"foo""bar"'

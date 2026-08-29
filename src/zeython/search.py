"""Full-text search index creation for :meth:`zeython.db.model.Model.search`
-- run once from your own Alembic migration, not at request time.

Dispatches to whichever native full-text engine your database already has
-- SQLite's FTS5 virtual tables, Postgres's ``tsvector``/GIN indexes -- so
there's no new dependency and no separate search service to run and keep
in sync. That's also the trade-off: cross-database consistency and
relevance tuning are whatever each engine's own full-text implementation
gives you, not a shared abstraction over both. For requirements a
database's own full-text search can't meet (typo tolerance, faceting,
huge multi-tenant indexes), point at a dedicated search service instead
and skip this module entirely -- ``Model.search()`` is deliberately just a
thin dispatch over raw SQL, not a search engine of its own.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

__all__ = [
    "create_fts5_index",
    "create_tsvector_index",
    "drop_fts5_index",
    "drop_tsvector_index",
]


def create_fts5_index(op: Any, table: str, columns: Iterable[str]) -> None:
    """Create a SQLite FTS5 external-content index over ``table``'s
    ``columns``, backfilled from every existing row, and kept in sync by
    three triggers (``AFTER INSERT``/``UPDATE``/``DELETE``) -- SQLite's own
    documented recipe for external-content FTS5 tables. Unlike an
    ORM-level hook, these triggers fire for *any* write to ``table``
    (raw SQL, another process), not just ones that go through
    :class:`~zeython.db.model.Model`.

    Call this once from a migration's ``upgrade()``::

        from zeython.search import create_fts5_index

        def upgrade() -> None:
            create_fts5_index(op, "posts", ["title", "body"])

    Requires ``id`` to be the table's integer primary key (true of every
    :class:`~zeython.db.model.Model` subclass) -- FTS5's ``content_rowid``
    is set to it.
    """
    cols = list(columns)
    col_list = ", ".join(cols)
    new_values = ", ".join(f"new.{c}" for c in cols)
    old_values = ", ".join(f"old.{c}" for c in cols)

    op.execute(f"CREATE VIRTUAL TABLE {table}_fts USING fts5({col_list}, content='{table}', content_rowid='id')")
    op.execute(f"INSERT INTO {table}_fts(rowid, {col_list}) SELECT id, {col_list} FROM {table}")
    op.execute(
        f"CREATE TRIGGER {table}_fts_ai AFTER INSERT ON {table} BEGIN "
        f"INSERT INTO {table}_fts(rowid, {col_list}) VALUES (new.id, {new_values}); "
        f"END"
    )
    op.execute(
        f"CREATE TRIGGER {table}_fts_ad AFTER DELETE ON {table} BEGIN "
        f"INSERT INTO {table}_fts({table}_fts, rowid, {col_list}) VALUES('delete', old.id, {old_values}); "
        f"END"
    )
    op.execute(
        f"CREATE TRIGGER {table}_fts_au AFTER UPDATE ON {table} BEGIN "
        f"INSERT INTO {table}_fts({table}_fts, rowid, {col_list}) VALUES('delete', old.id, {old_values}); "
        f"INSERT INTO {table}_fts(rowid, {col_list}) VALUES (new.id, {new_values}); "
        f"END"
    )


def drop_fts5_index(op: Any, table: str) -> None:
    """Undo :func:`create_fts5_index` -- call from a migration's ``downgrade()``."""
    op.execute(f"DROP TRIGGER IF EXISTS {table}_fts_au")
    op.execute(f"DROP TRIGGER IF EXISTS {table}_fts_ad")
    op.execute(f"DROP TRIGGER IF EXISTS {table}_fts_ai")
    op.execute(f"DROP TABLE IF EXISTS {table}_fts")


def create_tsvector_index(
    op: Any, table: str, columns: Iterable[str], *, language: str = "english", column_name: str = "search_vector"
) -> None:
    """Add a generated ``tsvector`` column over ``table``'s ``columns`` plus
    a GIN index on it -- Postgres keeps a ``GENERATED ALWAYS ... STORED``
    column in sync automatically on every write, no triggers needed.

    Call this once from a migration's ``upgrade()``::

        from zeython.search import create_tsvector_index

        def upgrade() -> None:
            create_tsvector_index(op, "posts", ["title", "body"])

    ``language`` must match whatever ``Model.__search_language__`` the
    corresponding model uses (default ``"english"`` on both sides).
    """
    concat_expr = " || ' ' || ".join(f"coalesce({c}, '')" for c in columns)
    op.execute(
        f"ALTER TABLE {table} ADD COLUMN {column_name} tsvector "
        f"GENERATED ALWAYS AS (to_tsvector('{language}', {concat_expr})) STORED"
    )
    op.execute(f"CREATE INDEX ix_{table}_{column_name} ON {table} USING GIN ({column_name})")


def drop_tsvector_index(op: Any, table: str, *, column_name: str = "search_vector") -> None:
    """Undo :func:`create_tsvector_index` -- call from a migration's ``downgrade()``."""
    op.execute(f"DROP INDEX IF EXISTS ix_{table}_{column_name}")
    op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column_name}")

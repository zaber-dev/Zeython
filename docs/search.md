# Full-Text Search

`Model.search()` runs a real full-text query — not a `LIKE '%...%'` scan —
using whichever full-text engine your database already ships: SQLite's
FTS5, or Postgres's `tsvector`/GIN indexes. No new dependency, no separate
search service to run and keep in sync.

## Setup

Declare which columns are searchable on the model:

```python
# app/Models/post.py
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column
from zeython import Model

class Post(Model):
    __tablename__ = "posts"
    __searchable__ = ("title", "body")

    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
```

Then create the matching index **once**, from a migration — `Model.search()`
queries an index, it doesn't create one for you:

```bash
zeython db revision -m "add posts search index"
```

```python
# migrations/versions/xxxx_add_posts_search_index.py
from alembic import op
from zeython.search import create_fts5_index  # SQLite

def upgrade() -> None:
    create_fts5_index(op, "posts", ["title", "body"])

def downgrade() -> None:
    from zeython.search import drop_fts5_index
    drop_fts5_index(op, "posts")
```

```bash
zeython db migrate
```

That's it — search away:

```python
results = await Post.search("async orm")
```

## SQLite: `create_fts5_index()`

Creates an [external-content FTS5](https://sqlite.org/fts5.html#external_content_tables)
virtual table (`posts_fts`) plus three triggers that keep it in sync with
`posts` on every `INSERT`/`UPDATE`/`DELETE` — including writes that don't
go through `Model` at all (a raw `INSERT`, a script, another process),
since the triggers live in the database itself, not in Python. Backfills
every existing row when the migration runs.

`Model.search()` queries it with SQLite's `MATCH` operator, ordered by
FTS5's own built-in `rank` column (best matches first) — no extra
configuration.

## Postgres: `create_tsvector_index()`

Adds a `search_vector tsvector` column,
[`GENERATED ALWAYS ... STORED`](https://www.postgresql.org/docs/current/ddl-generated-columns.html)
from the given columns, plus a GIN index on it. Postgres keeps a generated
column in sync automatically on every write — no triggers needed here.

```python
from zeython.search import create_tsvector_index

def upgrade() -> None:
    create_tsvector_index(op, "posts", ["title", "body"])
```

`Model.search()` queries it with `plainto_tsquery()`/`@@`, ordered by
`ts_rank()`. `language` defaults to `"english"` on both the index and the
query side — pass a different one to both `create_tsvector_index(...,
language="french")` and set `Post.__search_language__ = "french"` if you
need it, and keep them in sync.

## Excluding soft-deleted rows

`search()` excludes soft-deleted rows by default, the same as `all()`/
`find_by()` — pass `include_deleted=True` to include them:

```python
await Post.search("draft", include_deleted=True)
```

## Limiting results

```python
await Post.search("async orm", limit=10)  # default 20
```

## What this isn't

`Model.search()` is a thin, honest dispatch over each database's own
full-text SQL — not a search engine. It doesn't give you: relevance
tuning beyond what `rank`/`ts_rank` compute, typo tolerance/fuzzy
matching, faceted search, or a shared ranking model across SQLite and
Postgres (each engine ranks its own way). For requirements like those, or
for an index too large for your primary database to carry alongside
everything else, point a dedicated search service (Elasticsearch,
Meilisearch, Typesense) at the same data instead — `Model.search()`
covers the common case of "let me search this table" without a second
service to run, not every case.

MySQL isn't supported yet (`Model.search()` raises a clear `RuntimeError`
naming the dialect) — its own full-text indexes work differently enough
from SQLite/Postgres's that adding a third dispatch branch is deliberately
left for when someone actually needs it, not implemented speculatively.

## API reference

See [`zeython.search`](reference/database.md) for the full API, and
[`Model.search()`](reference/database.md) alongside the rest of `Model`.

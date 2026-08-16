# Database & Migrations

## Defining a model

```python
# app/Models/post.py
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from zeython import Model

class Post(Model):
    __tablename__ = "posts"

    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
```

Every `Model` subclass already has `id`, `created_at`, `updated_at`, `is_deleted`,
and `deleted_at` columns — you only declare the columns specific to your table.

Register new models in `app/Models/__init__.py` (done automatically by
`zeython make model`) so Alembic's autogenerate can see them.

## Active Record API

```python
post = await Post.create(title="Hello", body="World")
post = await Post.find(1)
posts = await Post.all()
posts = await Post.find_by(title="Hello")
await post.update(title="Updated")
await post.delete()                 # soft delete by default
await post.delete(soft=False)       # hard delete
await post.restore()
post.to_dict()                      # JSON-serializable dict
```

All of these require an active database session — present automatically inside
a request, or via `async with database.session():` elsewhere (see
[Architecture](architecture.md#request-scoped-database-sessions)).

`find`/`all`/`find_by`/`first_where` also accept `include=("relationship_name",)`
to eager-load relationships — required reading before you define your first
`relationship()`, since touching one without eager-loading crashes async
code differently than you'd expect from sync SQLAlchemy. See
[Relationships](relationships.md).

## Pagination

`all()` loads every matching row — fine for a small table, not for a
listing endpoint whose table grows without bound. `paginate()` is the
same query, sliced:

```python
page = await Post.paginate(page=1, per_page=20)

page.items         # list[Post] -- this page's rows
page.page          # 1
page.per_page      # 20
page.total         # every matching row, not just this page
page.total_pages   # ceil(total / per_page)
page.has_next       # page < total_pages
page.has_prev       # page > 1
```

`total` costs a second query (a `COUNT(*)` over the same filters) to
compute — that's the price of knowing `total_pages`/`has_next` up front,
not a bug. If you don't need that, `all()` with a hand-rolled `limit`
isn't available on `Model` directly, but nothing stops you from writing
a raw `select()` for that one case.

`paginate()` accepts the same `include_deleted`/`include=(...)` keywords
as `find`/`all`/`find_by`. `zeython new` wires it into the generated
`GET /users` (`?page=`/`?per_page=`, defaulting to `1`/`20`) — see
`app/Controllers/user_controller.py`.

## Migrations

```bash
zeython db revision -m "add posts table"
zeython db migrate
```

`zeython new` scaffolds a working Alembic setup (`alembic.ini`, `migrations/env.py`)
pointed at your `DATABASE_URL` and your `app.Models` metadata, so
`--autogenerate` works out of the box against SQLite, PostgreSQL (`pip install
zeython[postgres]`), or MySQL (`pip install zeython[mysql]`).

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

## Migrations

```bash
zeython db revision -m "add posts table"
zeython db migrate
```

`zeython new` scaffolds a working Alembic setup (`alembic.ini`, `migrations/env.py`)
pointed at your `DATABASE_URL` and your `app.Models` metadata, so
`--autogenerate` works out of the box against SQLite, PostgreSQL (`pip install
zeython[postgres]`), or MySQL (`pip install zeython[mysql]`).

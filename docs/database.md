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

A model that declares a `tenant_id` column gets every one of these
methods scoped to the current tenant automatically — see
[Multi-Tenancy](multi-tenancy.md).

## Transactions

Every request already runs inside one implicit transaction: `DatabaseSessionMiddleware`
opens a session at the start of the request and commits it at the end, or
rolls it back if an unhandled exception reaches the end of the request --
even one your own exception handler already turned into a response.
Starlette re-raises the original exception to outer ASGI middleware after
handling it, specifically so this kind of outer cleanup still runs. Nothing
extra is needed for "undo everything this request did if it fails":

```python
async def transfer(self, request):
    await from_account.update(balance=from_account.balance - amount)
    await to_account.update(balance=to_account.balance + amount)
    if something_goes_wrong:
        raise ConflictException("Transfer failed")
        # both updates above are rolled back -- the whole request's
        # writes are, whenever an exception ends it
```

`transaction()` is for a narrower case: isolating *part* of a request so a
failure there doesn't undo everything else, without ending the request:

```python
from zeython import transaction

async def checkout(self, request):
    order = await Order.create(user_id=user.id, status="pending")

    try:
        async with transaction():
            await reserve_inventory(order)   # several writes
            await charge_payment(order)      # might raise
    except PaymentFailedException:
        await order.update(status="payment_failed")
        return JSONResponse({"error": "Payment failed"}, status_code=402)

    await order.update(status="confirmed")
    return JSONResponse(order.to_dict())
```

If `reserve_inventory`/`charge_payment` raise, only their writes roll back
(a `SAVEPOINT` under the hood) -- `order`'s initial creation isn't touched,
and the handler keeps running to record the failure and respond normally,
rather than the whole request dying with a 500. `transaction()` blocks
nest: an inner one rolling back doesn't affect an outer one still in
progress.

Requires an active session, same as the rest of the Active Record API --
raises the same `RuntimeError` as calling `Model.create()` outside one.

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

`page.to_dict()` serializes a whole page in one call — items (via each
item's own `to_dict()`, for `Model` instances) plus the metadata above:

```python
return JSONResponse(page.to_dict())
# {"items": [...], "page": 1, "per_page": 20, "total": 57,
#  "total_pages": 3, "has_next": true, "has_prev": false}
```

Pass the current request to also get `next_url`/`prev_url` — the same
URL with only the `page` query param changed (every other query param
carries over), `None` when there is no next/previous page:

```python
return JSONResponse(page.to_dict(request=request))
# adds "next_url": "http://.../users?page=2", "prev_url": null
```

## Connection pooling

`DatabaseServiceProvider` forwards `DATABASE_POOL_SIZE`/`DATABASE_MAX_OVERFLOW`
straight through to SQLAlchemy's connection pool, unset by default:

```env
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
```

- `DATABASE_POOL_SIZE` — steady-state connections the pool keeps open.
- `DATABASE_MAX_OVERFLOW` — extra connections allowed beyond that under
  load, closed again once things quiet down.

**Meaningful for PostgreSQL/MySQL, and for a file-based SQLite URL** (what
`zeython new` scaffolds, `sqlite+aiosqlite:///./database.db`) — all three
default to SQLAlchemy's `AsyncAdaptedQueuePool`, which both settings
configure directly. The one exception is `sqlite+aiosqlite:///:memory:`
(what the framework's own test suite uses): in-memory SQLite defaults to
`StaticPool`, which doesn't accept either kwarg at all — passing them
raises `TypeError` at engine-creation time. That's why both are unset by
default rather than shipping a number that would break an in-memory setup;
set them once you have an actual concurrency figure to size against (a
reasonable start: your app server's worker count, or a little above it).

## Read replicas

A second `DATABASE_READ_URL` routes read-heavy work to a replica instead
of the primary — a report, a dashboard, an analytics query, anything
that can tolerate a little replication lag and that you'd rather not have
competing with write traffic for the primary's connections:

```env
DATABASE_URL=postgresql+asyncpg://user:pass@primary/app
DATABASE_READ_URL=postgresql+asyncpg://user:pass@replica/app
```

```python
async def monthly_report(self, request):
    async with database.read_replica():
        orders = await Order.all()
    return JSONResponse(build_report(orders))
```

`read_replica()` opens a session against the replica exactly the way
`database.session()` opens one against the primary — same
`current_session()` underneath, so `Model.find/all/find_by/...` all work
inside the block unchanged. Not registered as the request's default
session — reach for it explicitly, only for the read path you actually
want off the primary; everything else in the request still uses the
regular session.

**Read-only in practice, not by any check this framework adds.** A real
replica is normally configured read-only at the database level itself
(Postgres's `default_transaction_read_only`, a MySQL replica user with no
write grants) — a write attempted inside `read_replica()` fails with a
real database error there, the same as it would against any other client
connected to that replica. There's also no `commit()` on exit, since a
replica session exists for reads.

**Optional** — no `DATABASE_READ_URL` set, `read_replica()` transparently
falls back to opening a session against the primary. Code written against
it works the same whether or not a replica is actually configured, so
it's safe to write `async with database.read_replica():` around a report
query in an app that doesn't have one yet.

Passed through via `**engine_kwargs` on `Database.__init__` — the same
mechanism accepts any other keyword `create_async_engine()` understands,
if you construct `Database` yourself instead of going through
`DatabaseServiceProvider`.

## Migrations

```bash
zeython db revision -m "add posts table"
zeython db migrate
```

`zeython new` scaffolds a working Alembic setup (`alembic.ini`, `migrations/env.py`)
pointed at your `DATABASE_URL` and your `app.Models` metadata, so
`--autogenerate` works out of the box against SQLite, PostgreSQL (`pip install
zeython[postgres]`), or MySQL (`pip install zeython[mysql]`). `migrations/env.py`
also enables Alembic's `render_as_batch` mode, needed for SQLite specifically:
SQLite can add a new column but can't otherwise `ALTER` a constraint in place,
so a migration adding a `ForeignKey` (or any other constraint change) to an
existing table would fail without it. Harmless no-op on Postgres/MySQL.

Adding a `NOT NULL` column to a table that already has rows hits a real SQL
constraint on every database, not a Zeython limitation: the existing rows
need *some* value for that column. Give the generated migration a default —
`sa.Column('author_id', sa.Integer(), nullable=False, server_default='1')` —
so the backfill has something to write, or make the column nullable if the
data genuinely doesn't apply to old rows.

# Relationships

Defining a relationship on a `Model` is plain SQLAlchemy — no framework
wrapper needed:

```python
# app/Models/user.py
class User(Model):
    __tablename__ = "users"
    posts: Mapped[list["Post"]] = relationship(back_populates="author")

# app/Models/post.py
class Post(Model):
    __tablename__ = "posts"
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    author: Mapped[User] = relationship(back_populates="posts")
```

Where Zeython actually adds value is *loading* relationships safely.

## Why this needs care in async code

Touching an unloaded relationship in a sync SQLAlchemy app just triggers a
lazy load — a bit slow (N+1 queries), but it works. Touching one in an
**async** session raises `MissingGreenlet`, because a lazy load is a
synchronous DB call and there's no synchronous DB call available inside an
async context. This is the single most common way people get stuck the
first time they use async SQLAlchemy, and it's exactly what `include=`
exists to prevent.

## Eager-loading with `include=`

`find`, `all`, `find_by`, and `first_where` all accept `include=(...)`,
applying `selectinload()` for each relationship name — the query fetches
related rows up front, so touching the relationship afterward (even after
the session that fetched it has closed) is just reading already-loaded
Python attributes, no further DB access:

```python
post = await Post.find(1, include=("author",))
post.author.name          # safe -- already loaded

posts = await Post.all(include=("author",))
for post in posts:
    post.author.name      # safe for every row -- one extra query total, not N+1
```

Without `include=`, the same access raises:

```python
post = await Post.find(1)
post.author.name          # MissingGreenlet
```

## Serializing relationships with `to_dict(include=...)`

`to_dict()` accepts the same `include=` and nests the related object's own
`to_dict()`:

```python
post = await Post.find(1, include=("author",))
post.to_dict(include=("author",))
# {"id": 1, "title": "...", "author": {"id": 1, "name": "Ada", ...}, ...}
```

If you pass `include=` for a relationship that wasn't eager-loaded,
`to_dict()` raises a `RuntimeError` telling you exactly what to fix, rather
than either silently omitting the data or crashing with `MissingGreenlet`
three frames deep in SQLAlchemy:

```python
post = await Post.find(1)           # no include=
post.to_dict(include=("author",))
# RuntimeError: Cannot serialize unloaded relationship 'author' on Post.
# Eager-load it first, e.g. `await Post.find(id, include=('author',))`.
```

Without `include=` at all, `to_dict()` only ever touches columns — it never
attempts a relationship, loaded or not.

## Assigning a relationship keeps it loaded

Setting a relationship attribute directly (rather than just the foreign key
column) keeps it loaded in memory immediately, no query needed — useful
right after creating a row when you already have the related object:

```python
post = await Post.create(title="Hello", body="...", author=current_user)
post.to_dict(include=("author",))   # works immediately, no extra query
```

vs. setting only the FK, which leaves the relationship unloaded:

```python
post = await Post.create(title="Hello", body="...", author_id=current_user.id)
post.to_dict(include=("author",))   # RuntimeError -- author was never loaded
```

## Scope

`include=` loads one level of relationships per name; it doesn't support
nested paths like `"comments.author"`. For anything beyond that — complex
joins, nested eager loading, custom query shapes — drop down to SQLAlchemy
directly with `select()` and `.options()`; `Model` subclasses `Base`, so
raw SQLAlchemy queries work on them exactly as documented upstream.

## Detecting N+1s automatically

`include=` prevents the crash (`MissingGreenlet`), but forgetting it
entirely — hand-rolling a loop that touches a relationship's foreign key
and fetches the related row one at a time instead — doesn't crash, it just
runs one query per row: fine with 3 rows, a real production slowdown with
3,000. `N1QueryDetectionServiceProvider` catches this in development
before it ships:

```python
# main.py
from zeython import Application, N1QueryDetectionServiceProvider

app = Application()
app.register(DatabaseServiceProvider)             # must run first -- binds Database
app.register(N1QueryDetectionServiceProvider(app))
```

Not registered by default, but its `boot()` is a no-op unless `APP_DEBUG`
is true, so it's safe to always register — no per-query overhead and no
query text logged from real production traffic. It hooks SQLAlchemy's
`before_cursor_execute` event and counts statement *shapes* (bound
parameters aside — `SELECT ... WHERE id = ?` run once per row in a loop is
one shape, run many times) per request; more than `N1_QUERY_THRESHOLD`
(default `10`) of the same shape in one request logs a warning naming the
route and the query:

```
WARNING zeython.n_plus_one: Possible N+1 query on /posts: the same statement
ran 47 times in one request. Eager-load the relationship instead
(include=(...), see docs/relationships.md). Query: SELECT posts.author_id, ...
```

For the full picture of what queries a request ran and how long each
took — not just a warning past a threshold — see
[Request & Query Profiling](profiling.md).

The fix is the same one this whole page is about — eager-load with
`include=(...)` instead of touching the relationship inside a loop.

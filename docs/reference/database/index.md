# Database

The async SQLAlchemy-backed `Model` base class, session/transaction management, N+1 query detection, a request/query profiler, and factories & seeders for tests and local data.

## db

### Model

Bases: `Base`

Base class for application models.

Provides an Active-Record style async API (`create`, `find`, `all`, `save`, `delete`) plus soft deletes and audit timestamps out of the box. All methods operate on the session bound to the current request via :data:`zeython.db.session.current_session`.

#### observe

```python
observe(observer: type[Observer] | Observer) -> None
```

Register an observer for this model class -- a class (instantiated with no arguments) or an already-constructed instance. Typically called once, e.g. in a service provider's `boot()`.

Source code in `src/zeython/db/model.py`

```python
@classmethod
def observe(cls, observer: type[Observer] | Observer) -> None:
    """Register an observer for this model class -- a class (instantiated
    with no arguments) or an already-constructed instance. Typically
    called once, e.g. in a service provider's ``boot()``.
    """
    instance = observer() if isinstance(observer, type) else observer
    cls.__observers__.append(instance)
```

#### validate

```python
validate() -> dict[str, list[str]]
```

Run `__rules__` against the current field values. Does not raise.

A thin wrapper over :func:`zeython.validation.validate` applied to this instance's own field values -- use that function directly to run the same rule sets against a plain dict (a request payload, not yet a model instance).

Source code in `src/zeython/db/model.py`

```python
def validate(self) -> dict[str, list[str]]:
    """Run ``__rules__`` against the current field values. Does not raise.

    A thin wrapper over :func:`zeython.validation.validate` applied to
    this instance's own field values -- use that function directly to
    run the same rule sets against a plain dict (a request payload, not
    yet a model instance).
    """
    data = {field: getattr(self, field, None) for field in self.__rules__}
    return validate_data(data, self.__rules__)
```

#### saving

```python
saving() -> None
```

Runs before every save() -- both create and update.

Source code in `src/zeython/db/model.py`

```python
async def saving(self) -> None:
    """Runs before every save() -- both create and update."""
```

#### saved

```python
saved() -> None
```

Runs after every successful save() -- both create and update.

Source code in `src/zeython/db/model.py`

```python
async def saved(self) -> None:
    """Runs after every successful save() -- both create and update."""
```

#### creating

```python
creating() -> None
```

Runs before a new record's first save().

Source code in `src/zeython/db/model.py`

```python
async def creating(self) -> None:
    """Runs before a new record's first save()."""
```

#### created

```python
created() -> None
```

Runs after a new record's first save().

Source code in `src/zeython/db/model.py`

```python
async def created(self) -> None:
    """Runs after a new record's first save()."""
```

#### updating

```python
updating() -> None
```

Runs before saving changes to an existing record.

Source code in `src/zeython/db/model.py`

```python
async def updating(self) -> None:
    """Runs before saving changes to an existing record."""
```

#### updated

```python
updated() -> None
```

Runs after saving changes to an existing record.

Source code in `src/zeython/db/model.py`

```python
async def updated(self) -> None:
    """Runs after saving changes to an existing record."""
```

#### deleting

```python
deleting() -> None
```

Runs before delete() -- soft or hard.

Source code in `src/zeython/db/model.py`

```python
async def deleting(self) -> None:
    """Runs before delete() -- soft or hard."""
```

#### deleted

```python
deleted() -> None
```

Runs after delete() -- soft or hard.

Source code in `src/zeython/db/model.py`

```python
async def deleted(self) -> None:
    """Runs after delete() -- soft or hard."""
```

#### paginate

```python
paginate(
    *,
    page: int = 1,
    per_page: int = 20,
    include_deleted: bool = False,
    include: Iterable[str] = (),
) -> Page[Self]
```

One page of results, plus the total row count for building pager UI.

`total` (and therefore `total_pages`) reflects every matching row, not just this page -- it costs a second query (a `COUNT(*)` over the same filters) to get that number. If you only need the rows themselves, `all()` is cheaper.

Source code in `src/zeython/db/model.py`

```python
@classmethod
async def paginate(
    cls,
    *,
    page: int = 1,
    per_page: int = 20,
    include_deleted: bool = False,
    include: Iterable[str] = (),
) -> Page[Self]:
    """One page of results, plus the total row count for building pager UI.

    ``total`` (and therefore ``total_pages``) reflects every matching
    row, not just this page -- it costs a second query (a ``COUNT(*)``
    over the same filters) to get that number. If you only need the
    rows themselves, ``all()`` is cheaper.
    """
    if page < 1:
        raise ValueError("page must be >= 1")
    if per_page < 1:
        raise ValueError("per_page must be >= 1")

    session = current_session()
    stmt = cls._base_select()
    if not include_deleted:
        stmt = stmt.where(cls.is_deleted.is_(False))

    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    stmt = cls._with_includes(stmt, include)
    stmt = stmt.limit(per_page).offset((page - 1) * per_page)
    result = await session.execute(stmt)
    items = list(result.scalars().all())

    return Page(items=items, page=page, per_page=per_page, total=total)
```

#### to_dict

```python
to_dict(
    *,
    exclude: tuple[str, ...] = (),
    include: tuple[str, ...] = (),
) -> dict[str, Any]
```

Serialize columns, plus any eagerly-loaded relationships named in `include`.

Raises `RuntimeError` (not the framework's problem to swallow) if a name in `include` wasn't eager-loaded on the query that fetched this instance -- see docs/relationships.md for why serializing an unloaded relationship isn't something this silently attempts.

Source code in `src/zeython/db/model.py`

```python
def to_dict(self, *, exclude: tuple[str, ...] = (), include: tuple[str, ...] = ()) -> dict[str, Any]:
    """Serialize columns, plus any eagerly-loaded relationships named in ``include``.

    Raises ``RuntimeError`` (not the framework's problem to swallow) if
    a name in ``include`` wasn't eager-loaded on the query that fetched
    this instance -- see docs/relationships.md for why serializing an
    unloaded relationship isn't something this silently attempts.
    """
    hidden = set(self.__hidden__) | set(exclude)
    mapper = inspect(self.__class__)
    result: dict[str, Any] = {}
    for column in mapper.columns:
        if column.name in hidden:
            continue
        value = getattr(self, column.name)
        if isinstance(value, datetime):
            value = value.isoformat()
        result[column.name] = value

    if include:
        unloaded = inspect(self).unloaded
        for name in include:
            if name in unloaded:
                raise RuntimeError(
                    f"Cannot serialize unloaded relationship '{name}' on {type(self).__name__}. "
                    f"Eager-load it first, e.g. "
                    f"`await {type(self).__name__}.find(id, include=('{name}',))`."
                )
            related = getattr(self, name)
            if isinstance(related, list):
                result[name] = [item.to_dict() if isinstance(item, Model) else item for item in related]
            elif isinstance(related, Model):
                result[name] = related.to_dict()
            else:
                result[name] = related

    return result
```

### Observer

Base class for model observers -- mirrors Laravel's `Model::observe()`.

A model's own lifecycle hooks (`saving`/`saved`/...) live on the model itself, one implementation per class. An observer is a separate object registered against a model class with :meth:`Model.observe`, for cross-cutting concerns that don't belong on the model (search-index sync, cache invalidation, audit logging) and that several independent observers might want to react to. Override any subset of these hooks; the rest are no-ops. Called in the same order as the model's own hooks, immediately after each one.

#### saving

```python
saving(model: Model) -> None
```

Runs before every save() -- both create and update.

Source code in `src/zeython/db/model.py`

```python
async def saving(self, model: Model) -> None:
    """Runs before every save() -- both create and update."""
```

#### saved

```python
saved(model: Model) -> None
```

Runs after every successful save() -- both create and update.

Source code in `src/zeython/db/model.py`

```python
async def saved(self, model: Model) -> None:
    """Runs after every successful save() -- both create and update."""
```

#### creating

```python
creating(model: Model) -> None
```

Runs before a new record's first save().

Source code in `src/zeython/db/model.py`

```python
async def creating(self, model: Model) -> None:
    """Runs before a new record's first save()."""
```

#### created

```python
created(model: Model) -> None
```

Runs after a new record's first save().

Source code in `src/zeython/db/model.py`

```python
async def created(self, model: Model) -> None:
    """Runs after a new record's first save()."""
```

#### updating

```python
updating(model: Model) -> None
```

Runs before saving changes to an existing record.

Source code in `src/zeython/db/model.py`

```python
async def updating(self, model: Model) -> None:
    """Runs before saving changes to an existing record."""
```

#### updated

```python
updated(model: Model) -> None
```

Runs after saving changes to an existing record.

Source code in `src/zeython/db/model.py`

```python
async def updated(self, model: Model) -> None:
    """Runs after saving changes to an existing record."""
```

#### deleting

```python
deleting(model: Model) -> None
```

Runs before delete() -- soft or hard.

Source code in `src/zeython/db/model.py`

```python
async def deleting(self, model: Model) -> None:
    """Runs before delete() -- soft or hard."""
```

#### deleted

```python
deleted(model: Model) -> None
```

Runs after delete() -- soft or hard.

Source code in `src/zeython/db/model.py`

```python
async def deleted(self, model: Model) -> None:
    """Runs after delete() -- soft or hard."""
```

### Page

```python
Page(items: list[T], page: int, per_page: int, total: int)
```

Bases: `Generic[T]`

One page of results from :meth:`Model.paginate`.

#### to_dict

```python
to_dict(
    *, request: Request | None = None
) -> dict[str, Any]
```

Serialize this page: items (via `.to_dict()` for `Model` instances, as-is otherwise) plus pagination metadata.

Pass the current request to also get `next_url`/`prev_url` -- the same URL with only the `page` query param changed (every other query param, e.g. `per_page` or a filter, carries over), `None` when there is no next/previous page.

Source code in `src/zeython/db/model.py`

```python
def to_dict(self, *, request: Request | None = None) -> dict[str, Any]:
    """Serialize this page: items (via ``.to_dict()`` for ``Model``
    instances, as-is otherwise) plus pagination metadata.

    Pass the current request to also get ``next_url``/``prev_url`` --
    the same URL with only the ``page`` query param changed (every
    other query param, e.g. ``per_page`` or a filter, carries over),
    ``None`` when there is no next/previous page.
    """
    items = [item.to_dict() if isinstance(item, Model) else item for item in self.items]
    result: dict[str, Any] = {
        "items": items,
        "page": self.page,
        "per_page": self.per_page,
        "total": self.total,
        "total_pages": self.total_pages,
        "has_next": self.has_next,
        "has_prev": self.has_prev,
    }
    if request is not None:
        result["next_url"] = (
            str(request.url.include_query_params(page=self.page + 1)) if self.has_next else None
        )
        result["prev_url"] = (
            str(request.url.include_query_params(page=self.page - 1)) if self.has_prev else None
        )
    return result
```

### Base

Bases: `DeclarativeBase`

Declarative base shared by every Zeython model.

### Database

```python
Database(
    url: str,
    *,
    read_url: str | None = None,
    echo: bool = False,
    **engine_kwargs: object,
)
```

Owns the async engine and session factory for a Zeython application.

`read_url`, if given, points at a read replica: :meth:`read_replica` opens a session against it instead of the primary. Optional -- with no `read_url`, :meth:`read_replica` just falls back to the primary, so code written against it works unchanged whether or not a replica is configured. See docs/database.md#read-replicas.

Source code in `src/zeython/db/session.py`

```python
def __init__(self, url: str, *, read_url: str | None = None, echo: bool = False, **engine_kwargs: object) -> None:
    self.url = url
    self.engine: AsyncEngine = create_async_engine(url, echo=echo, **engine_kwargs)
    self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    self.read_url = read_url
    self.read_engine: AsyncEngine | None = None
    self.read_session_factory: async_sessionmaker[AsyncSession] | None = None
    if read_url is not None:
        self.read_engine = create_async_engine(read_url, echo=echo, **engine_kwargs)
        self.read_session_factory = async_sessionmaker(self.read_engine, expire_on_commit=False)
```

#### create_all

```python
create_all() -> None
```

Create all tables known to :class:`Base`. Intended for tests/dev; use migrations in production.

Source code in `src/zeython/db/session.py`

```python
async def create_all(self) -> None:
    """Create all tables known to :class:`Base`. Intended for tests/dev; use migrations in production."""
    async with self.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
```

#### session

```python
session() -> AsyncIterator[AsyncSession]
```

Open a session, bind it to the current context, commit on success.

Source code in `src/zeython/db/session.py`

```python
@asynccontextmanager
async def session(self) -> AsyncIterator[AsyncSession]:
    """Open a session, bind it to the current context, commit on success."""
    session = self.session_factory()
    token = _current_session.set(session)
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
        _current_session.reset(token)
```

#### read_replica

```python
read_replica() -> AsyncIterator[AsyncSession]
```

Open a session against the read replica (or the primary, if no `read_url` was configured) -- for a read-heavy path that can tolerate replication lag (a report, a dashboard, an analytics query), not a substitute for :meth:`session` in general.

Read-only in practice, not by any framework-enforced check, and Zeython doesn't duplicate one in Python: whether a write attempted here is actually rejected depends entirely on how the replica is configured at the database level (Postgres's `default_transaction_read_only`, a MySQL replica user with no write grants). Configured that way, it fails with a database error; left writable, the write silently succeeds against the replica and is never flushed back to the primary, since there's no commit here -- a replica session is for reads, so nothing needs to be flushed. Configure the replica read-only at the database level if you want a stray write here to fail loudly instead of vanishing.

Source code in `src/zeython/db/session.py`

```python
@asynccontextmanager
async def read_replica(self) -> AsyncIterator[AsyncSession]:
    """Open a session against the read replica (or the primary, if no
    ``read_url`` was configured) -- for a read-heavy path that can
    tolerate replication lag (a report, a dashboard, an analytics
    query), not a substitute for :meth:`session` in general.

    Read-only in practice, not by any framework-enforced check, and
    Zeython doesn't duplicate one in Python: whether a write attempted
    here is actually rejected depends entirely on how the replica is
    configured at the database level (Postgres's
    ``default_transaction_read_only``, a MySQL replica user with no
    write grants). Configured that way, it fails with a database error;
    left writable, the write silently succeeds against the replica and
    is never flushed back to the primary, since there's no commit here
    -- a replica session is for reads, so nothing needs to be flushed.
    Configure the replica read-only at the database level if you want a
    stray write here to fail loudly instead of vanishing.
    """
    factory = self.read_session_factory or self.session_factory
    session = factory()
    token = _current_session.set(session)
    try:
        yield session
    finally:
        await session.close()
        _current_session.reset(token)
```

### current_session

```python
current_session() -> AsyncSession
```

Return the session bound to the current async context.

Raises if called outside a request handled by `DatabaseSessionMiddleware` or outside an explicit `async with database.session():` block.

Source code in `src/zeython/db/session.py`

```python
def current_session() -> AsyncSession:
    """Return the session bound to the current async context.

    Raises if called outside a request handled by ``DatabaseSessionMiddleware``
    or outside an explicit ``async with database.session():`` block.
    """
    session = _current_session.get()
    if session is None:
        raise RuntimeError(
            "No active database session in this context. Wrap your code with "
            "`async with database.session():`, or make sure DatabaseSessionMiddleware "
            "is registered on the application."
        )
    return session
```

### transaction

```python
transaction() -> AsyncIterator[AsyncSession]
```

A `SAVEPOINT`-scoped nested transaction within the current session -- for a chunk of work that should roll back independently of the rest of the request if it fails, without undoing writes made earlier in the same request or ending it. Requires an active session (see :func:`current_session`)::

```text
async with transaction():
    await from_account.save()
    await to_account.save()
# a failure inside the block rolls back only these two writes --
# anything saved before entering it, or after it exits normally,
# is unaffected.
```

Rolling back an *entire* request already happens for free and needs no extra API: `DatabaseSessionMiddleware` rolls back the whole session whenever the response status ends up `4xx`/`5xx` -- whether that's a genuinely unhandled exception unwinding past it, or one of `zeython`'s own `HTTPException` subclasses your handler raised (`NotFoundException`, `ValidationException`, etc.), which Starlette's inner `ExceptionMiddleware` turns into that response without ever re-raising past this middleware -- see :class:`DatabaseSessionMiddleware`. `transaction()` is for the narrower case where you catch the failure yourself, keep the request going, and still return a success response, but don't want that chunk's partial writes kept.

Source code in `src/zeython/db/session.py`

```python
@asynccontextmanager
async def transaction() -> AsyncIterator[AsyncSession]:
    """A ``SAVEPOINT``-scoped nested transaction within the current session
    -- for a chunk of work that should roll back independently of the rest
    of the request if it fails, without undoing writes made earlier in the
    same request or ending it. Requires an active session (see
    :func:`current_session`)::

        async with transaction():
            await from_account.save()
            await to_account.save()
        # a failure inside the block rolls back only these two writes --
        # anything saved before entering it, or after it exits normally,
        # is unaffected.

    Rolling back an *entire* request already happens for free and needs
    no extra API: ``DatabaseSessionMiddleware`` rolls back the whole
    session whenever the response status ends up ``4xx``/``5xx`` --
    whether that's a genuinely unhandled exception unwinding past it, or
    one of ``zeython``'s own ``HTTPException`` subclasses your handler
    raised (`NotFoundException`, `ValidationException`, etc.), which
    Starlette's inner ``ExceptionMiddleware`` turns into that response
    without ever re-raising past this middleware -- see
    :class:`DatabaseSessionMiddleware`. ``transaction()`` is for the
    narrower case where you catch the failure yourself, keep the request
    going, and still return a success response, but don't want that
    chunk's partial writes kept.
    """
    session = current_session()
    async with session.begin_nested():
        yield session
```

## database

### Factory

```python
Factory()
```

Bases: `ABC`, `Generic[ModelT]`

Base class for a model factory. One subclass per model.

::

```text
class UserFactory(Factory[User]):
    model = User

    def definition(self, sequence: int) -> dict:
        return {
            "name": f"User {sequence}",
            "email": f"user{sequence}@example.com",
            "password_hash": hash_password("password"),
        }

user = await UserFactory().create()
users = await UserFactory().create_many(5)
unsaved = UserFactory().make(name="Override")  # not persisted
```

Source code in `src/zeython/database/factory.py`

```python
def __init__(self) -> None:
    self._sequence = 0
```

#### definition

```python
definition(sequence: int) -> dict[str, Any]
```

Default attributes for one instance.

`sequence` starts at 1 and increments on every `make()`/ `create()` call on this factory instance -- use it to keep unique-constrained columns (an email, a slug) actually unique across a batch, without reaching for a random-data library.

Source code in `src/zeython/database/factory.py`

```python
@abstractmethod
def definition(self, sequence: int) -> dict[str, Any]:
    """Default attributes for one instance.

    ``sequence`` starts at 1 and increments on every ``make()``/
    ``create()`` call on this factory instance -- use it to keep
    unique-constrained columns (an email, a slug) actually unique
    across a batch, without reaching for a random-data library.
    """
```

#### make

```python
make(**overrides: Any) -> ModelT
```

Build an instance in memory. Not persisted -- nothing touches the database.

Source code in `src/zeython/database/factory.py`

```python
def make(self, **overrides: Any) -> ModelT:
    """Build an instance in memory. Not persisted -- nothing touches the database."""
    data = {**self.definition(self._next_sequence()), **overrides}
    return self.model(**data)  # type: ignore[return-value]
```

#### create

```python
create(**overrides: Any) -> ModelT
```

Build an instance and save it, the same way `Model.create()` does.

Requires an active database session (a request, or an explicit `async with database.session():` block) -- same requirement as every other persistence method in the framework.

Source code in `src/zeython/database/factory.py`

```python
async def create(self, **overrides: Any) -> ModelT:
    """Build an instance and save it, the same way ``Model.create()`` does.

    Requires an active database session (a request, or an explicit
    ``async with database.session():`` block) -- same requirement as
    every other persistence method in the framework.
    """
    data = {**self.definition(self._next_sequence()), **overrides}
    return await self.model.create(**data)  # type: ignore[return-value]
```

### Seeder

```python
Seeder(app: Application)
```

Bases: `ABC`

Base class for a database seeder.

::

```text
class UserSeeder(Seeder):
    async def run(self) -> None:
        await UserFactory().create(email="admin@example.com")
        await UserFactory().create_many(9)

class DatabaseSeeder(Seeder):
    async def run(self) -> None:
        await self.call(UserSeeder, PostSeeder)
```

Runs inside a single database session opened by the CLI (`zeython db seed`) -- `Model.create()`/factory `create()` calls inside `run()` work exactly as they do in a request handler, no session parameter to thread through.

Source code in `src/zeython/database/seeder.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
```

#### run

```python
run() -> None
```

Insert seed data -- via factories, or `Model.create()` directly.

Source code in `src/zeython/database/seeder.py`

```python
@abstractmethod
async def run(self) -> None:
    """Insert seed data -- via factories, or ``Model.create()`` directly."""
```

#### call

```python
call(*seeder_classes: type[Seeder]) -> None
```

Run other seeders from within this one, in order.

Source code in `src/zeython/database/seeder.py`

```python
async def call(self, *seeder_classes: type[Seeder]) -> None:
    """Run other seeders from within this one, in order."""
    for seeder_cls in seeder_classes:
        await seeder_cls(self.app).run()
```

### discover_seeders

```python
discover_seeders(
    project_root: Path,
) -> dict[str, type[Seeder]]
```

Every :class:`Seeder` subclass in `database/seeders/*.py`, keyed by class name.

Source code in `src/zeython/database/seeder.py`

```python
def discover_seeders(project_root: Path) -> dict[str, type[Seeder]]:
    """Every :class:`Seeder` subclass in ``database/seeders/*.py``, keyed by class name."""
    seeders_dir = project_root / "database" / "seeders"
    seeders: dict[str, type[Seeder]] = {}
    if not seeders_dir.is_dir():
        return seeders

    root_str = str(project_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    sync_project_modules(project_root)
    importlib.invalidate_caches()

    for path in sorted(seeders_dir.glob("*.py")):
        if path.stem == "__init__":
            continue

        module = importlib.import_module(f"database.seeders.{path.stem}")
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if obj is Seeder or not issubclass(obj, Seeder):
                continue
            if obj.__module__ != module.__name__:
                continue  # e.g. `from zeython.database.seeder import Seeder` itself
            seeders[name] = obj

    return seeders
```

## n_plus_one

N+1 query detection: an opt-in, dev-only warning when a single request fires the exact same SQL statement shape suspiciously many times -- the classic symptom of fetching each row's related object one at a time in a loop instead of eager-loading with `include=(...)` (see docs/relationships.md).

Hooks SQLAlchemy's `before_cursor_execute` event on the engine and counts statements (bound parameters aside -- the same query with different parameter *values* still produces an identical parameterized statement string, so `SELECT ... WHERE id = ?` run once per row in a loop groups together as one entry with a high count) per request, via a :class:`contextvars.ContextVar`, the same mechanism :mod:`zeython.request_id` uses.

### N1QueryDetectionMiddleware

```python
N1QueryDetectionMiddleware(
    app: Any, *, threshold: int = DEFAULT_THRESHOLD
)
```

Pure ASGI middleware: counts SQL statements per request, warning (`zeython.n_plus_one`, at `WARNING`) for any statement shape that ran more than `threshold` times in the same request.

Source code in `src/zeython/n_plus_one.py`

```python
def __init__(self, app: Any, *, threshold: int = DEFAULT_THRESHOLD) -> None:
    self.app = app
    self.threshold = threshold
```

### N1QueryDetectionServiceProvider

```python
N1QueryDetectionServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Hooks the SQLAlchemy engine and registers :class:`N1QueryDetectionMiddleware` -- not registered by default, and a no-op in `boot()` unless `APP_DEBUG` is true, so it's safe to always register (including in a production `main.py`) without worrying about the per-query event-listener overhead or leaking query text/counts from real traffic into production logs::

```text
# main.py
app.register(DatabaseServiceProvider)  # must run first -- binds Database
app.register(N1QueryDetectionServiceProvider(app))
```

Configurable via `.env`:

- `N1_QUERY_THRESHOLD` -- default 10.

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

## profiler

Request/query profiler: an opt-in, dev-only record of every SQL query a request ran, with duration -- the Laravel Telescope / Django Debug Toolbar question ("how many queries did this request run, and how long did they take") answered without a bundled UI, since most of what this framework serves is a JSON API rather than server-rendered HTML pages a toolbar overlay could attach to.

Every response gets `X-Debug-Duration-Ms`/`X-Debug-Query-Count`/ `X-Debug-Query-Time-Ms` headers instead -- inspectable from any HTTP client, a browser's network tab, or a test assertion, no special tooling required. A request that crashes gets the same information baked into the debug error page/body (see :mod:`zeython.exceptions`).

Deliberately separate from :mod:`zeython.n_plus_one`, which answers a different, narrower question (the same statement shape repeated suspiciously many times) and can be registered independently of this.

### RequestProfilerMiddleware

```python
RequestProfilerMiddleware(
    app: Callable[..., Any],
    *,
    slow_query_threshold_ms: float = DEFAULT_SLOW_QUERY_MS,
)
```

Pure ASGI middleware: records this request's queries via a :class:`~contextvars.ContextVar` (the same mechanism :mod:`zeython.request_id`/:mod:`zeython.n_plus_one` use), stamps `X-Debug-Duration-Ms`/`X-Debug-Query-Count`/`X-Debug-Query-Time-Ms` on the response, and logs (`zeython.profiler`, at `WARNING`) any individual query at or past `slow_query_threshold_ms`.

Source code in `src/zeython/profiler.py`

```python
def __init__(self, app: Callable[..., Any], *, slow_query_threshold_ms: float = DEFAULT_SLOW_QUERY_MS) -> None:
    self.app = app
    self.slow_query_threshold_ms = slow_query_threshold_ms
```

### RequestProfilerServiceProvider

```python
RequestProfilerServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Hooks the SQLAlchemy engine and registers :class:`RequestProfilerMiddleware` -- not registered by default, and a no-op in `boot()` unless `APP_DEBUG` is true, so it's safe to always register (including in a production `main.py`) without worrying about the per-query event-listener overhead or leaking query text/timing from real traffic::

```text
# main.py
app.register(DatabaseServiceProvider)  # must run first -- binds Database
app.register(RequestProfilerServiceProvider(app))
```

Configurable via `.env`:

- `PROFILER_SLOW_QUERY_MS` -- default 100.

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

### current_queries

```python
current_queries() -> list[QueryRecord]
```

The SQL queries executed so far during the current request, in order -- empty if :class:`RequestProfilerServiceProvider` isn't registered (or `APP_DEBUG` is false), or if called outside a request/response cycle the middleware wrapped.

Source code in `src/zeython/profiler.py`

```python
def current_queries() -> list[QueryRecord]:
    """The SQL queries executed so far during the current request, in
    order -- empty if :class:`RequestProfilerServiceProvider` isn't
    registered (or ``APP_DEBUG`` is false), or if called outside a
    request/response cycle the middleware wrapped.
    """
    return list(_current_queries.get() or [])
```

"""Async SQLAlchemy engine and request-scoped session management.

Unlike the synchronous ``SessionLocal()``-per-call pattern common in ad-hoc
Flask apps, Zeython opens exactly one session per request (or per explicit
``async with database.session():`` block), stored in a
:class:`contextvars.ContextVar` so model methods can find it without any
session threading through every function signature.
"""

from __future__ import annotations

import contextvars
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

# Alembic's SQLite "batch mode" (recreate-the-table, the only way SQLite can
# alter a constraint) needs every constraint to have a deterministic name --
# an unnamed foreign key or check constraint can't be dropped and re-added
# during a table rebuild. Without this, a migration as ordinary as adding a
# ForeignKey column to an existing SQLite table raises ``ValueError:
# Constraint must have a name``. This is the naming scheme Alembic's own
# docs recommend for exactly this reason.
_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by every Zeython model."""

    metadata = MetaData(naming_convention=_NAMING_CONVENTION)


_current_session: contextvars.ContextVar[AsyncSession | None] = contextvars.ContextVar(
    "zeython_db_session", default=None
)


class Database:
    """Owns the async engine and session factory for a Zeython application.

    ``read_url``, if given, points at a read replica: :meth:`read_replica`
    opens a session against it instead of the primary. Optional -- with no
    ``read_url``, :meth:`read_replica` just falls back to the primary, so
    code written against it works unchanged whether or not a replica is
    configured. See docs/database.md#read-replicas.
    """

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

    async def create_all(self) -> None:
        """Create all tables known to :class:`Base`. Intended for tests/dev; use migrations in production."""
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def drop_all(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)

    async def dispose(self) -> None:
        await self.engine.dispose()
        if self.read_engine is not None:
            await self.read_engine.dispose()

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


class DatabaseSessionMiddleware:
    """Pure ASGI middleware that opens one DB session per HTTP request.

    Commits when the response status is a success/redirect (``< 400``),
    rolls back otherwise -- including for a ``4xx``/``5xx`` your own
    handler chose to send by raising one of ``zeython``'s
    ``HTTPException`` subclasses (``ValidationException``,
    ``NotFoundException``, etc.). Deliberately does **not** just reuse
    :meth:`Database.session`'s "commit unless an exception propagates"
    rule: Starlette's own ``ExceptionMiddleware`` sits *inside* this
    (user-added) middleware and fully handles every registered
    ``HTTPException`` there -- building and sending the response itself
    -- without ever re-raising past this middleware, so ``self.app(...)``
    below returns completely normally even for a request your handler
    meant to abort. Only the actual response status reveals that. A
    genuinely unhandled exception (no registered handler) still
    propagates here directly and is rolled back the same way, then
    re-raised unchanged.
    """

    def __init__(self, app: object, database: Database) -> None:
        self.app = app
        self.database = database

    async def __call__(self, scope: dict, receive: object, send: object) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)  # type: ignore[operator]
            return

        status_code = 200

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)  # type: ignore[operator]

        session = self.database.session_factory()
        token = _current_session.set(session)
        try:
            await self.app(scope, receive, send_wrapper)  # type: ignore[operator]
        except Exception:
            await session.rollback()
            raise
        else:
            if status_code < 400:
                await session.commit()
            else:
                await session.rollback()
        finally:
            await session.close()
            _current_session.reset(token)

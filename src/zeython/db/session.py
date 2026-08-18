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

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base shared by every Zeython model."""


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

        Read-only in practice, not by any framework-enforced check: a real
        replica is normally configured read-only at the database level
        (Postgres's ``default_transaction_read_only``, a MySQL replica
        user with no write grants), so a write attempted here fails with a
        clear database error rather than being silently accepted -- Zeython
        doesn't duplicate that check in Python. There's also no commit: a
        replica session is for reads, so nothing here needs to be flushed.
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
    no extra API: an exception that propagates out of a request handler
    unwinds past ``DatabaseSessionMiddleware`` and rolls back the whole
    session (see :meth:`Database.session`) -- Starlette re-raises the
    original exception to outer ASGI middleware even after one of your own
    exception handlers already sent a response for it. ``transaction()``
    is for the narrower case where you catch the failure yourself and keep
    the request going, but still don't want its partial writes kept.
    """
    session = current_session()
    async with session.begin_nested():
        yield session


class DatabaseSessionMiddleware:
    """Pure ASGI middleware that opens one DB session per HTTP request."""

    def __init__(self, app: object, database: Database) -> None:
        self.app = app
        self.database = database

    async def __call__(self, scope: dict, receive: object, send: object) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)  # type: ignore[operator]
            return

        async with self.database.session():
            await self.app(scope, receive, send)  # type: ignore[operator]

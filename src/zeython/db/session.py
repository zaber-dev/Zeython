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
    """Owns the async engine and session factory for a Zeython application."""

    def __init__(self, url: str, *, echo: bool = False, **engine_kwargs: object) -> None:
        self.url = url
        self.engine: AsyncEngine = create_async_engine(url, echo=echo, **engine_kwargs)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_all(self) -> None:
        """Create all tables known to :class:`Base`. Intended for tests/dev; use migrations in production."""
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def drop_all(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

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

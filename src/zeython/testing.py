"""Test helpers for Zeython applications."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import itsdangerous
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.testclient import TestClient

from zeython.application import Application
from zeython.csrf import DEFAULT_COOKIE_NAME, DEFAULT_HEADER_NAME
from zeython.db.session import Database, _current_session


@asynccontextmanager
async def client(app: Application, *, base_url: str = "http://testserver") -> AsyncIterator[httpx.AsyncClient]:
    """An ``httpx.AsyncClient`` wired directly to the app's ASGI callable, no sockets involved.

    Named ``client`` rather than ``test_client`` so pytest's ``test_*`` collection
    doesn't mistake this helper for a test function when imported into a test module.

    Automatically attaches the CSRF header (see :mod:`zeython.csrf`) from
    whatever ``csrf_token`` cookie this client is already holding -- the
    same thing a real browser-based app does by reading the cookie in JS,
    so a test doesn't need to plumb the token through by hand. This still
    means the *first* unsafe request in a test needs a prior safe one (a
    ``GET``) to actually receive that cookie -- there's nothing to attach
    before that.

    Usage::

        async with client(app) as http:
            await http.get("/")  # picks up the csrf_token cookie
            response = await http.post("/posts", json={"title": "t"})
            assert response.status_code == 201
    """

    async def _attach_csrf_header(request: httpx.Request) -> None:
        token = http_client.cookies.get(DEFAULT_COOKIE_NAME)
        if token is not None:
            request.headers.setdefault(DEFAULT_HEADER_NAME, token)

    transport = httpx.ASGITransport(app=app.asgi)
    http_client = httpx.AsyncClient(
        transport=transport, base_url=base_url, event_hooks={"request": [_attach_csrf_header]}
    )
    async with http_client:
        yield http_client


def login_as(http_client: httpx.AsyncClient, app: Application, user: Any) -> None:
    """Log ``http_client`` in as ``user`` directly, without a real
    ``POST /login`` -- for a test that needs an authenticated request but
    isn't specifically testing the login flow itself::

        async with client(app) as http:
            login_as(http, app, user)
            response = await http.get("/me")
            assert response.status_code == 200

    Builds the exact signed session cookie Starlette's own
    ``SessionMiddleware`` would set after a real ``login(request, user)``
    call (see :mod:`zeython.auth`) -- same secret key, same cookie name
    (``SESSION_COOKIE_NAME``, default ``zeython_session``) -- and sets it
    directly on the client, so :func:`~zeython.auth.require_auth` and
    :func:`~zeython.auth.current_user` see a real logged-in session on the
    very next request. Requires ``AuthServiceProvider`` to be registered
    (same requirement ``login()`` itself has).
    """
    from zeython.auth import _SESSION_KEY

    cookie_name = app.config.get("session.cookie_name", "zeython_session")
    signer = itsdangerous.TimestampSigner(str(app.config.secret_key))
    payload = base64.b64encode(json.dumps({_SESSION_KEY: user.id}).encode("utf-8"))
    signed = signer.sign(payload)
    http_client.cookies.set(cookie_name, signed.decode("utf-8"))


@asynccontextmanager
async def transactional_session(database: Database) -> AsyncIterator[AsyncSession]:
    """Opens one session for an entire test and rolls it back
    unconditionally on exit, regardless of whether the block raised --
    for a test that writes real data through the Active Record API and
    wants it visible to queries made anywhere in the same test, without
    that data persisting past it.

    Most valuable against a real Postgres/MySQL test database, where
    recreating the schema per test (the usual alternative) is slow.
    Against SQLite's own ``:memory:`` URL -- what the framework's own test
    suite and `zeython new`'s default scaffold both use -- a fresh
    :class:`~zeython.db.Database` per test already gets the same
    isolation for free, so this mostly matters once a project's tests run
    against its real production database engine::

        @pytest_asyncio.fixture
        async def db_session(database: Database):
            async with transactional_session(database):
                yield

    Requires the caller to hold a reference to the app's
    :class:`~zeython.db.Database` directly (e.g. via
    ``app.container.make(Database)``) -- unlike :meth:`Database.session`,
    this doesn't commit, so nesting it inside a request handled by
    ``DatabaseSessionMiddleware`` would conflict with that middleware's
    own session for the same context; use it to wrap a whole test instead.
    """
    session = database.session_factory()
    token = _current_session.set(session)
    try:
        yield session
    finally:
        await session.rollback()
        await session.close()
        _current_session.reset(token)


def websocket_client(app: Application) -> TestClient:
    """A ``starlette.testclient.TestClient`` wired to the app's ASGI callable, for testing WebSocket routes.

    Unlike :func:`client`, this is synchronous -- httpx has no WebSocket
    support, and Starlette's own ``TestClient`` is what actually drives a
    WebSocket handshake against an ASGI app in tests, no real socket
    involved either way.

    Usage::

        with websocket_client(app).websocket_connect("/ws/chat") as ws:
            ws.send_text("hi")
            assert ws.receive_text() == "hi"
    """
    return TestClient(app.asgi)

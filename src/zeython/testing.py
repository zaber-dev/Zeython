"""Test helpers for Zeython applications."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from starlette.testclient import TestClient

from zeython.application import Application
from zeython.csrf import DEFAULT_COOKIE_NAME, DEFAULT_HEADER_NAME


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

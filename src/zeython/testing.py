"""Test helpers for Zeython applications."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from starlette.testclient import TestClient

from zeython.application import Application


@asynccontextmanager
async def client(app: Application, *, base_url: str = "http://testserver") -> AsyncIterator[httpx.AsyncClient]:
    """An ``httpx.AsyncClient`` wired directly to the app's ASGI callable, no sockets involved.

    Named ``client`` rather than ``test_client`` so pytest's ``test_*`` collection
    doesn't mistake this helper for a test function when imported into a test module.

    Usage::

        async with client(app) as http:
            response = await http.get("/users/1")
            assert response.status_code == 200
    """
    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
        yield client


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

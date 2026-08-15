"""Test helpers for Zeython applications."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

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

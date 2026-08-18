"""Conditional GETs: an ``ETag`` on a cacheable response, and a ``304 Not
Modified`` (empty body) when the client's ``If-None-Match`` already
matches it -- for a GET/HEAD response that doesn't change on every
request (a list endpoint between writes, a lookup table), this saves the
client (and the network) the cost of re-downloading a body it already
has. See docs/api-standards.md.
"""

from __future__ import annotations

import hashlib
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.requests import Request

from zeython.providers import ServiceProvider


def _etag_matches(if_none_match: str, etag: str) -> bool:
    if if_none_match.strip() == "*":
        return True
    candidates = (value.strip() for value in if_none_match.split(","))
    return etag in candidates


class ETagMiddleware:
    """Pure ASGI middleware. Buffers a ``GET``/``HEAD`` response's full
    body (so it necessarily holds the whole thing in memory -- fine for a
    typical JSON API response, a poor fit in front of a large file
    download or a streaming response; scope this middleware to specific
    routes, or use :class:`~zeython.storage.Storage` for downloads
    instead of running it in front of everything, if that's a concern),
    computes a strong ``ETag`` (a SHA-256 hash of the body) for any ``200``
    response at or above ``minimum_size`` bytes, and short-circuits to
    ``304 Not Modified`` when the request's ``If-None-Match`` already
    matches it.
    """

    def __init__(self, app: Any, *, minimum_size: int = 0) -> None:
        self.app = app
        self.minimum_size = minimum_size

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope["method"] not in ("GET", "HEAD"):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        if_none_match = request.headers.get("if-none-match")

        start_message: dict | None = None
        body_chunks: list[bytes] = []

        async def buffering_send(message: dict) -> None:
            nonlocal start_message
            if message["type"] == "http.response.start":
                start_message = message
                return

            body_chunks.append(message.get("body", b""))
            if message.get("more_body", False):
                return

            assert start_message is not None
            body = b"".join(body_chunks)

            if start_message["status"] == 200 and len(body) >= self.minimum_size:
                etag = '"' + hashlib.sha256(body).hexdigest() + '"'
                if if_none_match is not None and _etag_matches(if_none_match, etag):
                    await send({"type": "http.response.start", "status": 304, "headers": [(b"etag", etag.encode())]})
                    await send({"type": "http.response.body", "body": b""})
                    return
                MutableHeaders(scope=start_message).append("etag", etag)

            await send(start_message)
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, buffering_send)


class ETagServiceProvider(ServiceProvider):
    """Registers :class:`ETagMiddleware` -- not registered by default::

        # main.py
        app.register(ETagServiceProvider)

    Configurable via ``.env``:

    - ``ETAG_MINIMUM_SIZE`` -- default ``0`` (every 200 response gets an
      ETag). Raise it to skip the hashing cost for tiny responses that
      aren't worth caching.
    """

    def boot(self) -> None:
        self.app.add_middleware(ETagMiddleware, minimum_size=int(self.config.get("etag.minimum_size", 0)))


__all__ = ["ETagMiddleware", "ETagServiceProvider"]

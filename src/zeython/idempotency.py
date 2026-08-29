"""Idempotency keys: replay a mutating request's first response instead of
running it again, for a client that must safely retry a ``POST``/``PUT``/
``PATCH``/``DELETE`` it can't tell succeeded or not -- a dropped
connection, a timeout -- without double-charging a card, double-sending
an email, or creating a duplicate row.

Opt-in per request, the same way Stripe's API works: a request without an
``Idempotency-Key`` header is never touched. Built on
:class:`zeython.cache.Cache` (``InMemoryCache`` by default, ``RedisCache``
for a shared store across processes/machines) -- the same abstraction
application code already uses for caching, not a bespoke storage backend.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
from collections.abc import Iterable
from typing import Any

from starlette.requests import Request

from zeython.cache import Cache, InMemoryCache
from zeython.exceptions import ConflictException, http_exception_handler
from zeython.providers import ServiceProvider

DEFAULT_TTL = 86400.0  # 24 hours -- matches the retention window Stripe's own API documents.
DEFAULT_HEADER = "Idempotency-Key"
DEFAULT_METHODS = ("POST", "PUT", "PATCH", "DELETE")
REPLAYED_HEADER = "Idempotency-Replayed"


async def _drain_body(receive: Any) -> bytes:
    chunks = []
    more_body = True
    while more_body:
        message = await receive()
        chunks.append(message.get("body", b""))
        more_body = message.get("more_body", False)
    return b"".join(chunks)


class IdempotencyMiddleware:
    """Pure ASGI middleware. See :class:`IdempotencyServiceProvider` for the
    usual way to register this.

    A request without the configured header (default ``Idempotency-Key``),
    or whose method isn't in ``methods`` (default ``POST``/``PUT``/
    ``PATCH``/``DELETE`` -- the ones that aren't already naturally
    idempotent), passes straight through untouched.

    A first-seen key runs the request normally and stores its response
    (status, headers, body) under that key, scoped to this method and
    path. A repeated key within ``ttl`` replays the stored response
    verbatim instead of running the request again, adding an
    ``Idempotency-Replayed: true`` response header so a client (or your
    own logs) can tell the two cases apart.

    A repeated key whose request body doesn't match the first request's
    raises :class:`~zeython.exceptions.ConflictException` (409) rather
    than silently returning a stale response for what might be a
    different operation that reused the same key by mistake.

    A repeated key that arrives *while the first request with that key is
    still being processed* waits for it to finish, then replays its
    result, instead of running the operation a second time in parallel --
    correct within one worker process. Across multiple processes or
    machines, only the *stored result* is shared (via
    :class:`~zeython.cache.RedisCache`); two processes racing on a
    brand-new key can both start processing it before either finishes --
    the same in-process-only limitation :class:`~zeython.rate_limit.RateLimiter`
    and :class:`~zeython.cache.Cache` already document for their default
    backends, not something new here.
    """

    def __init__(
        self,
        app: Any,
        *,
        cache: Cache,
        methods: Iterable[str] = DEFAULT_METHODS,
        ttl: float = DEFAULT_TTL,
        header: str = DEFAULT_HEADER,
    ) -> None:
        self.app = app
        self.cache = cache
        self.methods = frozenset(method.upper() for method in methods)
        self.ttl = ttl
        self._header = header.lower().encode("latin-1")
        self._locks: dict[str, asyncio.Lock] = {}

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope["method"].upper() not in self.methods:
            await self.app(scope, receive, send)
            return

        raw_key = dict(scope["headers"]).get(self._header)
        if not raw_key:
            await self.app(scope, receive, send)
            return

        idempotency_key = raw_key.decode("latin-1")
        body = await _drain_body(receive)
        body_hash = hashlib.sha256(body).hexdigest()
        cache_key = f"idempotency:{scope['method']}:{scope['path']}:{idempotency_key}"

        async def replay_receive() -> dict:
            return {"type": "http.request", "body": body, "more_body": False}

        lock = self._locks.setdefault(cache_key, asyncio.Lock())
        try:
            async with lock:
                record = await self.cache.get(cache_key)
                if record is None:
                    await self._process(scope, replay_receive, send, cache_key, body_hash)
                    return
        finally:
            self._locks.pop(cache_key, None)

        # A record already existed -- the lock above only serialized
        # against a request currently *creating* one.
        if record["body_hash"] != body_hash:
            request = Request(scope, receive=replay_receive)
            exc = ConflictException(
                f"Idempotency-Key {idempotency_key!r} was already used with a different request body."
            )
            response = await http_exception_handler(request, exc)
            await response(scope, replay_receive, send)
            return

        await self._send_stored(send, record)

    async def _process(self, scope: dict, receive: Any, send: Any, cache_key: str, body_hash: str) -> None:
        captured: dict[str, Any] = {"status": 200, "headers": [], "body": bytearray()}

        async def capturing_send(message: dict) -> None:
            if message["type"] == "http.response.start":
                captured["status"] = message["status"]
                captured["headers"] = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                captured["body"] += message.get("body", b"")
            await send(message)

        await self.app(scope, receive, capturing_send)

        record = {
            "status": captured["status"],
            "headers": [[key.decode("latin-1"), value.decode("latin-1")] for key, value in captured["headers"]],
            "body": base64.b64encode(bytes(captured["body"])).decode("ascii"),
            "body_hash": body_hash,
        }
        await self.cache.put(cache_key, record, ttl=self.ttl)

    async def _send_stored(self, send: Any, record: dict[str, Any]) -> None:
        headers = [(key.encode("latin-1"), value.encode("latin-1")) for key, value in record["headers"]]
        headers.append((REPLAYED_HEADER.encode("latin-1"), b"true"))
        await send({"type": "http.response.start", "status": record["status"], "headers": headers})
        await send({"type": "http.response.body", "body": base64.b64decode(record["body"])})


class IdempotencyServiceProvider(ServiceProvider):
    """Registers :class:`IdempotencyMiddleware`::

        app.register(IdempotencyServiceProvider(app))

    Uses its own process-local :class:`~zeython.cache.InMemoryCache` by
    default -- pass ``cache=`` to share a :class:`~zeython.cache.RedisCache`
    with the rest of the app instead, so a replay works across every
    process/machine, not just the one that handled the original request.
    """

    def __init__(
        self,
        app: Any,
        *,
        cache: Cache | None = None,
        methods: Iterable[str] = DEFAULT_METHODS,
        ttl: float = DEFAULT_TTL,
        header: str = DEFAULT_HEADER,
    ) -> None:
        super().__init__(app)
        self.cache = cache if cache is not None else InMemoryCache()
        self.methods = methods
        self.ttl = ttl
        self.header = header

    def boot(self) -> None:
        self.app.add_middleware(
            IdempotencyMiddleware,
            cache=self.cache,
            methods=self.methods,
            ttl=self.ttl,
            header=self.header,
        )


__all__ = ["IdempotencyMiddleware", "IdempotencyServiceProvider"]

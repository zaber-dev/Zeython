"""Real-time WebSocket support, built directly on Starlette's ASGI-native
WebSocket handling -- no separate server, no extra process.

``Router.websocket(...)``/``Application.websocket(...)`` registers a
handler the same way ``@app.get(...)`` does for HTTP. :class:`WebSocketHub`
is the process-local "broadcast to everyone connected" registry a chat
window, a live dashboard, or any other push-to-many feature needs;
:class:`RedisWebSocketHub` is the same thing backed by Redis pub/sub, for
a broadcast to reach every worker process, not just this one.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import Iterable

from starlette.websockets import WebSocket, WebSocketDisconnect

from zeython.providers import ServiceProvider

logger = logging.getLogger(__name__)


class WebSocketHub:
    """Tracks connected WebSocket clients and broadcasts messages to them.

    Process-local: a message only reaches clients connected to *this*
    process. Fine for a single worker; running more than one means each
    worker has its own, disjoint set of connections, so a broadcast only
    reaches whichever fraction of clients happen to be on the same worker
    -- back this with a pub/sub backend (Redis's ``PUBLISH``/``SUBSCRIBE``
    is the usual choice) once that matters. See docs/websockets.md.

    A WebSocket handshake is a plain HTTP request that carries cookies
    automatically -- without an origin check, any site can open a
    connection here using a logged-in visitor's session (cross-site
    WebSocket hijacking). Pass ``allowed_origins`` to guard against that;
    left unset, every origin is accepted (matches every earlier release --
    opt in once you actually serve browser clients over more than one
    origin you don't control).

    Nothing stops a single client from opening hundreds of connections --
    each one costs a slot in this hub's memory and a slot in the pool of
    connections a broadcast iterates, so a runaway or malicious client can
    degrade the service for everyone else. Pass ``max_connections_per_ip``
    to cap it; left unset, there's no limit (matches every earlier
    release).
    """

    def __init__(
        self,
        *,
        allowed_origins: Iterable[str] | None = None,
        max_connections_per_ip: int | None = None,
    ) -> None:
        self._connections: set[WebSocket] = set()
        self._connections_by_ip: dict[str, set[WebSocket]] = defaultdict(set)
        self._ip_of_connection: dict[WebSocket, str] = {}
        self._allowed_origins = set(allowed_origins) if allowed_origins is not None else None
        self._max_connections_per_ip = max_connections_per_ip

    def __len__(self) -> int:
        return len(self._connections)

    def _origin_allowed(self, websocket: WebSocket) -> bool:
        if self._allowed_origins is None:
            return True
        origin = websocket.headers.get("origin")
        if origin is None:
            # No Origin header at all -- not a browser cross-site context
            # (a native app, a server-to-server client, curl); browsers
            # always send this header on a cross-origin request, so its
            # absence isn't the thing this check exists to catch.
            return True
        return origin in self._allowed_origins

    @staticmethod
    def _client_ip(websocket: WebSocket) -> str:
        return websocket.client.host if websocket.client else "unknown"

    async def connect(self, websocket: WebSocket) -> bool:
        """Accept the handshake and start tracking this connection.

        Returns ``False`` (after closing the connection, without ever
        accepting it) if ``allowed_origins`` is configured and this
        handshake's ``Origin`` header doesn't match one of them (close code
        4403), or if ``max_connections_per_ip`` is configured and this
        client already has that many connections open (close code 4429).
        Check the return value and bail out if it's ``False`` -- proceeding
        to ``receive_text()``/etc. on a connection that was never accepted
        raises::

            if not await hub.connect(websocket):
                return
        """
        if not self._origin_allowed(websocket):
            await websocket.close(code=4403)
            return False

        ip = self._client_ip(websocket)
        if self._max_connections_per_ip is not None and len(self._connections_by_ip[ip]) >= self._max_connections_per_ip:
            await websocket.close(code=4429)
            return False

        await websocket.accept()
        self._connections.add(websocket)
        self._connections_by_ip[ip].add(websocket)
        self._ip_of_connection[websocket] = ip
        return True

    def disconnect(self, websocket: WebSocket) -> None:
        """Stop tracking a connection -- call this from a ``finally`` block
        once its handler loop ends, however it ends."""
        self._connections.discard(websocket)
        ip = self._ip_of_connection.pop(websocket, None)
        if ip is not None:
            self._connections_by_ip[ip].discard(websocket)
            if not self._connections_by_ip[ip]:
                del self._connections_by_ip[ip]

    async def broadcast(self, message: str | dict, *, exclude: WebSocket | None = None) -> None:
        """Send ``message`` to every connected client except ``exclude``
        (typically the sender, when echoing a chat message back to everyone
        *else*).

        A send failing -- a client that's disconnected but hasn't reached
        this hub's ``disconnect()`` yet -- doesn't stop the broadcast
        reaching everyone else; that connection is just dropped from the
        hub instead.
        """
        stale: list[WebSocket] = []
        for connection in list(self._connections):
            if connection is exclude:
                continue
            try:
                if isinstance(message, str):
                    await connection.send_text(message)
                else:
                    await connection.send_json(message)
            except Exception:
                logger.debug("Dropping a stale WebSocket connection during broadcast", exc_info=True)
                stale.append(connection)

        for connection in stale:
            self._connections.discard(connection)


class RedisWebSocketHub(WebSocketHub):
    """A :class:`WebSocketHub` whose broadcasts reach every process, not
    just this one -- the distributed backend the base class's docstring
    names. Requires the ``redis`` extra (``pip install zeython[redis]``).

    Every process running a ``RedisWebSocketHub`` against the same Redis
    PUBLISHes each broadcast to a shared channel and SUBSCRIBEs to that
    same channel, relaying whatever it receives to its own locally
    connected clients -- so a message broadcast from any one worker
    reaches clients connected to every worker, this one included, with no
    special-casing needed (each published message is tagged with this
    instance's own id so it doesn't relay its own broadcast back to
    clients that already got it directly from :meth:`broadcast`).

    The listener starts automatically on this hub's first :meth:`connect`
    call -- there's no ASGI lifespan hook to start it any earlier, and
    nothing needs the listener running before the first connection exists
    anyway. That first ``connect()`` (and only that one -- later calls see
    the subscription already confirmed) doesn't return until the ``SUBSCRIBE``
    has actually been acknowledged by Redis, not just scheduled: without
    that wait, a client that connects and immediately triggers a broadcast
    could publish before this instance's own subscription had taken
    effect, and Redis pub/sub never redelivers a message to a subscriber
    that wasn't listening yet. Call :meth:`stop` to shut the listener down
    cleanly (mainly useful in tests; a real process just exits, taking the
    task with it).

    Doesn't attempt to reconnect if the Redis connection drops mid-stream
    -- the listener task logs the error and stops; broadcasts stop
    reaching other processes (and this process stops relaying theirs)
    until the process is restarted. The same accepted trade-off as the
    other Redis-backed classes here, none of which implement retry logic:
    simple and predictable beats a hand-rolled reconnect loop that
    becomes its own source of bugs.
    """

    def __init__(
        self,
        url: str,
        *,
        channel: str = "zeython:websockets:broadcast",
        allowed_origins: Iterable[str] | None = None,
        max_connections_per_ip: int | None = None,
    ) -> None:
        super().__init__(allowed_origins=allowed_origins, max_connections_per_ip=max_connections_per_ip)
        try:
            from redis.asyncio import Redis
        except ImportError as exc:
            raise ImportError(
                "RedisWebSocketHub requires the redis package. Install it with: pip install zeython[redis]"
            ) from exc

        self._client = Redis.from_url(url)
        self._channel = channel
        self._instance_id = uuid.uuid4().hex
        self._listener_task: asyncio.Task[None] | None = None
        self._subscribed = asyncio.Event()

    async def connect(self, websocket: WebSocket) -> bool:
        if self._listener_task is None:
            # A fresh Event per listener, not reused across a stop()+reconnect
            # cycle -- reusing the previous (already-set) one would make the
            # wait() below return instantly, before the *new* listener
            # task has actually resubscribed.
            self._subscribed = asyncio.Event()
            self._listener_task = asyncio.create_task(self._listen())
        # Without this, a connect() that returns as soon as the listener
        # task is merely *scheduled* -- not yet actually SUBSCRIBEd --
        # races broadcast()'s PUBLISH: a caller that connects and
        # immediately triggers a broadcast can publish before this
        # instance's own subscription has taken effect, and Redis pub/sub
        # never redelivers a message to a subscriber that wasn't listening
        # yet. Waiting here closes that window -- every connect() that
        # returns is a guarantee this instance is subscribed and ready to
        # relay whatever gets published after.
        await self._subscribed.wait()
        return await super().connect(websocket)

    async def stop(self) -> None:
        """Cancel the background listener task."""
        if self._listener_task is not None:
            self._listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener_task
            self._listener_task = None

    async def broadcast(self, message: str | dict, *, exclude: WebSocket | None = None) -> None:
        """Deliver to this process's own connections immediately (respecting
        ``exclude``, which only ever refers to a connection on this
        process -- another process can't have the same object), then
        publish so every other process's listener relays it to theirs.
        """
        await super().broadcast(message, exclude=exclude)
        envelope = {"origin": self._instance_id, "payload": message}
        await self._client.publish(self._channel, json.dumps(envelope))

    async def _listen(self) -> None:
        pubsub = self._client.pubsub()
        await pubsub.subscribe(self._channel)
        self._subscribed.set()
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    envelope = json.loads(message["data"])
                except (TypeError, ValueError):
                    continue
                if envelope.get("origin") == self._instance_id:
                    continue  # already delivered locally by broadcast() itself
                await super().broadcast(envelope.get("payload"))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("RedisWebSocketHub listener stopped unexpectedly")
        finally:
            await pubsub.unsubscribe(self._channel)
            await pubsub.aclose()


class WebSocketHubServiceProvider(ServiceProvider):
    """Binds a process-local :class:`WebSocketHub` into the container.

    ``WEBSOCKET_ALLOWED_ORIGINS`` -- comma-separated, e.g.
    ``https://example.com,https://app.example.com`` -- restricts handshakes
    to those origins (see :class:`WebSocketHub`'s cross-site hijacking
    note). Unset by default, matching every earlier release; set it once
    real browser clients are involved and you're not deliberately serving
    other origins too.

    ``WEBSOCKET_MAX_CONNECTIONS_PER_IP`` -- caps concurrent connections
    from a single client (see :class:`WebSocketHub`'s resource-exhaustion
    note). Unset by default, matching every earlier release.

    For a broadcast that reaches every worker process/machine, not just
    this one, bind :class:`RedisWebSocketHub` directly instead of
    registering this provider::

        app.container.singleton(WebSocketHub, lambda: RedisWebSocketHub(config.get("redis.url")))

    See docs/redis.md.
    """

    def register(self) -> None:
        raw = self.config.get("websocket.allowed_origins", "")
        allowed_origins = [origin.strip() for origin in str(raw).split(",") if origin.strip()] or None

        max_connections_per_ip = self.config.get("websocket.max_connections_per_ip")
        if max_connections_per_ip is not None:
            max_connections_per_ip = int(max_connections_per_ip)

        self.container.singleton(
            WebSocketHub,
            lambda: WebSocketHub(
                allowed_origins=allowed_origins,
                max_connections_per_ip=max_connections_per_ip,
            ),
        )


__all__ = [
    "WebSocket",
    "WebSocketDisconnect",
    "WebSocketHub",
    "RedisWebSocketHub",
    "WebSocketHubServiceProvider",
]

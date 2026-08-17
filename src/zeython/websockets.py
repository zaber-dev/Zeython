"""Real-time WebSocket support, built directly on Starlette's ASGI-native
WebSocket handling -- no separate server, no extra process.

``Router.websocket(...)``/``Application.websocket(...)`` registers a
handler the same way ``@app.get(...)`` does for HTTP. :class:`WebSocketHub`
is the process-local "broadcast to everyone connected" registry a chat
window, a live dashboard, or any other push-to-many feature needs.
"""

from __future__ import annotations

import logging
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


__all__ = ["WebSocket", "WebSocketDisconnect", "WebSocketHub", "WebSocketHubServiceProvider"]

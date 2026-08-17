"""Real-time WebSocket support, built directly on Starlette's ASGI-native
WebSocket handling -- no separate server, no extra process.

``Router.websocket(...)``/``Application.websocket(...)`` registers a
handler the same way ``@app.get(...)`` does for HTTP. :class:`WebSocketHub`
is the process-local "broadcast to everyone connected" registry a chat
window, a live dashboard, or any other push-to-many feature needs.
"""

from __future__ import annotations

import logging

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
    """

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    def __len__(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        """Accept the handshake and start tracking this connection."""
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Stop tracking a connection -- call this from a ``finally`` block
        once its handler loop ends, however it ends."""
        self._connections.discard(websocket)

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
    """Binds a process-local :class:`WebSocketHub` into the container."""

    def register(self) -> None:
        self.container.singleton(WebSocketHub, WebSocketHub)


__all__ = ["WebSocket", "WebSocketDisconnect", "WebSocketHub", "WebSocketHubServiceProvider"]

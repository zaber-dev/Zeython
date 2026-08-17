# WebSockets

Real-time features -- a chat window, a live dashboard, a "someone else is
editing this" indicator -- need a persistent, two-way connection HTTP
doesn't give you. Zeython's WebSocket support is built directly on
Starlette's ASGI-native handling: no separate server, no extra process, no
new protocol library to add.

## Defining a handler

```python
# routes/web.py
from zeython.websockets import WebSocket, WebSocketDisconnect

@app.websocket("/ws/echo")
async def echo(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_text()
            await websocket.send_text(f"echo:{message}")
    except WebSocketDisconnect:
        pass
```

`@app.websocket(path, name=...)` registers a handler the same way
`@app.get(...)` does for HTTP -- one required argument, the `WebSocket`
connection, no request/response cycle. `WebSocket`/`WebSocketDisconnect`
are Starlette's own classes, re-exported from `zeython.websockets` so you
don't need a second import source.

A handler owns its own loop: `receive_text()`/`receive_json()` block until
the client sends something (or disconnects, raising `WebSocketDisconnect`
-- always catch it, or every client closing its tab logs a stack trace).

## Broadcasting: `WebSocketHub`

Most real-time features aren't one client talking to itself -- they're one
client's message reaching every *other* connected client. `WebSocketHub`
is that registry:

```python
from zeython.websockets import WebSocket, WebSocketDisconnect, WebSocketHub

@app.websocket("/ws/chat", name="chat")
async def chat(websocket: WebSocket) -> None:
    hub: WebSocketHub = websocket.app.state.container.make(WebSocketHub)
    if not await hub.connect(websocket):
        return  # origin rejected -- already closed, see "Origin protection" below
    try:
        while True:
            message = await websocket.receive_text()
            await hub.broadcast(message, exclude=websocket)
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(websocket)
```

`hub.connect(websocket)` accepts the handshake and starts tracking the
connection, returning `True` -- or, if the origin check below rejects it,
closes the connection without ever accepting it and returns `False`, in
which case the handler must return immediately rather than call
`receive_text()`/etc. on a connection that was never accepted.
`hub.broadcast(message, exclude=websocket)` sends to everyone else
currently connected (drop `exclude` to also echo back to the sender).
Always `disconnect()` in a `finally` block -- a handler's loop can end via
a normal disconnect, an exception, or the client just vanishing, and an
untracked-but-still-in-the-set connection is a slow memory leak that only
shows up under real traffic.

`message` can be a string (`send_text`) or a `dict` (`send_json`) -- the
hub picks the right one automatically. A send failing (a client that
disconnected but hasn't reached `disconnect()` yet) doesn't stop the
broadcast reaching everyone else; that connection is just dropped from
the hub instead.

### Setup

```python
# main.py
from zeython import Application, WebSocketHubServiceProvider

app = Application()
app.register(WebSocketHubServiceProvider)
```

Registered by default in a generated project, alongside a working
`/ws/chat` demo in `routes/web.py`.

### Origin protection

A WebSocket handshake is a plain HTTP request, and a browser attaches
cookies to it automatically -- even one initiated by a page on a
completely different site. Without an origin check, any site can open a
connection here using a logged-in visitor's session (cross-site WebSocket
hijacking, the WebSocket analogue of [CSRF](csrf.md)). Set
`WEBSOCKET_ALLOWED_ORIGINS` (comma-separated) once real browser clients
are involved and you're not deliberately serving other origins too:

```env
WEBSOCKET_ALLOWED_ORIGINS=https://example.com,https://app.example.com
```

Unset by default -- every origin is accepted, matching every earlier
release. A request with no `Origin` header at all (a native app, a
server-to-server client, `curl`) is always allowed through regardless:
browsers only send this header on a cross-origin request, so its absence
isn't the thing this check exists to catch.

### `WebSocketHub` is process-local

Same trade-off as the default `Cache`/`Queue`/`RateLimiter`: a broadcast
only reaches clients connected to *this* process. Fine for a single
worker; running more than one means each worker has its own, disjoint set
of connections, so a broadcast only reaches whichever fraction of clients
happen to be on the same worker as the sender. There's no bundled
distributed hub -- wiring one up means picking a pub/sub backend (Redis's
`PUBLISH`/`SUBSCRIBE` is the usual choice) and having every worker
subscribe, forwarding what it receives to its own local connections; the
shape doesn't change (`connect`/`disconnect`/`broadcast`), only where the
fan-out happens.

## Testing

```python
from zeython.testing import websocket_client

def test_echo() -> None:
    with websocket_client(app).websocket_connect("/ws/echo") as ws:
        ws.send_text("hello")
        assert ws.receive_text() == "echo:hello"
```

`websocket_client()` wraps `starlette.testclient.TestClient` -- unlike
`zeython.testing.client` (an async `httpx.AsyncClient` for HTTP), this is
**synchronous**: httpx has no WebSocket support, and Starlette's own
`TestClient` is what actually drives a WebSocket handshake against an ASGI
app in tests. Write these as plain `def test_...`, not `async def` --
`TestClient` manages its own event loop internally, and calling it from
inside a pytest-asyncio-wrapped test raises "asyncio.run() cannot be
called from a running event loop." No real socket is involved either way,
same as HTTP testing.

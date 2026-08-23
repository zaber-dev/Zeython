"""Tests for RedisWebSocketHub -- skipped if the `redis` extra isn't
installed, or if no Redis server is reachable at TEST_REDIS_URL (default
redis://localhost:6379/15 -- db 15, to stay out of the way of anything
else that might be using db 0). See tests/test_redis_backends.py.

Each `websocket_client(app)` call creates a *new* `TestClient`, which runs
the app in its own background thread with its own event loop (Starlette's
TestClient design) -- a legitimate stand-in for "a different worker
process" when two connections are meant to belong to different hub
instances (`test_broadcast_reaches_a_different_process_via_redis`).

But two connections meant to share *one* hub instance (two clients on the
same process/app) must come from the *same* `TestClient` -- i.e. call
`websocket_client(app)` once and open both `.websocket_connect()`s on
that one instance, the same way `test_broadcast_reaches_local_connections`
already does. `RedisWebSocketHub.connect()` lazily binds its listener
task to whichever event loop happens to be running on the *first*
`connect()` call, and `broadcast()` (called from any connected client's
handler) walks every connection in the shared `_connections` set,
including ones that live on a different `TestClient`'s thread/loop --
awaiting a send on a WebSocket object owned by a foreign event loop is
undefined behavior with anyio's stream primitives, and was observed to
hang intermittently in CI until connections sharing a hub were changed to
share a `TestClient` too. This is purely a test-harness hazard: a real
ASGI server serves an entire process from one event loop, so production
`WebSocketHub`/`RedisWebSocketHub` usage never has connections spanning
more than one loop to begin with.

Tests never call `hub.stop()` on a hub whose listener task was created
inside a TestClient's background thread (the task, and the thread's whole
event loop, are already gone by the time the `with` block exits; there's
nothing left to cancel). The one test that does call `stop()` builds
everything in the outer event loop directly, without going through a
TestClient at all.

Two real races were found and fixed via repeated local stress-testing
against a real Redis server (CI failures alone don't reproduce reliably
enough to debug from): the cross-TestClient hub-sharing hazard above, and
RedisWebSocketHub.connect() previously returning as soon as its listener
task was merely *scheduled*, not once its SUBSCRIBE was actually
acknowledged by Redis -- closed by having connect() await that
confirmation (see the class docstring in zeython/websockets.py). Both
measurably cut the hang rate (roughly 1 in 15-18 runs down to roughly 1
in 40), but didn't eliminate it entirely -- a residual, rarer hang
(observed as low as 1 in 80 runs, on tests that don't obviously touch the
races above) remains, same accepted, not-fully-root-caused category as
tests/test_redis_queue.py's own documented flake: something about
Starlette TestClient's one-thread-plus-one-event-loop-per-connection
model, redis-py's async client, and anyio's blocking portal occasionally
missing a wakeup under load. pytest-timeout (pyproject.toml, 60s) is the
backstop so a recurrence fails a CI job loudly within a minute instead of
hanging it indefinitely -- if a run fails here with a Timeout traceback,
re-running is the correct response, not a sign your change broke
something.
"""

import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

pytest.importorskip("redis")

from zeython.application import Application  # noqa: E402
from zeython.config import Config  # noqa: E402
from zeython.testing import websocket_client  # noqa: E402
from zeython.websockets import (  # noqa: E402
    RedisWebSocketHub,
    WebSocket,
    WebSocketDisconnect,
    WebSocketHub,
)

REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")


@pytest_asyncio.fixture(autouse=True)
async def _require_redis() -> None:
    from redis.asyncio import Redis

    client = Redis.from_url(REDIS_URL)
    try:
        await client.ping()
    except Exception:
        pytest.skip(f"No Redis server reachable at {REDIS_URL}")
    finally:
        await client.aclose()


def _make_app_with_chat(base_path: Path, hub: WebSocketHub) -> Application:
    base_path.mkdir(parents=True, exist_ok=True)
    app = Application(Config.load(base_path))
    app.container.instance(WebSocketHub, hub)

    @app.websocket("/ws/chat", name="chat")
    async def chat(websocket: WebSocket) -> None:
        connected_hub: WebSocketHub = websocket.app.state.container.make(WebSocketHub)
        if not await connected_hub.connect(websocket):
            return
        try:
            while True:
                message = await websocket.receive_text()
                await connected_hub.broadcast(message, exclude=websocket)
        except WebSocketDisconnect:
            pass
        finally:
            connected_hub.disconnect(websocket)

    return app


@pytest.fixture
def channel() -> str:
    # A fresh channel per test avoids cross-talk with a previous test's
    # listener that hasn't fully unsubscribed yet.
    return f"zeython-test:ws:{uuid.uuid4().hex}"


def test_broadcast_reaches_local_connections(tmp_path: Path, channel: str) -> None:
    app = _make_app_with_chat(tmp_path, RedisWebSocketHub(REDIS_URL, channel=channel))

    test_client = websocket_client(app)
    with (
        test_client.websocket_connect("/ws/chat") as alice,
        test_client.websocket_connect("/ws/chat") as bob,
    ):
        alice.send_text("hi from alice")
        assert bob.receive_text() == "hi from alice"


def test_broadcast_reaches_a_different_process_via_redis(tmp_path: Path, channel: str) -> None:
    # Two separate Application instances, each with its own RedisWebSocketHub
    # (pointed at the same Redis + channel), stand in for two separate
    # worker processes -- the one thing InMemoryHub cannot do at all.
    app_a = _make_app_with_chat(tmp_path / "a", RedisWebSocketHub(REDIS_URL, channel=channel))
    app_b = _make_app_with_chat(tmp_path / "b", RedisWebSocketHub(REDIS_URL, channel=channel))

    with (
        websocket_client(app_a).websocket_connect("/ws/chat") as on_process_a,
        websocket_client(app_b).websocket_connect("/ws/chat") as on_process_b,
    ):
        on_process_a.send_text("cross-process hello")
        assert on_process_b.receive_text() == "cross-process hello"

        on_process_b.send_text("cross-process reply")
        assert on_process_a.receive_text() == "cross-process reply"


def test_broadcast_is_not_duplicated_on_the_senders_own_process(tmp_path: Path, channel: str) -> None:
    # Regression guard for the self-echo problem: the sending process is
    # also subscribed to its own channel, so without origin-tagging a
    # broadcast would be delivered to that process's other local clients
    # twice -- once directly in broadcast(), once relayed back from its
    # own Redis subscription. Proven via message order: if "first" were
    # duplicated, the peer's *second* receive would return the stale
    # extra "first" instead of the genuinely next "second" message.
    app_a = _make_app_with_chat(tmp_path / "a", RedisWebSocketHub(REDIS_URL, channel=channel))
    app_b = _make_app_with_chat(tmp_path / "b", RedisWebSocketHub(REDIS_URL, channel=channel))
    # sender/same_process_peer share app_a's hub -- must share a TestClient
    # (see the module docstring for why crossing threads here can hang).
    client_a = websocket_client(app_a)

    with (
        client_a.websocket_connect("/ws/chat") as sender,
        client_a.websocket_connect("/ws/chat") as same_process_peer,
        websocket_client(app_b).websocket_connect("/ws/chat") as other_process_peer,
    ):
        sender.send_text("first")
        assert same_process_peer.receive_text() == "first"
        assert other_process_peer.receive_text() == "first"

        sender.send_text("second")
        assert same_process_peer.receive_text() == "second"
        assert other_process_peer.receive_text() == "second"


def test_different_channels_do_not_cross_talk(tmp_path: Path) -> None:
    app_a = _make_app_with_chat(tmp_path / "a", RedisWebSocketHub(REDIS_URL, channel="zeython-test:ws:channel-a"))
    app_b = _make_app_with_chat(tmp_path / "b", RedisWebSocketHub(REDIS_URL, channel="zeython-test:ws:channel-b"))
    # sender_b/peer_b share app_b's hub -- must share a TestClient (see
    # the module docstring for why crossing threads here can hang).
    client_b = websocket_client(app_b)

    with (
        websocket_client(app_a).websocket_connect("/ws/chat") as sender_a,
        client_b.websocket_connect("/ws/chat") as sender_b,
        client_b.websocket_connect("/ws/chat") as peer_b,
    ):
        sender_a.send_text("should stay on channel a")
        # If that leaked onto channel b, peer_b's next message would be
        # this stray one instead of the one actually sent on channel b.
        sender_b.send_text("actually on channel b")
        assert peer_b.receive_text() == "actually on channel b"


async def test_stop_cancels_the_listener_task_cleanly(channel: str) -> None:
    hub = RedisWebSocketHub(REDIS_URL, channel=channel)

    class _FakeWebSocket:
        headers: dict = {}
        client = None

        async def accept(self) -> None: ...

        async def close(self, code: int) -> None: ...

    await hub.connect(_FakeWebSocket())  # type: ignore[arg-type]
    assert hub._listener_task is not None

    await hub.stop()
    assert hub._listener_task is None

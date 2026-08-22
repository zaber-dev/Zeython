"""Tests for RedisWebSocketHub -- skipped if the `redis` extra isn't
installed, or if no Redis server is reachable at TEST_REDIS_URL (default
redis://localhost:6379/15 -- db 15, to stay out of the way of anything
else that might be using db 0). See tests/test_redis_backends.py.

Each `websocket_client(app)` connection runs the app in its own
background thread with its own event loop (Starlette's TestClient), torn
down when its `with websocket_connect(...)` block exits -- a legitimate
stand-in for "a different worker process," and why these tests never call
`hub.stop()` on a hub whose listener task was created inside one of those
threads (the task, and the thread's whole event loop, are already gone by
the time the `with` block exits; there's nothing left to cancel). The one
test that does call `stop()` builds everything in the outer event loop
directly, without going through a TestClient at all.
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

    with (
        websocket_client(app_a).websocket_connect("/ws/chat") as sender,
        websocket_client(app_a).websocket_connect("/ws/chat") as same_process_peer,
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

    with (
        websocket_client(app_a).websocket_connect("/ws/chat") as sender_a,
        websocket_client(app_b).websocket_connect("/ws/chat") as sender_b,
        websocket_client(app_b).websocket_connect("/ws/chat") as peer_b,
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

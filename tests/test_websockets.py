from pathlib import Path

import pytest
from starlette.routing import WebSocketRoute

from zeython.application import Application
from zeython.config import Config
from zeython.testing import websocket_client
from zeython.websockets import (
    WebSocket,
    WebSocketDisconnect,
    WebSocketHub,
    WebSocketHubServiceProvider,
)


def _make_app(tmp_path: Path) -> Application:
    return Application(Config.load(tmp_path))


def _register_echo(app: Application) -> None:
    @app.websocket("/ws/echo")
    async def echo(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                message = await websocket.receive_text()
                await websocket.send_text(f"echo:{message}")
        except WebSocketDisconnect:
            pass


def _register_chat(app: Application) -> None:
    @app.websocket("/ws/chat", name="chat")
    async def chat(websocket: WebSocket) -> None:
        hub: WebSocketHub = websocket.app.state.container.make(WebSocketHub)
        if not await hub.connect(websocket):
            return
        try:
            while True:
                message = await websocket.receive_text()
                await hub.broadcast(message, exclude=websocket)
        except WebSocketDisconnect:
            pass
        finally:
            hub.disconnect(websocket)


# -- Router.websocket() / Application.websocket() -------------------------------------


def test_websocket_route_is_registered_on_the_router(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    _register_echo(app)

    routes = [route for route in app.router.routes if isinstance(route, WebSocketRoute)]
    assert len(routes) == 1
    assert routes[0].path == "/ws/echo"


def test_websocket_route_defaults_name_to_the_function_name(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    _register_echo(app)

    route = next(route for route in app.router.routes if isinstance(route, WebSocketRoute))
    assert route.name == "echo"


def test_websocket_route_respects_an_explicit_name(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    _register_chat(app)

    route = next(route for route in app.router.routes if isinstance(route, WebSocketRoute))
    assert route.name == "chat"


def test_echo_round_trip_over_a_real_asgi_websocket_handshake(tmp_path: Path) -> None:
    # Starlette's TestClient drives the actual ASGI WebSocket protocol
    # against the app in-process -- no real socket, same "real protocol,
    # no real network" guarantee zeython.testing.client makes for HTTP.
    app = _make_app(tmp_path)
    _register_echo(app)

    with websocket_client(app).websocket_connect("/ws/echo") as ws:
        ws.send_text("hello")
        assert ws.receive_text() == "echo:hello"


# -- WebSocketHub, exercised through a real handshake ----------------------------------


def test_hub_broadcast_reaches_other_clients_but_not_the_sender(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    app.register(WebSocketHubServiceProvider)
    _register_chat(app)

    test_client = websocket_client(app)
    with (
        test_client.websocket_connect("/ws/chat") as alice,
        test_client.websocket_connect("/ws/chat") as bob,
    ):
        alice.send_text("hi from alice")
        assert bob.receive_text() == "hi from alice"

        bob.send_text("hi from bob")
        assert alice.receive_text() == "hi from bob"


def test_hub_len_reflects_connected_clients(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    app.register(WebSocketHubServiceProvider)
    _register_chat(app)

    hub = app.container.make(WebSocketHub)
    test_client = websocket_client(app)

    assert len(hub) == 0
    with test_client.websocket_connect("/ws/chat"):
        assert len(hub) == 1
        with test_client.websocket_connect("/ws/chat"):
            assert len(hub) == 2
        assert len(hub) == 1
    assert len(hub) == 0


def test_websocket_hub_service_provider_binds_a_singleton(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    app.register(WebSocketHubServiceProvider)

    assert app.container.make(WebSocketHub) is app.container.make(WebSocketHub)


# -- WebSocketHub in isolation --------------------------------------------------------


async def test_broadcast_with_no_connections_is_a_noop() -> None:
    hub = WebSocketHub()
    await hub.broadcast("hello")  # must not raise


def test_disconnect_of_an_unknown_connection_is_a_noop() -> None:
    hub = WebSocketHub()
    hub.disconnect(object())  # type: ignore[arg-type]  # must not raise
    assert len(hub) == 0


# -- allowed_origins: cross-site WebSocket hijacking protection -----------------------


def _make_app_with_allowed_origins(tmp_path: Path, *allowed_origins: str) -> Application:
    (tmp_path / ".env").write_text(
        "APP_SECRET_KEY=test\nWEBSOCKET_ALLOWED_ORIGINS=" + ",".join(allowed_origins) + "\n"
    )
    app = Application(Config.load(tmp_path))
    app.register(WebSocketHubServiceProvider)
    _register_chat(app)
    return app


def test_default_hub_has_no_origin_restriction(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    app.register(WebSocketHubServiceProvider)
    _register_chat(app)

    with websocket_client(app).websocket_connect(
        "/ws/chat", headers={"Origin": "https://evil.example"}
    ) as ws:
        ws.send_text("hi")  # connection was accepted -- no error


def test_mismatched_origin_is_rejected(tmp_path: Path) -> None:
    app = _make_app_with_allowed_origins(tmp_path, "https://good.example")

    test_client = websocket_client(app)
    with (
        pytest.raises(WebSocketDisconnect),
        test_client.websocket_connect("/ws/chat", headers={"Origin": "https://evil.example"}),
    ):
        pass


def test_matching_origin_is_accepted(tmp_path: Path) -> None:
    app = _make_app_with_allowed_origins(tmp_path, "https://good.example")

    with websocket_client(app).websocket_connect(
        "/ws/chat", headers={"Origin": "https://good.example"}
    ) as ws:
        ws.send_text("hi")  # connection was accepted -- no error


def test_no_origin_header_at_all_is_accepted(tmp_path: Path) -> None:
    # Native/server-to-server clients don't send an Origin header; only
    # browsers do on cross-origin requests, so absence isn't the thing
    # this check exists to catch.
    app = _make_app_with_allowed_origins(tmp_path, "https://good.example")

    with websocket_client(app).websocket_connect("/ws/chat") as ws:
        ws.send_text("hi")


def test_rejected_connection_is_never_tracked_by_the_hub(tmp_path: Path) -> None:
    app = _make_app_with_allowed_origins(tmp_path, "https://good.example")
    hub = app.container.make(WebSocketHub)

    test_client = websocket_client(app)
    with (
        pytest.raises(WebSocketDisconnect),
        test_client.websocket_connect("/ws/chat", headers={"Origin": "https://evil.example"}),
    ):
        pass

    assert len(hub) == 0

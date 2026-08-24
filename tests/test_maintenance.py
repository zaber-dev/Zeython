from pathlib import Path

from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.maintenance import (
    BYPASS_COOKIE_NAME,
    DEFAULT_STORE_PATH,
    MaintenanceModeMiddleware,
    disable_maintenance_mode,
    enable_maintenance_mode,
    maintenance_store_path,
)
from zeython.testing import client


def _make_app(tmp_path: Path, store_path: Path) -> Application:
    app = Application(Config.load(tmp_path))
    app.add_middleware(MaintenanceModeMiddleware, store_path=store_path)

    @app.get("/")
    async def index(request):
        return JSONResponse({"ok": True})

    return app


# -- Flag file helpers ------------------------------------------------------------------------


def test_maintenance_store_path_defaults_relative_to_base_path(tmp_path: Path) -> None:
    resolved = maintenance_store_path(tmp_path, None)
    assert resolved == tmp_path / DEFAULT_STORE_PATH


def test_maintenance_store_path_honors_an_absolute_override(tmp_path: Path) -> None:
    absolute = tmp_path / "elsewhere" / "down.json"
    resolved = maintenance_store_path(tmp_path, str(absolute))
    assert resolved == absolute


def test_enable_creates_parent_directories_and_returns_the_secret(tmp_path: Path) -> None:
    store_path = tmp_path / "storage" / "framework" / "down.json"
    secret = enable_maintenance_mode(store_path, secret="my-secret")
    assert secret == "my-secret"
    assert store_path.exists()
    assert "my-secret" in store_path.read_text()


def test_enable_generates_a_secret_when_none_given(tmp_path: Path) -> None:
    store_path = tmp_path / "down.json"
    secret = enable_maintenance_mode(store_path)
    assert secret  # non-empty


def test_disable_removes_the_file_and_reports_whether_it_existed(tmp_path: Path) -> None:
    store_path = tmp_path / "down.json"
    assert disable_maintenance_mode(store_path) is False

    enable_maintenance_mode(store_path)
    assert disable_maintenance_mode(store_path) is True
    assert not store_path.exists()


# -- Middleware behavior ------------------------------------------------------------------------


async def test_app_responds_normally_with_no_flag_file(tmp_path: Path) -> None:
    app = _make_app(tmp_path, tmp_path / "down.json")

    async with client(app) as http:
        response = await http.get("/")
        assert response.status_code == 200
        assert response.json() == {"ok": True}


async def test_requests_get_503_while_down(tmp_path: Path) -> None:
    store_path = tmp_path / "down.json"
    enable_maintenance_mode(store_path, message="Deploying, back soon.")
    app = _make_app(tmp_path, store_path)

    async with client(app) as http:
        response = await http.get("/")
        assert response.status_code == 503
        assert response.json() == {"message": "Deploying, back soon.", "status": 503}


async def test_retry_after_header_is_set_when_configured(tmp_path: Path) -> None:
    store_path = tmp_path / "down.json"
    enable_maintenance_mode(store_path, retry=120)
    app = _make_app(tmp_path, store_path)

    async with client(app) as http:
        response = await http.get("/")
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "120"


async def test_no_retry_after_header_when_not_configured(tmp_path: Path) -> None:
    store_path = tmp_path / "down.json"
    enable_maintenance_mode(store_path)
    app = _make_app(tmp_path, store_path)

    async with client(app) as http:
        response = await http.get("/")
        assert "Retry-After" not in response.headers


async def test_removing_the_flag_file_brings_the_app_back_up_without_a_restart(tmp_path: Path) -> None:
    store_path = tmp_path / "down.json"
    enable_maintenance_mode(store_path)
    app = _make_app(tmp_path, store_path)

    async with client(app) as http:
        assert (await http.get("/")).status_code == 503
        disable_maintenance_mode(store_path)
        assert (await http.get("/")).status_code == 200


async def test_an_allowed_ip_bypasses_maintenance_mode(tmp_path: Path) -> None:
    store_path = tmp_path / "down.json"
    enable_maintenance_mode(store_path, allowed_ips=["127.0.0.1"])
    app = _make_app(tmp_path, store_path)

    # httpx.ASGITransport reports the client as ("testclient", 50000) by default.
    async with client(app) as http:
        response = await http.get("/", extensions={"client": ("127.0.0.1", 12345)})
        assert response.status_code == 200


async def test_visiting_the_secret_url_sets_a_bypass_cookie_and_redirects(tmp_path: Path) -> None:
    store_path = tmp_path / "down.json"
    secret = enable_maintenance_mode(store_path, secret="let-me-in")
    app = _make_app(tmp_path, store_path)

    async with client(app) as http:
        response = await http.get(f"/{secret}", follow_redirects=False)
        assert response.status_code in (302, 307)
        assert response.headers["location"] == "/"
        assert http.cookies.get(BYPASS_COOKIE_NAME) == secret

        # The cookie now carries through on the next request.
        follow_up = await http.get("/")
        assert follow_up.status_code == 200


async def test_bypass_cookie_has_no_secure_flag_by_default(tmp_path: Path) -> None:
    store_path = tmp_path / "down.json"
    secret = enable_maintenance_mode(store_path, secret="let-me-in")
    app = _make_app(tmp_path, store_path)

    async with client(app) as http:
        response = await http.get(f"/{secret}", follow_redirects=False)

    set_cookie = response.headers["set-cookie"]
    assert "secure" not in set_cookie.lower()


async def test_bypass_cookie_gets_secure_flag_when_configured(tmp_path: Path) -> None:
    # Regression guard: the bypass cookie is a bearer credential -- holding
    # it skips maintenance mode entirely -- yet it was the one sensitive
    # cookie in the codebase with no way to opt into Secure at all (unlike
    # the CSRF and session cookies, both config-driven). If the app is
    # served over HTTPS but ever also reachable over plain HTTP (common
    # before HSTS is fully in effect), this cookie would be sent in the
    # clear and interceptable.
    store_path = tmp_path / "down.json"
    secret = enable_maintenance_mode(store_path, secret="let-me-in")
    app = Application(Config.load(tmp_path))
    app.add_middleware(MaintenanceModeMiddleware, store_path=store_path, secure=True)

    @app.get("/")
    async def index(request):
        return JSONResponse({"ok": True})

    async with client(app) as http:
        response = await http.get(f"/{secret}", follow_redirects=False)

    set_cookie = response.headers["set-cookie"]
    assert "secure" in set_cookie.lower()


async def test_a_wrong_bypass_cookie_still_gets_503(tmp_path: Path) -> None:
    store_path = tmp_path / "down.json"
    enable_maintenance_mode(store_path, secret="correct-secret")
    app = _make_app(tmp_path, store_path)

    async with client(app) as http:
        http.cookies.set(BYPASS_COOKIE_NAME, "wrong-guess")
        response = await http.get("/")
        assert response.status_code == 503


async def test_a_corrupted_flag_file_fails_open(tmp_path: Path) -> None:
    store_path = tmp_path / "down.json"
    store_path.write_text("not json")
    app = _make_app(tmp_path, store_path)

    async with client(app) as http:
        response = await http.get("/")
        assert response.status_code == 200


async def test_websocket_scope_is_left_alone(tmp_path: Path) -> None:
    from zeython.websockets import WebSocket

    store_path = tmp_path / "down.json"
    enable_maintenance_mode(store_path)
    app = _make_app(tmp_path, store_path)

    @app.router.websocket("/ws")
    async def ws_handler(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text("hi")
        await websocket.close()

    from zeython.testing import websocket_client

    with websocket_client(app).websocket_connect("/ws") as ws:
        assert ws.receive_text() == "hi"


# -- MaintenanceModeServiceProvider ------------------------------------------------------------


async def test_service_provider_is_inert_with_no_flag_file(tmp_path: Path) -> None:
    from zeython.maintenance import MaintenanceModeServiceProvider

    app = Application(Config.load(tmp_path))
    app.register(MaintenanceModeServiceProvider)

    @app.get("/")
    async def index(request):
        return JSONResponse({"ok": True})

    async with client(app) as http:
        response = await http.get("/")
        assert response.status_code == 200


async def test_service_provider_honors_a_configured_store_path(tmp_path: Path) -> None:
    from zeython.maintenance import MaintenanceModeServiceProvider

    custom_path = tmp_path / "custom" / "down.json"
    (tmp_path / ".env").write_text(f"APP_SECRET_KEY=test\nMAINTENANCE_STORE_PATH={custom_path}\n")
    enable_maintenance_mode(custom_path)

    app = Application(Config.load(tmp_path))
    app.register(MaintenanceModeServiceProvider)

    @app.get("/")
    async def index(request):
        return JSONResponse({"ok": True})

    async with client(app) as http:
        response = await http.get("/")
        assert response.status_code == 503


async def test_service_provider_honors_maintenance_secure_cookie_config(tmp_path: Path) -> None:
    from zeython.maintenance import MaintenanceModeServiceProvider

    store_path = tmp_path / "down.json"
    secret = enable_maintenance_mode(store_path, secret="let-me-in")
    (tmp_path / ".env").write_text(
        f"APP_SECRET_KEY=test\nMAINTENANCE_STORE_PATH={store_path}\nMAINTENANCE_SECURE_COOKIE=true\n"
    )

    app = Application(Config.load(tmp_path))
    app.register(MaintenanceModeServiceProvider)

    @app.get("/")
    async def index(request):
        return JSONResponse({"ok": True})

    async with client(app) as http:
        response = await http.get(f"/{secret}", follow_redirects=False)

    assert "secure" in response.headers["set-cookie"].lower()

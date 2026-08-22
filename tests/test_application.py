import httpx
from starlette.responses import JSONResponse, PlainTextResponse

from zeython.application import Application
from zeython.config import Config
from zeython.exceptions import NotFoundException
from zeython.testing import client


def _make_app(tmp_path) -> Application:
    return Application(Config.load(tmp_path))


async def test_registered_route_is_reachable(tmp_path) -> None:
    app = _make_app(tmp_path)

    @app.get("/hello")
    async def hello(request):
        return PlainTextResponse("hi")

    async with client(app) as http:
        response = await http.get("/hello")

    assert response.status_code == 200
    assert response.text == "hi"


async def test_http_exception_is_rendered_as_json(tmp_path) -> None:
    app = _make_app(tmp_path)

    @app.get("/missing")
    async def missing(request):
        raise NotFoundException("nope")

    async with client(app) as http:
        response = await http.get("/missing")

    assert response.status_code == 404
    assert response.json() == {"error": "nope", "status": 404}


async def test_unregistered_route_returns_404(tmp_path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/does-not-exist")

    assert response.status_code == 404


async def test_include_router_mounts_grouped_routes(tmp_path) -> None:
    from zeython.routing import Router

    app = _make_app(tmp_path)
    api = Router()

    @api.get("/status")
    async def status(request):
        return JSONResponse({"status": "ok"})

    app.include_router(api, prefix="/api")

    async with client(app) as http:
        response = await http.get("/api/status")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_service_providers_boot_before_first_request(tmp_path) -> None:
    from zeython.providers import ServiceProvider

    boot_order: list[str] = []

    class First(ServiceProvider):
        def boot(self) -> None:
            boot_order.append("first")

    class Second(ServiceProvider):
        def boot(self) -> None:
            boot_order.append("second")

    app = _make_app(tmp_path)
    app.register(First)
    app.register(Second)

    async with client(app) as http:
        await http.get("/")

    assert boot_order == ["first", "second"]


def test_container_exposes_config_and_router(tmp_path) -> None:
    app = _make_app(tmp_path)

    assert app.container.make(Config) is app.config
    assert app.container.make(type(app.router)) is app.router


async def test_unhandled_exception_uses_zeythons_own_handler_in_debug_mode(tmp_path) -> None:
    """Regression: Application must never pass its own debug flag straight
    through to Starlette's constructor. Starlette's own ``debug=True``
    makes ``ServerErrorMiddleware`` render its own built-in traceback page
    directly for any unhandled exception, bypassing zeython's registered
    ``Exception`` handler (the JSON traceback / HTML debug page in
    zeython.exceptions) entirely -- checked via a real ASGI round-trip with
    ``raise_app_exceptions=False`` (zeython.testing.client() can't be
    used here: it re-raises the original exception after handling, per
    Starlette's own test-transport behavior; see tests/test_exceptions.py).
    """
    (tmp_path / ".env").write_text("APP_DEBUG=true\n")
    app = _make_app(tmp_path)

    @app.get("/boom")
    async def boom(request):
        raise ValueError("kaboom")

    transport = httpx.ASGITransport(app=app.asgi, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        response = await http.get("/boom")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["error"] == "Internal Server Error"
    assert body["exception"] == "ValueError: kaboom"
    assert "traceback" in body


async def test_unhandled_exception_renders_html_debug_page_for_a_browser_request(tmp_path) -> None:
    (tmp_path / ".env").write_text("APP_DEBUG=true\n")
    app = _make_app(tmp_path)

    @app.get("/boom")
    async def boom(request):
        raise ValueError("kaboom")

    transport = httpx.ASGITransport(app=app.asgi, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        response = await http.get("/boom", headers={"accept": "text/html,application/xhtml+xml"})

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("text/html")
    assert "ValueError" in response.text
    assert "kaboom" in response.text
    assert "GET /boom" in response.text

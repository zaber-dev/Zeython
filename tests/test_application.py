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

from pathlib import Path

from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.providers import CorsServiceProvider
from zeython.testing import client


async def test_cors_headers_present_for_allowed_origin(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("CORS_ORIGINS=https://example.com\n")
    app = Application(Config.load(tmp_path))
    app.register(CorsServiceProvider)

    @app.get("/ping")
    async def ping(request):
        return JSONResponse({"pong": True})

    async with client(app) as http:
        response = await http.get("/ping", headers={"Origin": "https://example.com"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://example.com"


async def test_cors_headers_absent_without_provider(tmp_path: Path) -> None:
    app = Application(Config.load(tmp_path))

    @app.get("/ping")
    async def ping(request):
        return JSONResponse({"pong": True})

    async with client(app) as http:
        response = await http.get("/ping", headers={"Origin": "https://example.com"})

    assert "access-control-allow-origin" not in response.headers


async def test_disallowed_origin_gets_no_cors_header(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("CORS_ORIGINS=https://allowed.example.com\n")
    app = Application(Config.load(tmp_path))
    app.register(CorsServiceProvider)

    @app.get("/ping")
    async def ping(request):
        return JSONResponse({"pong": True})

    async with client(app) as http:
        response = await http.get("/ping", headers={"Origin": "https://evil.example.com"})

    assert "access-control-allow-origin" not in response.headers

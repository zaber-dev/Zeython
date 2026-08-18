from pathlib import Path

from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.gzip import GzipServiceProvider
from zeython.testing import client


def _make_app(tmp_path: Path, body: dict) -> Application:
    app = Application(Config.load(tmp_path))
    app.register(GzipServiceProvider)

    @app.get("/")
    async def index(request):
        return JSONResponse(body)

    return app


async def test_a_large_response_is_gzip_compressed_when_accepted(tmp_path: Path) -> None:
    app = _make_app(tmp_path, {"items": ["x" * 20] * 100})

    async with client(app) as http:
        response = await http.get("/", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers.get("content-encoding") == "gzip"
    # httpx transparently decompresses -- the JSON is still there underneath.
    assert response.json()["items"][0] == "x" * 20


async def test_a_small_response_is_not_compressed(tmp_path: Path) -> None:
    app = _make_app(tmp_path, {"ok": True})

    async with client(app) as http:
        response = await http.get("/", headers={"Accept-Encoding": "gzip"})

    assert "content-encoding" not in response.headers


async def test_gzip_minimum_size_is_configurable(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("GZIP_MINIMUM_SIZE=5\n")
    app = _make_app(tmp_path, {"ok": True})  # small, but now above the lowered threshold

    async with client(app) as http:
        response = await http.get("/", headers={"Accept-Encoding": "gzip"})

    assert response.headers.get("content-encoding") == "gzip"


async def test_without_accept_encoding_the_response_is_uncompressed(tmp_path: Path) -> None:
    app = _make_app(tmp_path, {"items": ["x" * 20] * 100})

    async with client(app) as http:
        response = await http.get("/", headers={"Accept-Encoding": "identity"})

    assert "content-encoding" not in response.headers
    assert response.json()["items"][0] == "x" * 20

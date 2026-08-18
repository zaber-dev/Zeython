from pathlib import Path

from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.etag import ETagServiceProvider
from zeython.testing import client


def _make_app(tmp_path: Path, *, minimum_size: int | None = None) -> Application:
    if minimum_size is not None:
        (tmp_path / ".env").write_text(f"ETAG_MINIMUM_SIZE={minimum_size}\n")
    app = Application(Config.load(tmp_path))
    app.register(ETagServiceProvider)

    @app.get("/")
    async def index(request):
        return JSONResponse({"items": [1, 2, 3]})

    @app.post("/")
    async def create(request):
        return JSONResponse({"created": True}, status_code=201)

    @app.get("/missing")
    async def missing(request):
        from zeython.exceptions import NotFoundException

        raise NotFoundException()

    return app


async def test_a_get_response_receives_an_etag_header(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/")

    assert response.status_code == 200
    assert response.headers.get("etag") is not None
    assert response.json() == {"items": [1, 2, 3]}


async def test_the_same_body_produces_the_same_etag_across_requests(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        first = await http.get("/")
        second = await http.get("/")

    assert first.headers["etag"] == second.headers["etag"]


async def test_a_matching_if_none_match_returns_304_with_no_body(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        first = await http.get("/")
        etag = first.headers["etag"]
        second = await http.get("/", headers={"If-None-Match": etag})

    assert second.status_code == 304
    assert second.content == b""


async def test_a_non_matching_if_none_match_returns_the_full_response(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/", headers={"If-None-Match": '"stale-value"'})

    assert response.status_code == 200
    assert response.json() == {"items": [1, 2, 3]}


async def test_if_none_match_star_always_matches(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/", headers={"If-None-Match": "*"})

    assert response.status_code == 304


async def test_a_post_response_is_not_given_an_etag(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        response = await http.post("/")

    assert response.status_code == 201
    assert "etag" not in response.headers


async def test_a_non_200_response_is_not_given_an_etag(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/missing")

    assert response.status_code == 404
    assert "etag" not in response.headers


async def test_etag_minimum_size_skips_small_responses(tmp_path: Path) -> None:
    app = _make_app(tmp_path, minimum_size=10_000)  # this response's body is far smaller

    async with client(app) as http:
        response = await http.get("/")

    assert response.status_code == 200
    assert "etag" not in response.headers

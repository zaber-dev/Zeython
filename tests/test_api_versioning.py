"""Tests for API versioning -- Router.version(), current_api_version(), and
the deprecated() decorator.
"""

from pathlib import Path

from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.routing import Controller, Router, current_api_version, deprecated
from zeython.testing import client, websocket_client


async def _make_app(tmp_path: Path) -> Application:
    return Application(Config.load(tmp_path))


# -- Router.version() --------------------------------------------------------------


def test_version_mounts_routes_under_a_default_prefix() -> None:
    root = Router()
    with root.version("v1") as v1:
        v1.get("/posts")(lambda request: JSONResponse({}))

    assert root.routes[0].path == "/v1/posts"


def test_version_accepts_an_explicit_prefix() -> None:
    root = Router()
    with root.version("v1", prefix="/api/v1") as v1:
        v1.get("/posts")(lambda request: JSONResponse({}))

    assert root.routes[0].path == "/api/v1/posts"


def test_version_accepts_an_empty_prefix() -> None:
    root = Router()
    with root.version("v1", prefix="") as v1:
        v1.get("/posts")(lambda request: JSONResponse({}))

    assert root.routes[0].path == "/posts"


def test_version_composes_with_the_parent_routers_own_prefix() -> None:
    root = Router(prefix="/api")
    with root.version("v1") as v1:
        v1.get("/posts")(lambda request: JSONResponse({}))

    assert root.routes[0].path == "/api/v1/posts"


def test_routes_added_throughout_the_with_block_are_all_included() -> None:
    # Regression guard: version() must build the sub-router's full route
    # list before folding it into the parent -- appending eagerly, one
    # route at a time, would only be safe if nothing else about the
    # sub-router's registration could still change, which the `with` block
    # explicitly allows for.
    root = Router()
    with root.version("v1") as v1:
        v1.get("/first")(lambda request: JSONResponse({}))
        v1.get("/second")(lambda request: JSONResponse({}))

    paths = {route.path for route in root.routes}
    assert paths == {"/v1/first", "/v1/second"}


def test_two_version_blocks_route_independently() -> None:
    # Regression guard: an earlier implementation mounted each version's
    # sub-router via include(), which wraps it in a Mount("/", ...) --
    # since a Mount's prefix strips to "" at "/", the *first* such Mount
    # matched (and claimed) every request regardless of path, so a second
    # version() block's routes were silently unreachable.
    root = Router()
    with root.version("v1") as v1:
        v1.get("/reports")(lambda request: JSONResponse({}))
    with root.version("v2") as v2:
        v2.get("/reports")(lambda request: JSONResponse({}))

    paths = {route.path for route in root.routes}
    assert paths == {"/v1/reports", "/v2/reports"}


async def test_current_api_version_resolves_during_a_versioned_request(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    with app.router.version("v1") as v1:

        @v1.get("/whoami")
        async def whoami(request):
            return JSONResponse({"version": current_api_version()})

    async with client(app) as http:
        response = await http.get("/v1/whoami")

    assert response.json() == {"version": "v1"}


async def test_current_api_version_is_none_outside_a_versioned_route(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    @app.get("/plain")
    async def plain(request):
        return JSONResponse({"version": current_api_version()})

    async with client(app) as http:
        response = await http.get("/plain")

    assert response.json() == {"version": None}


async def test_two_versions_resolve_independently(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    with app.router.version("v1") as v1:

        @v1.get("/reports")
        async def v1_reports(request):
            return JSONResponse({"version": current_api_version()})

    with app.router.version("v2") as v2:

        @v2.get("/reports")
        async def v2_reports(request):
            return JSONResponse({"version": current_api_version()})

    async with client(app) as http:
        first = await http.get("/v1/reports")
        second = await http.get("/v2/reports")

    assert first.json() == {"version": "v1"}
    assert second.json() == {"version": "v2"}


async def test_version_wraps_websocket_handlers_too(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    with app.router.version("v1") as v1:

        @v1.websocket("/echo")
        async def echo(websocket):
            await websocket.accept()
            await websocket.send_json({"version": current_api_version()})
            await websocket.close()

    with websocket_client(app).websocket_connect("/v1/echo") as ws:
        message = ws.receive_json()

    assert message == {"version": "v1"}


class Posts(Controller):
    async def index(self, request):
        return JSONResponse({"version": current_api_version()})


async def test_version_wraps_resource_controller_actions_too(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    with app.router.version("v1") as v1:
        v1.resource("/posts", Posts, only=("index",))

    async with client(app) as http:
        response = await http.get("/v1/posts")

    assert response.json() == {"version": "v1"}


def test_a_plain_router_has_no_versioning_overhead() -> None:
    router = Router()
    router.get("/ping")(lambda request: JSONResponse({}))

    # A plain (unversioned) router doesn't wrap the endpoint at all --
    # the registered route's endpoint is the original function object.
    assert router.routes[0].endpoint.__name__ == "<lambda>"


# -- deprecated() -------------------------------------------------------------------


async def test_deprecated_sets_the_deprecation_header(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    @app.get("/old")
    @deprecated()
    async def old(request):
        return JSONResponse({"ok": True})

    async with client(app) as http:
        response = await http.get("/old")

    assert response.headers["Deprecation"] == "true"
    assert "Sunset" not in response.headers


async def test_deprecated_sets_the_sunset_header_when_given(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    @app.get("/old")
    @deprecated(sunset="Wed, 01 Jan 2027 00:00:00 GMT")
    async def old(request):
        return JSONResponse({"ok": True})

    async with client(app) as http:
        response = await http.get("/old")

    assert response.headers["Deprecation"] == "true"
    assert response.headers["Sunset"] == "Wed, 01 Jan 2027 00:00:00 GMT"


async def test_deprecated_preserves_the_endpoint_name_for_route_naming(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    @app.get("/old")
    @deprecated()
    async def old_reports(request):
        return JSONResponse({"ok": True})

    route = app.router.routes[-1]
    assert route.name == "old_reports"


async def test_deprecated_composes_with_router_version(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    with app.router.version("v1") as v1:

        @v1.get("/old")
        @deprecated(sunset="Wed, 01 Jan 2027 00:00:00 GMT")
        async def old(request):
            return JSONResponse({"version": current_api_version()})

    async with client(app) as http:
        response = await http.get("/v1/old")

    assert response.json() == {"version": "v1"}
    assert response.headers["Deprecation"] == "true"
    assert response.headers["Sunset"] == "Wed, 01 Jan 2027 00:00:00 GMT"

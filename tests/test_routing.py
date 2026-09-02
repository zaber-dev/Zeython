from pathlib import Path

from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.routing import Controller, Router
from zeython.testing import client


async def _handler(request):
    return JSONResponse({"ok": True})


def test_decorator_registers_a_route() -> None:
    router = Router()
    router.get("/ping")(_handler)

    assert len(router.routes) == 1
    assert router.routes[0].path == "/ping"
    assert router.routes[0].methods == {"GET", "HEAD"}


def test_prefix_is_applied_to_every_route() -> None:
    router = Router(prefix="/api")
    router.get("/ping")(_handler)

    assert router.routes[0].path == "/api/ping"


def test_include_mounts_a_sub_router_under_a_prefix() -> None:
    api = Router()
    api.get("/ping")(_handler)

    root = Router()
    root.include(api, prefix="/v1")

    mount = root.routes[0]
    assert mount.path == "/v1"


class Users(Controller):
    async def index(self, request):
        return JSONResponse({"action": "index"})

    async def show(self, request):
        return JSONResponse({"action": "show"})


def test_resource_registers_conventional_crud_routes() -> None:
    router = Router()
    router.resource("/users", Users, only=("index", "show"))

    paths = {(route.path, tuple(route.methods - {"HEAD"})) for route in router.routes}
    assert ("/users", ("GET",)) in paths
    assert ("/users/{id:int}", ("GET",)) in paths


class UsersWithUpdate(Controller):
    async def update(self, request):
        return JSONResponse({"action": "update"})


def test_resource_update_accepts_both_put_and_patch() -> None:
    # Regression guard: resource()'s own docstring promises "update->PUT/PATCH
    # path/{id}", but only PUT was ever actually registered -- a PATCH
    # request to a resource's update action returned 405, never reaching
    # the controller, contradicting the documented contract and ordinary
    # REST convention.
    router = Router()
    router.resource("/users", UsersWithUpdate, only=("update",))

    assert len(router.routes) == 1
    route = router.routes[0]
    assert route.path == "/users/{id:int}"
    assert route.methods - {"HEAD"} == {"PUT", "PATCH"}


async def test_resource_show_action_rejects_a_non_integer_id_with_a_clean_404(tmp_path: Path) -> None:
    # Regression guard: resource()'s generated show/update/destroy actions
    # all do int(request.path_params["id"]) -- before {id:int}, a
    # non-numeric id (a typo, a stale link, a scanner poking at the API)
    # reached the handler as a plain string and blew up with an unhandled
    # ValueError instead of the ordinary "route didn't match" 404.
    app = Application(Config.load(tmp_path))
    app.router.resource("/users", Users, only=("show",))

    async with client(app) as http:
        valid = await http.get("/users/1")
        invalid = await http.get("/users/not-a-number")

    assert valid.status_code == 200
    assert invalid.status_code == 404

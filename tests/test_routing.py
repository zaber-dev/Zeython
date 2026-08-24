from starlette.responses import JSONResponse

from zeython.routing import Controller, Router


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
    assert ("/users/{id}", ("GET",)) in paths


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
    assert route.path == "/users/{id}"
    assert route.methods - {"HEAD"} == {"PUT", "PATCH"}

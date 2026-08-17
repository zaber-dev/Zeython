"""Direct tests for zeython.providers -- DatabaseServiceProvider has its own
dedicated tests/test_database_pooling.py, and CorsServiceProvider/
ViewServiceProvider are already exercised end-to-end in test_cors.py/
test_views.py. This file covers what neither has: the ServiceProvider
base class's own contract, and RouteServiceProvider, which previously had
no direct test at all -- only indirect coverage via every scaffolded
project's own routes/web.py registering through it.
"""

import sys
from pathlib import Path

from zeython.application import Application
from zeython.config import Config
from zeython.providers import RouteServiceProvider, ServiceProvider
from zeython.routing import Router

# -- ServiceProvider base class -----------------------------------------------------------


def test_init_wires_app_container_and_config(tmp_path: Path) -> None:
    app = Application(Config.load(tmp_path))
    provider = ServiceProvider(app)

    assert provider.app is app
    assert provider.container is app.container
    assert provider.config is app.config


def test_default_register_is_a_noop(tmp_path: Path) -> None:
    app = Application(Config.load(tmp_path))
    ServiceProvider(app).register()  # must not raise


def test_default_boot_is_a_noop(tmp_path: Path) -> None:
    app = Application(Config.load(tmp_path))
    ServiceProvider(app).boot()  # must not raise


# -- RouteServiceProvider -------------------------------------------------------------------


def test_no_modules_registers_no_routes(tmp_path: Path) -> None:
    app = Application(Config.load(tmp_path))
    app.register(RouteServiceProvider(app))

    assert list(app.router.routes) == []


def test_importing_a_module_registers_its_routes(tmp_path: Path, monkeypatch) -> None:
    # Mirrors the real pattern every generated project's routes/web.py
    # uses: `from main import app`, then `@app.get(...)` at module scope --
    # RouteServiceProvider.register() just imports the module for that
    # decorator side effect.
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "provider_test_main.py").write_text("from zeython import Application\n\napp = Application()\n")
    (tmp_path / "provider_test_routes.py").write_text(
        "from provider_test_main import app\n\n"
        "@app.get('/from-a-route-module')\n"
        "async def handler(request):\n"
        "    return {'ok': True}\n"
    )

    try:
        import provider_test_main

        app = provider_test_main.app
        app.register(RouteServiceProvider(app, modules=("provider_test_routes",)))

        paths = [route.path for route in app.router.routes]
        assert "/from-a-route-module" in paths
    finally:
        sys.modules.pop("provider_test_main", None)
        sys.modules.pop("provider_test_routes", None)


def test_multiple_modules_are_all_imported(tmp_path: Path, monkeypatch) -> None:
    imported: list[str] = []
    monkeypatch.syspath_prepend(str(tmp_path))

    for name in ("route_module_one", "route_module_two"):
        (tmp_path / f"{name}.py").write_text(f"IMPORTED_MARKER = '{name}'\n")

    app = Application(Config.load(tmp_path))
    try:
        app.register(RouteServiceProvider(app, modules=("route_module_one", "route_module_two")))
        imported = [sys.modules[name].IMPORTED_MARKER for name in ("route_module_one", "route_module_two")]
    finally:
        sys.modules.pop("route_module_one", None)
        sys.modules.pop("route_module_two", None)

    assert imported == ["route_module_one", "route_module_two"]


def test_router_is_bound_into_the_container(tmp_path: Path) -> None:
    app = Application(Config.load(tmp_path))
    assert app.container.make(Router) is app.router

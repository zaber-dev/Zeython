from pathlib import Path

from zeython.application import Application
from zeython.config import Config
from zeython.db import Database
from zeython.health import HealthCheckServiceProvider
from zeython.providers import DatabaseServiceProvider
from zeython.testing import client


def _make_app(tmp_path: Path, env: str = "") -> Application:
    (tmp_path / ".env").write_text(env)
    return Application(Config.load(tmp_path))


async def test_up_reports_ok_with_no_checks_when_no_database_is_bound(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    app.register(HealthCheckServiceProvider)

    async with client(app) as http:
        response = await http.get("/up")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {}}


async def test_up_reports_ok_and_database_check_when_database_is_healthy(tmp_path: Path) -> None:
    app = _make_app(
        tmp_path, "APP_SECRET_KEY=test-only-secret-not-for-production\nDATABASE_URL=sqlite+aiosqlite:///:memory:\n"
    )
    app.register(HealthCheckServiceProvider)
    app.register(DatabaseServiceProvider)

    async with client(app) as http:
        response = await http.get("/up")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}


async def test_up_reports_503_and_error_when_the_database_check_fails(tmp_path: Path) -> None:
    # A relative path whose parent directory doesn't exist -- sqlite won't
    # create missing parent directories, so connecting genuinely fails,
    # without needing a real unreachable network service to prove it.
    bad_url = f"sqlite+aiosqlite:///{tmp_path}/does/not/exist/db.sqlite"
    app = _make_app(tmp_path, f"APP_SECRET_KEY=test-only-secret-not-for-production\nDATABASE_URL={bad_url}\n")
    app.register(HealthCheckServiceProvider)
    app.register(DatabaseServiceProvider)

    async with client(app) as http:
        response = await http.get("/up")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "checks": {"database": "error"}}


async def test_health_check_enabled_false_disables_the_route(tmp_path: Path) -> None:
    app = _make_app(tmp_path, "HEALTH_CHECK_ENABLED=false\n")
    app.register(HealthCheckServiceProvider)

    async with client(app) as http:
        response = await http.get("/up")

    assert response.status_code == 404


async def test_health_check_path_is_configurable(tmp_path: Path) -> None:
    app = _make_app(tmp_path, "HEALTH_CHECK_PATH=/healthz\n")
    app.register(HealthCheckServiceProvider)

    async with client(app) as http:
        default_path = await http.get("/up")
        configured_path = await http.get("/healthz")

    assert default_path.status_code == 404
    assert configured_path.status_code == 200


async def test_up_route_is_named_health(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    app.register(HealthCheckServiceProvider)
    app.boot()

    names = {getattr(route, "name", None) for route in app.router.routes}
    assert "health" in names


def test_container_has_is_used_so_a_db_less_app_never_constructs_a_database(tmp_path: Path) -> None:
    # HealthCheckServiceProvider must check container.has(Database) before
    # calling container.make(Database) -- Database.__init__ requires a `url`
    # the container can't autowire, so an unguarded make() on an app with no
    # DatabaseServiceProvider would crash the whole health check with a
    # BindingResolutionError instead of just reporting "nothing to check".
    app = Application(Config.load(tmp_path))
    assert app.container.has(Database) is False

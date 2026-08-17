from pathlib import Path

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.auth import Authenticatable, AuthServiceProvider
from zeython.config import Config
from zeython.csrf import CsrfMiddleware, csrf_token
from zeython.db import Model
from zeython.providers import DatabaseServiceProvider
from zeython.testing import client


def _make_app(tmp_path: Path, **middleware_kwargs) -> Application:
    app = Application(Config.load(tmp_path))
    app.add_middleware(CsrfMiddleware, **middleware_kwargs)

    @app.get("/")
    async def index(request):
        return JSONResponse({"token": csrf_token(request)})

    @app.post("/echo")
    async def echo(request):
        return JSONResponse({"ok": True})

    return app


# -- Safe methods -----------------------------------------------------------------------


async def test_safe_methods_are_never_blocked(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/")
        assert response.status_code == 200


async def test_safe_response_issues_a_readable_csrf_cookie(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/")
        assert response.cookies.get("csrf_token") is not None
        # readable by JS -- no HttpOnly attribute on the raw Set-Cookie header
        assert "httponly" not in response.headers["set-cookie"].lower()


async def test_a_second_safe_request_does_not_rotate_the_cookie(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        first = await http.get("/")
        second = await http.get("/")
        assert "set-cookie" not in second.headers
        assert first.cookies.get("csrf_token") == second.json()["token"]


# -- Unsafe methods -----------------------------------------------------------------------


async def test_unsafe_method_without_any_token_is_rejected(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        response = await http.post("/echo")
        assert response.status_code == 403
        assert response.json()["error"].startswith("CSRF token missing or invalid")


async def test_rejection_still_issues_a_fresh_cookie_so_a_retry_can_succeed(tmp_path: Path) -> None:
    # "Self-healing": a client that skipped the safe-request-first step can
    # recover by reading the cookie off the 403 response and retrying.
    app = _make_app(tmp_path)

    async with client(app) as http:
        rejected = await http.post("/echo")
        assert rejected.status_code == 403
        token = rejected.cookies.get("csrf_token")
        assert token is not None

        retry = await http.post("/echo", headers={"X-CSRF-Token": token})
        assert retry.status_code == 200


async def test_unsafe_method_with_matching_cookie_and_header_succeeds(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        await http.get("/")  # primes the cookie; client() auto-attaches the header
        response = await http.post("/echo")
        assert response.status_code == 200


async def test_unsafe_method_with_a_wrong_header_is_rejected(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        await http.get("/")
        response = await http.post("/echo", headers={"X-CSRF-Token": "not-the-right-token"})
        assert response.status_code == 403


async def test_bearer_authenticated_request_bypasses_csrf_entirely(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        response = await http.post("/echo", headers={"Authorization": "Bearer some-token"})
        assert response.status_code == 200


# -- protect_if_cookie_present scoping -----------------------------------------------------


async def test_protect_if_cookie_present_skips_the_check_when_that_cookie_is_absent(tmp_path: Path) -> None:
    app = _make_app(tmp_path, protect_if_cookie_present="zeython_session")

    async with client(app) as http:
        # No `zeython_session` cookie was ever set -- nothing to protect,
        # so this succeeds even with no CSRF header at all.
        response = await http.post("/echo")
        assert response.status_code == 200


async def test_protect_if_cookie_present_enforces_the_check_when_that_cookie_exists(tmp_path: Path) -> None:
    app = _make_app(tmp_path, protect_if_cookie_present="zeython_session")

    async with client(app) as http:
        # Simulates the actual attack: only the session cookie rides along
        # (as a browser would send it automatically, cross-site), with no
        # matching CSRF cookie/header at all -- attaching it directly to
        # this one request rather than warming it up via a prior response,
        # since *any* response through CsrfMiddleware also hands out a
        # fresh, valid csrf_token cookie that client()'s own auto-attach
        # hook would then legitimately (and correctly) pick up and use.
        http.cookies.set("zeython_session", "fake-session-value")
        response = await http.post("/echo")
        assert response.status_code == 403


# -- csrf_token() helper -----------------------------------------------------------------


async def test_csrf_token_helper_reads_the_current_request_token(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/")
        assert response.json()["token"] == response.cookies.get("csrf_token")


# -- Configurable cookie/header names, secure flag ---------------------------------------


async def test_cookie_and_header_names_are_configurable(tmp_path: Path) -> None:
    app = _make_app(tmp_path, cookie_name="my_csrf", header_name="X-My-Csrf")

    async with client(app) as http:
        primed = await http.get("/")
        token = primed.cookies.get("my_csrf")
        assert token is not None

        response = await http.post("/echo", headers={"X-My-Csrf": token})
        assert response.status_code == 200


async def test_secure_true_sets_the_secure_cookie_attribute(tmp_path: Path) -> None:
    app = _make_app(tmp_path, secure=True)

    async with client(app) as http:
        response = await http.get("/")
        assert "secure" in response.headers["set-cookie"].lower()


# -- Wired into AuthServiceProvider by default --------------------------------------------


class CsrfAuthUser(Model, Authenticatable):
    __tablename__ = "csrf_auth_users"
    __hidden__ = ("password_hash",)

    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))


async def _make_auth_app(tmp_path: Path, *, csrf_enabled: bool | None = None) -> Application:
    env = "APP_SECRET_KEY=test-only-secret-not-for-production\nDATABASE_URL=sqlite+aiosqlite:///:memory:\n"
    if csrf_enabled is not None:
        env += f"CSRF_ENABLED={'true' if csrf_enabled else 'false'}\n"
    (tmp_path / ".env").write_text(env)

    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)
    app.register(AuthServiceProvider(app, user_model=CsrfAuthUser))

    from zeython.db.session import Database

    database = app.container.make(Database)
    async with database.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)

    @app.post("/register")
    async def register(request):
        data = await request.json()
        user = CsrfAuthUser(email=data["email"])
        user.set_password(data["password"])
        await user.save()
        from zeython.auth import login

        login(request, user)
        return JSONResponse(user.to_dict(), status_code=201)

    @app.post("/logout")
    async def do_logout(request):
        from zeython.auth import logout

        logout(request)
        return JSONResponse({"ok": True})

    return app


async def test_auth_service_provider_enables_csrf_by_default(tmp_path: Path) -> None:
    app = await _make_auth_app(tmp_path)

    async with client(app) as http:
        await http.get("/")  # primes the cookie
        await http.post("/register", json={"email": "ada@example.com", "password": "hunter2"})
        # Logged in now, so the session cookie is present. A real
        # cross-site forgery has the session cookie ride along
        # automatically but has no way to read/set the matching header --
        # forcing it empty here (overriding client()'s own auto-attach)
        # simulates exactly that.
        response = await http.post("/logout", headers={"X-CSRF-Token": ""})
        assert response.status_code == 403


async def test_csrf_enabled_false_turns_protection_off(tmp_path: Path) -> None:
    app = await _make_auth_app(tmp_path, csrf_enabled=False)

    async with client(app) as http:
        await http.post("/register", json={"email": "ada@example.com", "password": "hunter2"})
        response = await http.post("/logout")
        assert response.status_code == 200

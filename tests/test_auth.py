from pathlib import Path

import pytest
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.auth import (
    Authenticatable,
    AuthManager,
    AuthServiceProvider,
    current_user,
    login,
    logout,
    require_auth,
)
from zeython.config import Config
from zeython.db import Model
from zeython.db.session import Database
from zeython.exceptions import UnauthorizedException
from zeython.providers import DatabaseServiceProvider
from zeython.testing import client


class AuthUser(Model, Authenticatable):
    __tablename__ = "auth_users"
    __hidden__ = ("password_hash",)

    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))


async def _make_app(tmp_path: Path) -> Application:
    (tmp_path / ".env").write_text(
        "APP_SECRET_KEY=test-only-secret-not-for-production\n"
        "DATABASE_URL=sqlite+aiosqlite:///:memory:\n"
    )
    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)
    app.register(AuthServiceProvider(app, user_model=AuthUser))

    database = app.container.make(Database)
    async with database.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)

    @app.post("/register")
    async def register(request):
        data = await request.json()
        user = AuthUser(email=data["email"])
        user.set_password(data["password"])
        await user.save()
        login(request, user)
        return JSONResponse(user.to_dict(), status_code=201)

    @app.post("/login")
    async def do_login(request):
        data = await request.json()
        manager: AuthManager = request.app.state.container.make(AuthManager)
        user = await manager.attempt(data["email"], data["password"])
        if user is None:
            raise UnauthorizedException("Invalid credentials")
        login(request, user)
        return JSONResponse({"ok": True})

    @app.get("/me")
    async def me(request):
        user = await require_auth(request)
        return JSONResponse({"email": user.email})

    @app.get("/me-or-none")
    async def me_or_none(request):
        user = await current_user(request)
        return JSONResponse({"email": user.email if user else None})

    @app.post("/logout")
    async def do_logout(request):
        logout(request)
        return JSONResponse({"ok": True})

    return app


async def test_full_register_login_logout_flow(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        await http.get("/me-or-none")  # primes the CSRF cookie -- see docs/csrf.md
        response = await http.post("/register", json={"email": "ada@example.com", "password": "hunter2"})
        assert response.status_code == 201
        assert "password_hash" not in response.json()

        response = await http.get("/me")
        assert response.status_code == 200
        assert response.json()["email"] == "ada@example.com"

        response = await http.post("/logout")
        assert response.status_code == 200

        response = await http.get("/me")
        assert response.status_code == 401

        response = await http.get("/me-or-none")
        assert response.status_code == 200
        assert response.json()["email"] is None


async def test_login_rejects_wrong_password(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        await http.get("/me-or-none")  # primes the CSRF cookie -- see docs/csrf.md
        await http.post("/register", json={"email": "ada@example.com", "password": "hunter2"})
        await http.post("/logout")

        response = await http.post("/login", json={"email": "ada@example.com", "password": "wrong"})
        assert response.status_code == 401

        response = await http.post("/login", json={"email": "ada@example.com", "password": "hunter2"})
        assert response.status_code == 200

        response = await http.get("/me")
        assert response.status_code == 200


async def test_login_itself_requires_a_valid_csrf_token(tmp_path: Path) -> None:
    # Regression guard against login CSRF: AuthServiceProvider used to pass
    # protect_if_cookie_present=<session cookie name> to CsrfMiddleware,
    # which skips the CSRF check for any unsafe request that doesn't
    # already carry that cookie -- exactly true of the login request
    # itself, since it's the request that *establishes* the session
    # cookie. That exempted login from CSRF protection entirely: a
    # cross-site page could force a victim's browser to log in as an
    # attacker-controlled account with no way to be blocked, since the
    # forged request never had a session cookie to be missing in the
    # first place. Uses a plain httpx client (not zeython.testing.client(),
    # which auto-attaches the CSRF header) specifically to send a request
    # that has the CSRF cookie but not the matching header -- what a
    # cross-site attacker's forged request looks like, since it can read
    # neither.
    import httpx

    app = await _make_app(tmp_path)

    async with client(app) as http:
        await http.get("/me-or-none")  # primes the CSRF cookie
        await http.post("/register", json={"email": "ada@example.com", "password": "hunter2"})
        await http.post("/logout")
        csrf_cookie = http.cookies.get("csrf_token")

    assert csrf_cookie is not None
    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as forged:
        forged.cookies.set("csrf_token", csrf_cookie)
        response = await forged.post("/login", json={"email": "ada@example.com", "password": "hunter2"})

    assert response.status_code == 403


async def test_login_rejects_unknown_user(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        await http.get("/me-or-none")  # primes the CSRF cookie -- see docs/csrf.md
        response = await http.post("/login", json={"email": "nobody@example.com", "password": "x"})
        assert response.status_code == 401


async def test_attempt_still_hashes_on_an_unknown_username(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression guard against timing-based username enumeration:
    # attempt() used to return immediately for an unknown username,
    # skipping password hashing entirely -- hashing is deliberately slow
    # (PBKDF2, 600k iterations) and a database miss is not, so an unknown
    # username responded measurably faster than a known one with a wrong
    # password. Verified deterministically (call count), not by timing,
    # to avoid a flaky CI test -- verify_password() must run exactly once
    # regardless of whether the user exists.
    import zeython.auth as auth_module

    app = await _make_app(tmp_path)
    manager = app.container.make(AuthManager)

    calls = 0
    real_verify_password = auth_module.verify_password

    def counting_verify_password(password: str, hashed: str) -> bool:
        nonlocal calls
        calls += 1
        return real_verify_password(password, hashed)

    monkeypatch.setattr(auth_module, "verify_password", counting_verify_password)

    database = app.container.make(Database)
    async with database.session():
        result = await manager.attempt("nobody@example.com", "whatever")

    assert result is None
    assert calls == 1


async def test_sessions_are_isolated_between_clients(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        await http.post("/register", json={"email": "ada@example.com", "password": "hunter2"})

    # A fresh client (no cookie jar carried over) is unauthenticated.
    async with client(app) as http:
        response = await http.get("/me")
        assert response.status_code == 401

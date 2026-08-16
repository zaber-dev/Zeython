from pathlib import Path

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
        await http.post("/register", json={"email": "ada@example.com", "password": "hunter2"})
        await http.post("/logout")

        response = await http.post("/login", json={"email": "ada@example.com", "password": "wrong"})
        assert response.status_code == 401

        response = await http.post("/login", json={"email": "ada@example.com", "password": "hunter2"})
        assert response.status_code == 200

        response = await http.get("/me")
        assert response.status_code == 200


async def test_login_rejects_unknown_user(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        response = await http.post("/login", json={"email": "nobody@example.com", "password": "x"})
        assert response.status_code == 401


async def test_sessions_are_isolated_between_clients(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        await http.post("/register", json={"email": "ada@example.com", "password": "hunter2"})

    # A fresh client (no cookie jar carried over) is unauthenticated.
    async with client(app) as http:
        response = await http.get("/me")
        assert response.status_code == 401

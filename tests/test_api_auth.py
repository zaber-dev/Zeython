from pathlib import Path

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from starlette.responses import JSONResponse

from zeython.api_auth import (
    ApiAuthServiceProvider,
    TokenManager,
    current_api_user,
    require_api_auth,
)
from zeython.application import Application
from zeython.config import Config
from zeython.db import Model
from zeython.db.session import Database
from zeython.providers import DatabaseServiceProvider
from zeython.testing import client


class ApiAuthUser(Model):
    __tablename__ = "api_auth_users"

    email: Mapped[str] = mapped_column(String(255), unique=True)


async def _database_app(tmp_path: Path) -> Application:
    (tmp_path / ".env").write_text(
        "APP_SECRET_KEY=test-only-secret-not-for-production\nDATABASE_URL=sqlite+aiosqlite:///:memory:\n"
    )
    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)

    database = app.container.make(Database)
    async with database.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)

    return app


# -- TokenManager (no HTTP) ----------------------------------------------------------


async def test_issue_then_verify_returns_the_same_user(tmp_path: Path) -> None:
    app = await _database_app(tmp_path)
    manager = TokenManager(ApiAuthUser, secret_key="secret", expires_in=3600)

    async with app.container.make(Database).session():
        user = await ApiAuthUser.create(email="ada@example.com")
        token = manager.issue(user)

        verified = await manager.verify(token)
        assert verified is not None
        assert verified.id == user.id


async def test_verify_rejects_a_tampered_token(tmp_path: Path) -> None:
    app = await _database_app(tmp_path)
    manager = TokenManager(ApiAuthUser, secret_key="secret", expires_in=3600)

    async with app.container.make(Database).session():
        user = await ApiAuthUser.create(email="ada@example.com")
        token = manager.issue(user)

    # Flip a character in the middle, not the last one: base64's trailing
    # character can carry unused padding bits that some decoders ignore, so
    # tampering only the very end doesn't reliably corrupt the decoded
    # signature bytes. The middle of the string is always significant.
    middle = len(token) // 2
    tampered = token[:middle] + ("a" if token[middle] != "a" else "b") + token[middle + 1 :]

    async with app.container.make(Database).session():
        assert await manager.verify(tampered) is None


async def test_verify_rejects_an_expired_token(tmp_path: Path) -> None:
    # itsdangerous timestamps have 1-second resolution, so expires_in=0 can
    # pass if issue() and verify() land in the same wall-clock second --
    # -1 is always expired (age >= 0 > -1), regardless of timing.
    app = await _database_app(tmp_path)
    manager = TokenManager(ApiAuthUser, secret_key="secret", expires_in=-1)

    async with app.container.make(Database).session():
        user = await ApiAuthUser.create(email="ada@example.com")
        token = manager.issue(user)
        assert await manager.verify(token) is None


async def test_verify_rejects_a_token_for_a_deleted_or_missing_user(tmp_path: Path) -> None:
    app = await _database_app(tmp_path)
    manager = TokenManager(ApiAuthUser, secret_key="secret", expires_in=3600)

    async with app.container.make(Database).session():
        user = await ApiAuthUser.create(email="ada@example.com")
        token = manager.issue(user)
        await user.delete(soft=False)

        assert await manager.verify(token) is None


async def test_verify_rejects_a_well_signed_token_with_no_user_id(tmp_path: Path) -> None:
    await _database_app(tmp_path)
    manager = TokenManager(ApiAuthUser, secret_key="secret", expires_in=3600)
    weird_token = manager._serializer.dumps({"not_user_id": 1})

    assert await manager.verify(weird_token) is None


async def test_tokens_from_different_secrets_are_not_interchangeable(tmp_path: Path) -> None:
    app = await _database_app(tmp_path)
    a = TokenManager(ApiAuthUser, secret_key="secret-a", expires_in=3600)
    b = TokenManager(ApiAuthUser, secret_key="secret-b", expires_in=3600)

    async with app.container.make(Database).session():
        user = await ApiAuthUser.create(email="ada@example.com")
        token = a.issue(user)
        assert await b.verify(token) is None


# -- current_api_user / require_api_auth over HTTP ------------------------------------


async def _make_app(tmp_path: Path) -> Application:
    (tmp_path / ".env").write_text(
        "APP_SECRET_KEY=test-only-secret-not-for-production\nDATABASE_URL=sqlite+aiosqlite:///:memory:\n"
    )
    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)
    app.register(ApiAuthServiceProvider(app, user_model=ApiAuthUser))

    database = app.container.make(Database)
    async with database.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)

    @app.get("/api/me")
    async def me(request):
        user = await require_api_auth(request)
        return JSONResponse({"email": user.email})

    @app.get("/api/me-or-none")
    async def me_or_none(request):
        user = await current_api_user(request)
        return JSONResponse({"email": user.email if user else None})

    return app


async def test_require_api_auth_allows_a_valid_bearer_token(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    manager = app.container.make(TokenManager)

    async with app.container.make(Database).session():
        user = await ApiAuthUser.create(email="ada@example.com")
        token = manager.issue(user)

    async with client(app) as http:
        response = await http.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["email"] == "ada@example.com"


async def test_require_api_auth_rejects_a_missing_header(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/api/me")
        assert response.status_code == 401


async def test_require_api_auth_rejects_a_malformed_header(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/api/me", headers={"Authorization": "not-a-bearer-token"})
        assert response.status_code == 401


async def test_current_api_user_returns_none_without_raising(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/api/me-or-none")
        assert response.status_code == 200
        assert response.json()["email"] is None


# -- ApiAuthServiceProvider -----------------------------------------------------------


def test_default_expiry_is_thirty_days(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("APP_SECRET_KEY=test-only-secret-not-for-production\n")
    app = Application(Config.load(tmp_path))
    app.register(ApiAuthServiceProvider(app, user_model=ApiAuthUser))

    manager = app.container.make(TokenManager)
    assert manager.expires_in == 60 * 60 * 24 * 30


def test_expiry_is_configurable(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "APP_SECRET_KEY=test-only-secret-not-for-production\nAPI_TOKEN_EXPIRES_IN=3600\n"
    )
    app = Application(Config.load(tmp_path))
    app.register(ApiAuthServiceProvider(app, user_model=ApiAuthUser))

    manager = app.container.make(TokenManager)
    assert manager.expires_in == 3600

from pathlib import Path

import pytest
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from starlette.responses import JSONResponse, Response

from zeython.application import Application
from zeython.auth import Authenticatable, AuthServiceProvider, login
from zeython.authorization import AuthorizationServiceProvider, Gate, authorize
from zeython.config import Config
from zeython.db import Model
from zeython.db.session import Database
from zeython.providers import DatabaseServiceProvider
from zeython.testing import client

# -- Gate (no HTTP) -----------------------------------------------------------------


async def test_gate_allows_when_the_check_returns_true() -> None:
    gate = Gate()
    gate.define("edit", lambda user, item: True)

    assert await gate.allows("user", "edit", "item") is True


async def test_gate_denies_when_the_check_returns_false() -> None:
    gate = Gate()
    gate.define("edit", lambda user, item: False)

    assert await gate.allows("user", "edit", "item") is False


async def test_gate_supports_async_checks() -> None:
    async def check(user: str, item: str) -> bool:
        return user == "owner"

    gate = Gate()
    gate.define("edit", check)

    assert await gate.allows("owner", "edit", "item") is True
    assert await gate.allows("stranger", "edit", "item") is False


async def test_gate_denies_is_the_inverse_of_allows() -> None:
    gate = Gate()
    gate.define("edit", lambda user, item: user == "owner")

    assert await gate.denies("owner", "edit", "item") is False
    assert await gate.denies("stranger", "edit", "item") is True


async def test_gate_raises_for_an_undefined_ability() -> None:
    gate = Gate()

    with pytest.raises(KeyError, match="not-registered"):
        await gate.allows("user", "not-registered", "item")


# -- authorize() over HTTP -----------------------------------------------------------


class AuthzUser(Model, Authenticatable):
    __tablename__ = "authz_users"
    __hidden__ = ("password_hash",)

    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))


class AuthzNote(Model):
    __tablename__ = "authz_notes"

    body: Mapped[str] = mapped_column(String(255))
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("authz_users.id"))


async def _make_app(tmp_path: Path) -> Application:
    (tmp_path / ".env").write_text(
        "APP_SECRET_KEY=test-only-secret-not-for-production\nDATABASE_URL=sqlite+aiosqlite:///:memory:\n"
    )
    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)
    app.register(AuthServiceProvider(app, user_model=AuthzUser))
    app.register(AuthorizationServiceProvider)

    database = app.container.make(Database)
    async with database.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)

    gate: Gate = app.container.make(Gate)
    gate.define("delete-note", lambda user, note: note.owner_id == user.id)

    @app.post("/register")
    async def register(request):
        data = await request.json()
        user = AuthzUser(email=data["email"])
        user.set_password(data["password"])
        await user.save()
        login(request, user)
        return JSONResponse(user.to_dict(), status_code=201)

    @app.post("/notes")
    async def create_note(request):
        data = await request.json()
        note = await AuthzNote.create(body=data["body"], owner_id=data["owner_id"])
        return JSONResponse(note.to_dict(), status_code=201)

    @app.delete("/notes/{id}")
    async def delete_note(request):
        note = await AuthzNote.find(int(request.path_params["id"]))
        await authorize(request, "delete-note", note)
        await note.delete()
        return Response(status_code=204)

    return app


async def test_authorize_allows_the_owner(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        owner = (await http.post("/register", json={"email": "owner@example.com", "password": "hunter2"})).json()
        note = (await http.post("/notes", json={"body": "mine", "owner_id": owner["id"]})).json()

        response = await http.delete(f"/notes/{note['id']}")
        assert response.status_code == 204
        # A 204 must have an empty body -- Response(status_code=204), not
        # JSONResponse(None, ...), which would still serialize "null" and
        # crash a real HTTP server on the Content-Length mismatch (the
        # in-process test client here doesn't enforce that the way uvicorn
        # does, so this assertion is the only thing standing between a
        # regression here and it only surfacing against a live server).
        assert response.content == b""


async def test_authorize_forbids_a_non_owner(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        owner = (await http.post("/register", json={"email": "owner@example.com", "password": "hunter2"})).json()
        note = (await http.post("/notes", json={"body": "not yours", "owner_id": owner["id"]})).json()

    # A different logged-in user tries to delete someone else's note.
    async with client(app) as http:
        await http.post("/register", json={"email": "stranger@example.com", "password": "hunter2"})
        response = await http.delete(f"/notes/{note['id']}")
        assert response.status_code == 403


async def test_authorize_requires_login_first(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        owner = (await http.post("/register", json={"email": "owner@example.com", "password": "hunter2"})).json()
        note = (await http.post("/notes", json={"body": "mine", "owner_id": owner["id"]})).json()

    # A fresh, unauthenticated client (no cookie jar carried over).
    async with client(app) as http:
        response = await http.delete(f"/notes/{note['id']}")
        assert response.status_code == 401

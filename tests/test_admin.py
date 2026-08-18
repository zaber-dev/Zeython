"""Tests for zeython.admin -- the auto-generated CRUD admin UI.

Uses a real database (in-memory SQLite), a real logged-in session (via
zeython.testing.login_as), and real CSRF protection (AuthServiceProvider
registers CsrfMiddleware automatically) -- exercising the whole stack a
generated admin page actually runs through, not just AdminServiceProvider
in isolation.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from zeython.admin import AdminServiceProvider
from zeython.application import Application
from zeython.auth import Authenticatable, AuthServiceProvider
from zeython.config import Config
from zeython.db import Model
from zeython.db.session import Database
from zeython.providers import DatabaseServiceProvider
from zeython.testing import client, login_as


class AdminTestUser(Model, Authenticatable):
    __tablename__ = "admin_test_users"
    __hidden__ = ("password_hash",)

    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), default="x")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)


class AdminTestPost(Model):
    __tablename__ = "admin_test_posts"

    title: Mapped[str] = mapped_column(String(255))


async def _make_app(tmp_path: Path, *, guard=lambda user: user.is_admin) -> Application:
    (tmp_path / ".env").write_text(
        "APP_SECRET_KEY=test-only-secret-not-for-production\nDATABASE_URL=sqlite+aiosqlite:///:memory:\n"
    )
    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)
    app.register(AuthServiceProvider(app, user_model=AdminTestUser))
    app.register(AdminServiceProvider(app, models=[AdminTestPost], guard=guard))

    database = app.container.make(Database)
    async with database.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)

    return app


async def _create_user(app: Application, *, is_admin: bool) -> AdminTestUser:
    database = app.container.make(Database)
    async with database.session():
        return await AdminTestUser.create(email=f"user-{is_admin}@example.com", is_admin=is_admin)


# -- Access control -------------------------------------------------------------------------


async def test_dashboard_requires_login(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        response = await http.get("/admin")

    assert response.status_code == 401


async def test_dashboard_rejects_a_logged_in_non_admin(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    user = await _create_user(app, is_admin=False)

    async with client(app) as http:
        login_as(http, app, user)
        response = await http.get("/admin")

    assert response.status_code == 403


async def test_dashboard_allows_a_logged_in_admin(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    user = await _create_user(app, is_admin=True)

    async with client(app) as http:
        login_as(http, app, user)
        response = await http.get("/admin")

    assert response.status_code == 200
    assert "AdminTestPost" in response.text


async def test_guard_may_be_an_async_callable(tmp_path: Path) -> None:
    async def async_guard(user: AdminTestUser) -> bool:
        return user.is_admin

    app = await _make_app(tmp_path, guard=async_guard)
    user = await _create_user(app, is_admin=True)

    async with client(app) as http:
        login_as(http, app, user)
        response = await http.get("/admin")

    assert response.status_code == 200


# -- CRUD -------------------------------------------------------------------------------


async def test_unregistered_model_slug_404s(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    user = await _create_user(app, is_admin=True)

    async with client(app) as http:
        login_as(http, app, user)
        response = await http.get("/admin/nonexistent_table")

    assert response.status_code == 404


async def test_list_view_shows_existing_rows(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    user = await _create_user(app, is_admin=True)
    database = app.container.make(Database)
    async with database.session():
        await AdminTestPost.create(title="Hello World")

    async with client(app) as http:
        login_as(http, app, user)
        response = await http.get("/admin/admin_test_posts")

    assert response.status_code == 200
    assert "Hello World" in response.text


async def test_create_form_renders(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    user = await _create_user(app, is_admin=True)

    async with client(app) as http:
        login_as(http, app, user)
        response = await http.get("/admin/admin_test_posts/new")

    assert response.status_code == 200
    assert 'name="title"' in response.text
    assert 'name="csrf_token"' in response.text


async def test_create_via_post_persists_a_new_row(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    user = await _create_user(app, is_admin=True)

    async with client(app) as http:
        login_as(http, app, user)
        await http.get("/admin/admin_test_posts/new")  # to receive the CSRF cookie
        response = await http.post(
            "/admin/admin_test_posts", data={"title": "A new post"}, follow_redirects=True
        )

    assert response.status_code == 200
    assert "A new post" in response.text

    database = app.container.make(Database)
    async with database.session():
        posts = await AdminTestPost.all()
    assert any(post.title == "A new post" for post in posts)


async def test_edit_form_shows_current_values(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    user = await _create_user(app, is_admin=True)
    database = app.container.make(Database)
    async with database.session():
        post = await AdminTestPost.create(title="Original title")
        post_id = post.id

    async with client(app) as http:
        login_as(http, app, user)
        response = await http.get(f"/admin/admin_test_posts/{post_id}/edit")

    assert response.status_code == 200
    assert 'value="Original title"' in response.text


async def test_update_via_put_persists_the_change(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    user = await _create_user(app, is_admin=True)
    database = app.container.make(Database)
    async with database.session():
        post = await AdminTestPost.create(title="Before")
        post_id = post.id

    async with client(app) as http:
        login_as(http, app, user)
        await http.get(f"/admin/admin_test_posts/{post_id}/edit")
        response = await http.put(
            f"/admin/admin_test_posts/{post_id}", data={"title": "After"}, follow_redirects=True
        )

    assert response.status_code == 200
    async with database.session():
        updated = await AdminTestPost.find(post_id)
    assert updated is not None
    assert updated.title == "After"


async def test_destroy_via_delete_soft_deletes_the_row(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    user = await _create_user(app, is_admin=True)
    database = app.container.make(Database)
    async with database.session():
        post = await AdminTestPost.create(title="Will be deleted")
        post_id = post.id

    async with client(app) as http:
        login_as(http, app, user)
        await http.get("/admin/admin_test_posts")
        response = await http.delete(f"/admin/admin_test_posts/{post_id}", follow_redirects=True)

    assert response.status_code == 200
    async with database.session():
        remaining = await AdminTestPost.all()
        with_deleted = await AdminTestPost.find(post_id, include_deleted=True)
    assert all(item.id != post_id for item in remaining)
    assert with_deleted is not None
    assert with_deleted.is_deleted is True


async def test_destroy_of_a_missing_row_404s(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    user = await _create_user(app, is_admin=True)

    async with client(app) as http:
        login_as(http, app, user)
        await http.get("/admin/admin_test_posts")
        response = await http.delete("/admin/admin_test_posts/999999")

    assert response.status_code == 404


# -- CSRF ---------------------------------------------------------------------------------


async def test_create_without_csrf_header_is_rejected(tmp_path: Path) -> None:
    import httpx

    app = await _make_app(tmp_path)
    user = await _create_user(app, is_admin=True)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        login_as(http, app, user)
        await http.get("/admin/admin_test_posts/new")  # receive the csrf cookie, but don't attach the header
        response = await http.post("/admin/admin_test_posts", data={"title": "Forged"})

    assert response.status_code == 403

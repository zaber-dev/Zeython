from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import Column, ForeignKey, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship
from starlette.responses import JSONResponse, Response

from zeython.application import Application
from zeython.auth import Authenticatable, AuthServiceProvider, login
from zeython.authorization import AuthorizationServiceProvider, Gate, HasRoles, authorize
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


# -- Gate.policy() --------------------------------------------------------------------


class _Post:
    def __init__(self, author: str) -> None:
        self.author = author


class _PostPolicy:
    def update(self, user: str, post: "_Post") -> bool:
        return user == post.author

    def create(self, user: str) -> bool:
        return user == "verified-user"


async def test_gate_dispatches_an_ability_to_the_policy_registered_for_the_resources_type() -> None:
    gate = Gate()
    gate.policy(_Post, _PostPolicy)

    assert await gate.allows("owner", "update", _Post(author="owner")) is True
    assert await gate.allows("stranger", "update", _Post(author="owner")) is False


async def test_gate_policy_dispatches_by_class_when_theres_no_instance_yet() -> None:
    gate = Gate()
    gate.policy(_Post, _PostPolicy)

    assert await gate.allows("verified-user", "create", _Post) is True
    assert await gate.allows("new-user", "create", _Post) is False


async def test_gate_define_takes_precedence_over_a_policy_for_the_same_ability_name() -> None:
    gate = Gate()
    gate.policy(_Post, _PostPolicy)
    gate.define("update", lambda user, post: True)  # always allow, regardless of the policy

    assert await gate.allows("stranger", "update", _Post(author="owner")) is True


async def test_gate_raises_when_no_ability_or_policy_matches() -> None:
    gate = Gate()
    gate.policy(_Post, _PostPolicy)

    with pytest.raises(KeyError, match="delete"):
        await gate.allows("user", "delete", _Post(author="owner"))


async def test_gate_policy_accepts_an_instance_instead_of_a_class() -> None:
    gate = Gate()
    gate.policy(_Post, _PostPolicy())

    assert await gate.allows("owner", "update", _Post(author="owner")) is True


async def test_gate_policy_before_hook_short_circuits_the_ability_method() -> None:
    class _PolicyWithBefore:
        def before(self, user: str, ability: str) -> bool | None:
            return True if user == "super-admin" else None

        def update(self, user: str, post: "_Post") -> bool:
            return user == post.author

    gate = Gate()
    gate.policy(_Post, _PolicyWithBefore)

    assert await gate.allows("super-admin", "update", _Post(author="someone-else")) is True
    assert await gate.allows("stranger", "update", _Post(author="owner")) is False


# -- Gate.before() ----------------------------------------------------------------------


async def test_gate_before_hook_short_circuits_any_ability() -> None:
    gate = Gate()
    gate.define("delete-post", lambda user, post: False)
    gate.before(lambda user, ability, *args: True if user == "admin" else None)

    assert await gate.allows("admin", "delete-post", "post") is True
    assert await gate.allows("regular-user", "delete-post", "post") is False


async def test_gate_before_hook_returning_none_defers_to_the_normal_check() -> None:
    gate = Gate()
    gate.define("delete-post", lambda user, post: user == "owner")
    gate.before(lambda user, ability, *args: None)  # never short-circuits

    assert await gate.allows("owner", "delete-post", "post") is True
    assert await gate.allows("stranger", "delete-post", "post") is False


async def test_gate_before_hook_can_be_async() -> None:
    async def admin_bypass(user: str, ability: str, *args: object) -> bool | None:
        return True if user == "admin" else None

    gate = Gate()
    gate.define("delete-post", lambda user, post: False)
    gate.before(admin_bypass)

    assert await gate.allows("admin", "delete-post", "post") is True


# -- Gate.role() / Gate.permission() / HasRoles ------------------------------------------


class _Role:
    def __init__(self, name: str, permissions: tuple[str, ...] = ()) -> None:
        self.name = name
        self.permissions = [_Permission(p) for p in permissions]


class _Permission:
    def __init__(self, name: str) -> None:
        self.name = name


class _RoleUser(HasRoles):
    def __init__(self, roles: list[_Role]) -> None:
        self.roles = roles


def test_has_role_checks_the_users_roles_by_name() -> None:
    user = _RoleUser([_Role("editor")])

    assert user.has_role("editor") is True
    assert user.has_role("admin") is False


def test_has_any_role_and_has_all_roles() -> None:
    user = _RoleUser([_Role("editor"), _Role("reviewer")])

    assert user.has_any_role("admin", "editor") is True
    assert user.has_any_role("admin", "owner") is False
    assert user.has_all_roles("editor", "reviewer") is True
    assert user.has_all_roles("editor", "admin") is False


def test_has_permission_checks_permissions_via_the_users_roles() -> None:
    user = _RoleUser([_Role("editor", permissions=("posts.update", "posts.delete"))])

    assert user.has_permission("posts.delete") is True
    assert user.has_permission("posts.create") is False


async def test_gate_role_defines_an_ability_gated_on_a_role() -> None:
    gate = Gate()
    gate.define("manage-users", Gate.role("admin"))

    assert await gate.allows(_RoleUser([_Role("admin")]), "manage-users") is True
    assert await gate.allows(_RoleUser([_Role("editor")]), "manage-users") is False


async def test_gate_permission_defines_an_ability_gated_on_a_permission() -> None:
    gate = Gate()
    gate.define("delete-post", Gate.permission("posts.delete"))

    assert await gate.allows(_RoleUser([_Role("editor", permissions=("posts.delete",))]), "delete-post") is True
    assert await gate.allows(_RoleUser([_Role("editor")]), "delete-post") is False


async def test_gate_role_denies_a_user_without_the_has_any_role_method() -> None:
    gate = Gate()
    gate.define("manage-users", Gate.role("admin"))

    assert await gate.allows("not-a-has-roles-user", "manage-users") is False


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
        await http.get("/")  # primes the CSRF cookie (404 is fine) -- see docs/csrf.md
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
        await http.get("/")  # primes the CSRF cookie (404 is fine) -- see docs/csrf.md
        owner = (await http.post("/register", json={"email": "owner@example.com", "password": "hunter2"})).json()
        note = (await http.post("/notes", json={"body": "not yours", "owner_id": owner["id"]})).json()

    # A different logged-in user tries to delete someone else's note.
    async with client(app) as http:
        await http.get("/")  # primes the CSRF cookie (404 is fine) -- see docs/csrf.md
        await http.post("/register", json={"email": "stranger@example.com", "password": "hunter2"})
        response = await http.delete(f"/notes/{note['id']}")
        assert response.status_code == 403


async def test_authorize_requires_login_first(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        await http.get("/")  # primes the CSRF cookie (404 is fine) -- see docs/csrf.md
        owner = (await http.post("/register", json={"email": "owner@example.com", "password": "hunter2"})).json()
        note = (await http.post("/notes", json={"body": "mine", "owner_id": owner["id"]})).json()

    # A fresh, unauthenticated client (no cookie jar carried over).
    async with client(app) as http:
        await http.get("/")  # primes the CSRF cookie (404 is fine) -- see docs/csrf.md
        response = await http.delete(f"/notes/{note['id']}")
        assert response.status_code == 401


# -- HasRoles against real relationships (not test doubles) --------------------------
#
# The Gate-level tests above use plain objects for roles/permissions -- this
# section instead builds the exact many-to-many shape docs/authorization.md
# recommends (Column/Table + lazy="selectin" on both relationships) against
# a real SQLAlchemy model and a real (in-memory sqlite) database, to confirm
# the documented claim: that a *nested* lazy="selectin" cascades (roles, and
# each role's permissions) without needing Model.find(..., include=(...)),
# and without hitting MissingGreenlet -- the failure mode this whole design
# exists to avoid (see docs/relationships.md).

_rbac_user_roles = Table(
    "rbac_user_roles",
    Model.metadata,
    Column("user_id", ForeignKey("rbac_users.id"), primary_key=True),
    Column("role_id", ForeignKey("rbac_roles.id"), primary_key=True),
)
_rbac_role_permissions = Table(
    "rbac_role_permissions",
    Model.metadata,
    Column("role_id", ForeignKey("rbac_roles.id"), primary_key=True),
    Column("permission_id", ForeignKey("rbac_permissions.id"), primary_key=True),
)


class RbacUser(Model, HasRoles):
    __tablename__ = "rbac_users"

    name: Mapped[str] = mapped_column(String(255))
    roles: Mapped[list["RbacRole"]] = relationship(secondary=_rbac_user_roles, lazy="selectin")


class RbacRole(Model):
    __tablename__ = "rbac_roles"

    name: Mapped[str] = mapped_column(String(50), unique=True)
    permissions: Mapped[list["RbacPermission"]] = relationship(secondary=_rbac_role_permissions, lazy="selectin")


class RbacPermission(Model):
    __tablename__ = "rbac_permissions"

    name: Mapped[str] = mapped_column(String(100), unique=True)


@pytest_asyncio.fixture
async def rbac_database() -> AsyncIterator[Database]:
    db = Database("sqlite+aiosqlite:///:memory:")
    async with db.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)
    yield db
    await db.dispose()


async def test_has_role_and_has_permission_work_against_real_relationships_without_include(
    rbac_database: Database,
) -> None:
    async with rbac_database.session():
        admin_permission = await RbacPermission.create(name="posts.delete")
        editor_role = await RbacRole.create(name="editor")
        # Set at construction time, not via a later assignment -- once a
        # relationship attribute has been through a commit, SQLAlchemy's
        # default expire_on_commit means the *next* touch (even a plain
        # assignment, which needs the old collection value to compute
        # what changed) is a lazy load, and a lazy load is a synchronous
        # DB call with no synchronous fallback available in an async
        # session (MissingGreenlet) -- see docs/relationships.md.
        admin_role = await RbacRole.create(name="admin", permissions=[admin_permission])

        user = await RbacUser.create(name="Ada", roles=[editor_role, admin_role])
        user_id = user.id

    async with rbac_database.session():
        # Refetched with plain find() -- no include=(...) -- since
        # lazy="selectin" on the relationship itself is what's doing the
        # eager loading here.
        fetched = await RbacUser.find(user_id)

    assert fetched is not None
    # Accessed *after* the session block closed, same as
    # test_relationships.py's include= tests -- selectin already loaded it.
    assert fetched.has_role("editor") is True
    assert fetched.has_role("owner") is False
    assert fetched.has_any_role("owner", "admin") is True
    assert fetched.has_all_roles("editor", "admin") is True
    assert fetched.has_all_roles("editor", "owner") is False
    # Two relationship hops deep (user -> roles -> permissions) -- the case
    # a single include=("roles",) call couldn't cover on its own.
    assert fetched.has_permission("posts.delete") is True
    assert fetched.has_permission("posts.create") is False


async def test_gate_role_and_permission_work_end_to_end_against_a_real_user(rbac_database: Database) -> None:
    async with rbac_database.session():
        delete_permission = await RbacPermission.create(name="posts.delete")
        admin_role = await RbacRole.create(name="admin", permissions=[delete_permission])
        viewer_role = await RbacRole.create(name="viewer")

        admin_user = await RbacUser.create(name="Admin", roles=[admin_role])
        admin_user_id = admin_user.id

        viewer_user = await RbacUser.create(name="Viewer", roles=[viewer_role])
        viewer_user_id = viewer_user.id

    gate = Gate()
    gate.define("manage-users", Gate.role("admin"))
    gate.define("delete-post", Gate.permission("posts.delete"))

    async with rbac_database.session():
        fetched_admin = await RbacUser.find(admin_user_id)
        fetched_viewer = await RbacUser.find(viewer_user_id)

    assert fetched_admin is not None
    assert fetched_viewer is not None

    assert await gate.allows(fetched_admin, "manage-users") is True
    assert await gate.allows(fetched_viewer, "manage-users") is False
    assert await gate.allows(fetched_admin, "delete-post") is True
    assert await gate.allows(fetched_viewer, "delete-post") is False

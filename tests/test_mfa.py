import time
from pathlib import Path

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column
from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.auth import Authenticatable, AuthManager, AuthServiceProvider, login, require_auth
from zeython.config import Config
from zeython.db import Model
from zeython.db.session import Database
from zeython.exceptions import UnauthorizedException
from zeython.mfa import (
    MfaEnrollable,
    _hotp,
    complete_challenge,
    confirm,
    disable,
    enroll,
    generate_secret,
    pending_user_id,
    provisioning_uri,
    start_challenge,
    verify_and_consume,
    verify_totp,
)
from zeython.providers import DatabaseServiceProvider
from zeython.testing import client

# -- TOTP core --------------------------------------------------------------------------


def _valid_code(secret: str, *, offset: int = 0) -> str:
    counter = int(time.time() // 30) + offset
    return _hotp(secret, counter)


def test_verify_totp_accepts_the_current_code() -> None:
    secret = generate_secret()
    assert verify_totp(secret, _valid_code(secret)) is True


def test_verify_totp_rejects_a_wrong_code() -> None:
    secret = generate_secret()
    code = _valid_code(secret)
    wrong = "0" * 6 if code != "0" * 6 else "1" * 6
    assert verify_totp(secret, wrong) is False


def test_verify_totp_rejects_malformed_input() -> None:
    secret = generate_secret()
    assert verify_totp(secret, "") is False
    assert verify_totp(secret, "abcdef") is False
    assert verify_totp(secret, "12345") is False  # too short
    assert verify_totp(secret, "1234567") is False  # too long


def test_verify_totp_tolerates_one_step_of_clock_drift() -> None:
    secret = generate_secret()
    assert verify_totp(secret, _valid_code(secret, offset=1)) is True
    assert verify_totp(secret, _valid_code(secret, offset=-1)) is True


def test_verify_totp_rejects_codes_outside_the_window() -> None:
    secret = generate_secret()
    assert verify_totp(secret, _valid_code(secret, offset=2)) is False
    assert verify_totp(secret, _valid_code(secret, offset=-2)) is False


def test_provisioning_uri_contains_expected_fields() -> None:
    secret = generate_secret()
    uri = provisioning_uri(secret, account_name="ada@example.com", issuer="Zeython")
    assert uri.startswith("otpauth://totp/")
    assert f"secret={secret}" in uri
    assert "issuer=Zeython" in uri
    assert "ada%40example.com" in uri  # @ percent-encoded in the label


# -- Model setup for enroll/confirm/disable/verify_and_consume --------------------------


class MfaUser(Model, Authenticatable, MfaEnrollable):
    __tablename__ = "mfa_users"
    __hidden__ = ("password_hash", "mfa_secret", "mfa_recovery_codes")

    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    mfa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_recovery_codes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)


async def _make_app(tmp_path: Path) -> Application:
    (tmp_path / ".env").write_text(
        "APP_SECRET_KEY=test-only-secret-not-for-production\nDATABASE_URL=sqlite+aiosqlite:///:memory:\n"
    )
    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)
    app.register(AuthServiceProvider(app, user_model=MfaUser))

    database = app.container.make(Database)
    async with database.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)

    @app.post("/register")
    async def register(request):
        data = await request.json()
        user = MfaUser(email=data["email"])
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
        if user.mfa_enabled:
            start_challenge(request, user)
            return JSONResponse({"mfa_required": True})
        login(request, user)
        return JSONResponse({"ok": True})

    @app.post("/mfa/challenge")
    async def challenge(request):
        data = await request.json()
        user = await complete_challenge(request, data["code"])
        if user is None:
            raise UnauthorizedException("Invalid or expired MFA code.")
        return JSONResponse({"ok": True})

    @app.post("/mfa/enroll")
    async def do_enroll(request):
        user = await require_auth(request)
        enrollment = await enroll(user, account_name=user.email)
        return JSONResponse({"secret": enrollment.secret})

    @app.post("/mfa/confirm")
    async def do_confirm(request):
        user = await require_auth(request)
        data = await request.json()
        codes = await confirm(user, data["code"])
        return JSONResponse({"recovery_codes": codes})

    @app.post("/mfa/disable")
    async def do_disable(request):
        user = await require_auth(request)
        await disable(user)
        return JSONResponse({"ok": True})

    @app.get("/me")
    async def me(request):
        user = await require_auth(request)
        return JSONResponse({"email": user.email, "mfa_enabled": user.mfa_enabled})

    return app


# -- enroll / confirm / disable -----------------------------------------------------------


async def test_enroll_sets_a_pending_secret_without_enabling_mfa(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    async with client(app) as http:
        await http.get("/me", params={})  # unauth GET is fine here, just to prime CSRF
        await http.post("/register", json={"email": "ada@example.com", "password": "hunter2"})
        response = await http.post("/mfa/enroll")
        assert response.status_code == 200

        me = await http.get("/me")
        assert me.json()["mfa_enabled"] is False


async def test_confirm_with_wrong_code_raises_and_does_not_enable(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    async with client(app) as http:
        await http.get("/me")
        await http.post("/register", json={"email": "ada@example.com", "password": "hunter2"})
        await http.post("/mfa/enroll")

        response = await http.post("/mfa/confirm", json={"code": "000000"})
        assert response.status_code == 422

        me = await http.get("/me")
        assert me.json()["mfa_enabled"] is False


async def test_confirm_without_prior_enroll_raises(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    async with client(app) as http:
        await http.get("/me")
        await http.post("/register", json={"email": "ada@example.com", "password": "hunter2"})

        response = await http.post("/mfa/confirm", json={"code": "000000"})
        assert response.status_code == 422


async def test_confirm_with_valid_code_enables_and_returns_recovery_codes(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    async with client(app) as http:
        await http.get("/me")
        await http.post("/register", json={"email": "ada@example.com", "password": "hunter2"})
        enroll_response = await http.post("/mfa/enroll")
        secret = enroll_response.json()["secret"]

        response = await http.post("/mfa/confirm", json={"code": _valid_code(secret)})
        assert response.status_code == 200
        codes = response.json()["recovery_codes"]
        assert len(codes) == 8
        assert len(set(codes)) == 8  # all distinct

        me = await http.get("/me")
        assert me.json()["mfa_enabled"] is True


async def test_disable_clears_enrollment(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    async with client(app) as http:
        await http.get("/me")
        await http.post("/register", json={"email": "ada@example.com", "password": "hunter2"})
        enroll_response = await http.post("/mfa/enroll")
        secret = enroll_response.json()["secret"]
        await http.post("/mfa/confirm", json={"code": _valid_code(secret)})

        response = await http.post("/mfa/disable")
        assert response.status_code == 200

        me = await http.get("/me")
        assert me.json()["mfa_enabled"] is False


# -- recovery codes -----------------------------------------------------------------------


async def test_recovery_code_is_single_use(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    database = app.container.make(Database)
    async with database.session():
        user = MfaUser(email="ada@example.com")
        user.set_password("hunter2")
        await user.save()
        enrollment = await enroll(user, account_name=user.email)
        codes = await confirm(user, _valid_code(enrollment.secret))

        recovery_code = codes[0]
        assert await verify_and_consume(user, recovery_code) is True
        assert await verify_and_consume(user, recovery_code) is False  # already spent


async def test_verify_and_consume_returns_false_when_mfa_not_enabled(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    database = app.container.make(Database)
    async with database.session():
        user = MfaUser(email="ada@example.com")
        user.set_password("hunter2")
        await user.save()
        assert await verify_and_consume(user, "000000") is False


# -- login-time challenge (HTTP end-to-end) ------------------------------------------------


async def _register_enroll_and_confirm(http, email: str, password: str) -> str:
    await http.post("/register", json={"email": email, "password": password})
    enroll_response = await http.post("/mfa/enroll")
    secret = enroll_response.json()["secret"]
    confirm_response = await http.post("/mfa/confirm", json={"code": _valid_code(secret)})
    return secret, confirm_response.json()["recovery_codes"]


async def test_login_requires_a_second_factor_once_mfa_is_enabled(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    async with client(app) as http:
        await http.get("/me")
        await http.post("/register", json={"email": "ada@example.com", "password": "hunter2"})
        enroll_response = await http.post("/mfa/enroll")
        secret = enroll_response.json()["secret"]
        await http.post("/mfa/confirm", json={"code": _valid_code(secret)})

    # A fresh client -- no session cookie -- stands in for a new browser session.
    async with client(app) as http:
        await http.get("/me")  # primes CSRF for this fresh client
        login_response = await http.post("/login", json={"email": "ada@example.com", "password": "hunter2"})
        assert login_response.status_code == 200
        assert login_response.json() == {"mfa_required": True}

        # Not actually logged in yet -- the password check alone isn't enough.
        me_before = await http.get("/me")
        assert me_before.status_code == 401

        challenge_response = await http.post("/mfa/challenge", json={"code": _valid_code(secret)})
        assert challenge_response.status_code == 200

        me_after = await http.get("/me")
        assert me_after.status_code == 200
        assert me_after.json()["email"] == "ada@example.com"


async def test_mfa_challenge_rejects_a_wrong_code_but_preserves_the_pending_state(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    async with client(app) as http:
        await http.get("/me")
        secret, _codes = await _register_enroll_and_confirm(http, "ada@example.com", "hunter2")

    async with client(app) as http:
        await http.get("/me")
        await http.post("/login", json={"email": "ada@example.com", "password": "hunter2"})

        wrong = await http.post("/mfa/challenge", json={"code": "000000"})
        assert wrong.status_code == 401

        # The pending challenge survives the failed attempt -- retry works.
        right = await http.post("/mfa/challenge", json={"code": _valid_code(secret)})
        assert right.status_code == 200


async def test_a_recovery_code_completes_the_login_challenge(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    async with client(app) as http:
        await http.get("/me")
        _secret, codes = await _register_enroll_and_confirm(http, "ada@example.com", "hunter2")

    async with client(app) as http:
        await http.get("/me")
        await http.post("/login", json={"email": "ada@example.com", "password": "hunter2"})

        response = await http.post("/mfa/challenge", json={"code": codes[0]})
        assert response.status_code == 200

        me = await http.get("/me")
        assert me.status_code == 200


async def test_pending_user_id_is_none_with_no_challenge_in_progress(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    async with client(app) as http:
        await http.get("/me")
        response = await http.post("/mfa/challenge", json={"code": "000000"})
        assert response.status_code == 401


async def test_pending_user_id_reflects_the_started_challenge(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    @app.get("/pending")
    async def pending(request):
        return JSONResponse({"pending": pending_user_id(request)})

    async with client(app) as http:
        await http.get("/me")
        _secret, _codes = await _register_enroll_and_confirm(http, "ada@example.com", "hunter2")

    async with client(app) as http:
        await http.get("/me")

        before = await http.get("/pending")
        assert before.json()["pending"] is None

        await http.post("/login", json={"email": "ada@example.com", "password": "hunter2"})

        after = await http.get("/pending")
        assert after.json()["pending"] is not None

"""Tests for zeython.oauth -- the OAuth2/OIDC authorization redirect,
state CSRF protection, code exchange, and per-provider userinfo mapping.
"""

import functools
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from starlette.responses import JSONResponse

import zeython.oauth as oauth_module
from zeython.application import Application
from zeython.auth import AuthServiceProvider, login
from zeython.config import Config
from zeython.db import Model
from zeython.oauth import (
    OAuthProvider,
    OAuthServiceProvider,
    OAuthUser,
    generic_oidc,
    github,
    google,
    microsoft,
    oauth_callback,
    oauth_redirect,
)
from zeython.providers import DatabaseServiceProvider
from zeython.testing import client


class OAuthTestUser(Model):
    __tablename__ = "oauth_test_users"

    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255))


def _mock_transport(handler: Any) -> Any:
    return functools.partial(httpx.AsyncClient, transport=httpx.MockTransport(handler))


# -- Provider builders --------------------------------------------------------------------


def test_google_provider_has_expected_endpoints_and_default_scope() -> None:
    provider = google(client_id="cid", client_secret="secret", redirect_uri="https://app.example/auth/google/callback")
    assert provider.name == "google"
    assert provider.authorize_url == "https://accounts.google.com/o/oauth2/v2/auth"
    assert provider.token_url == "https://oauth2.googleapis.com/token"
    assert provider.userinfo_url == "https://openidconnect.googleapis.com/v1/userinfo"
    assert provider.scope == "openid email profile"


def test_github_provider_has_expected_endpoints_and_default_scope() -> None:
    provider = github(client_id="cid", client_secret="secret", redirect_uri="https://app.example/auth/github/callback")
    assert provider.name == "github"
    assert provider.authorize_url == "https://github.com/login/oauth/authorize"
    assert provider.token_url == "https://github.com/login/oauth/access_token"
    assert provider.scope == "read:user user:email"


def test_microsoft_provider_defaults_to_the_common_tenant() -> None:
    provider = microsoft(client_id="cid", client_secret="secret", redirect_uri="https://app.example/auth/microsoft/callback")
    assert "login.microsoftonline.com/common/oauth2/v2.0/authorize" in provider.authorize_url
    assert provider.userinfo_url == "https://graph.microsoft.com/v1.0/me"


def test_microsoft_provider_accepts_a_specific_tenant() -> None:
    provider = microsoft(
        client_id="cid", client_secret="secret", redirect_uri="https://x", tenant="contoso.onmicrosoft.com"
    )
    assert "login.microsoftonline.com/contoso.onmicrosoft.com/oauth2" in provider.authorize_url


def test_generic_oidc_uses_the_given_endpoints_and_name() -> None:
    provider = generic_oidc(
        name="okta",
        client_id="cid",
        client_secret="secret",
        authorize_url="https://org.okta.com/oauth2/v1/authorize",
        token_url="https://org.okta.com/oauth2/v1/token",
        userinfo_url="https://org.okta.com/oauth2/v1/userinfo",
        redirect_uri="https://app.example/auth/okta/callback",
    )
    assert provider.name == "okta"
    assert provider.authorize_url == "https://org.okta.com/oauth2/v1/authorize"
    assert provider.scope == "openid email profile"


# -- Per-provider userinfo mapping ----------------------------------------------------------


async def test_google_mapper_maps_standard_claims() -> None:
    provider = google(client_id="c", client_secret="s", redirect_uri="https://x")
    data = {"sub": "1234", "email": "ada@example.com", "name": "Ada", "picture": "https://img"}
    async with httpx.AsyncClient() as dummy:
        user = await provider.map_userinfo(data, dummy, "tok")

    assert user == OAuthUser(
        provider="google",
        provider_user_id="1234",
        email="ada@example.com",
        name="Ada",
        avatar_url="https://img",
        access_token="tok",
        raw=data,
    )


async def test_github_mapper_uses_the_public_email_when_present() -> None:
    provider = github(client_id="c", client_secret="s", redirect_uri="https://x")
    data = {"id": 42, "email": "pub@example.com", "login": "adalovelace", "name": "Ada Lovelace", "avatar_url": "https://a"}
    async with httpx.AsyncClient() as dummy:
        user = await provider.map_userinfo(data, dummy, "tok")

    assert user.provider_user_id == "42"
    assert user.email == "pub@example.com"
    assert user.name == "Ada Lovelace"
    assert user.avatar_url == "https://a"


async def test_github_mapper_falls_back_to_the_primary_email_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/user/emails"
        return httpx.Response(
            200,
            json=[
                {"email": "secondary@example.com", "primary": False},
                {"email": "primary@example.com", "primary": True},
            ],
        )

    provider = github(client_id="c", client_secret="s", redirect_uri="https://x")
    data = {"id": 42, "email": None, "login": "adalovelace"}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as fake:
        user = await provider.map_userinfo(data, fake, "tok")

    assert user.email == "primary@example.com"
    assert user.name == "adalovelace"  # no `name` field on the profile -- falls back to the login


async def test_github_mapper_leaves_email_none_if_the_emails_endpoint_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    provider = github(client_id="c", client_secret="s", redirect_uri="https://x")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as fake:
        user = await provider.map_userinfo({"id": 1, "email": None, "login": "x"}, fake, "tok")

    assert user.email is None


async def test_microsoft_mapper_prefers_mail_over_user_principal_name() -> None:
    provider = microsoft(client_id="c", client_secret="s", redirect_uri="https://x")
    data = {"id": "abc", "mail": "ada@contoso.com", "userPrincipalName": "ada@contoso.onmicrosoft.com", "displayName": "Ada"}
    async with httpx.AsyncClient() as dummy:
        user = await provider.map_userinfo(data, dummy, "tok")

    assert user.email == "ada@contoso.com"
    assert user.name == "Ada"
    assert user.avatar_url is None


async def test_microsoft_mapper_falls_back_to_user_principal_name() -> None:
    provider = microsoft(client_id="c", client_secret="s", redirect_uri="https://x")
    data = {"id": "abc", "mail": None, "userPrincipalName": "ada@contoso.onmicrosoft.com", "displayName": "Ada"}
    async with httpx.AsyncClient() as dummy:
        user = await provider.map_userinfo(data, dummy, "tok")

    assert user.email == "ada@contoso.onmicrosoft.com"


async def test_generic_oidc_mapper_uses_standard_claims_and_the_configured_name() -> None:
    provider = generic_oidc(
        name="okta",
        client_id="c",
        client_secret="s",
        authorize_url="https://x/authorize",
        token_url="https://x/token",
        userinfo_url="https://x/userinfo",
        redirect_uri="https://x/callback",
    )
    data = {"sub": "u1", "email": "a@b.com", "name": "A B", "picture": "https://p"}
    async with httpx.AsyncClient() as dummy:
        user = await provider.map_userinfo(data, dummy, "tok")

    assert user.provider == "okta"
    assert user.provider_user_id == "u1"
    assert user.email == "a@b.com"


# -- OAuthManager / OAuthServiceProvider, via a real request round-trip ---------------------


async def _make_app(tmp_path: Path, *, providers: list[OAuthProvider]) -> Application:
    (tmp_path / ".env").write_text(
        "APP_SECRET_KEY=test-only-secret-not-for-production\nDATABASE_URL=sqlite+aiosqlite:///:memory:\n"
    )
    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)
    app.register(AuthServiceProvider(app, user_model=OAuthTestUser))
    app.register(OAuthServiceProvider(app, providers=providers))

    from zeython.db.session import Database

    database = app.container.make(Database)
    async with database.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)

    @app.get("/auth/{provider}/redirect")
    async def redirect(request):
        return oauth_redirect(request, request.path_params["provider"])

    @app.get("/auth/{provider}/callback")
    async def callback(request):
        identity = await oauth_callback(request, request.path_params["provider"])
        user = await OAuthTestUser.first_where(email=identity.email)
        if user is None:
            user = await OAuthTestUser.create(email=identity.email, name=identity.name or identity.email)
        login(request, user)
        return JSONResponse({"id": user.id, "email": user.email, "provider": identity.provider})

    return app


def _mock_provider(**overrides: Any) -> OAuthProvider:
    base = google(client_id="cid", client_secret="secret", redirect_uri="https://app.example/auth/google/callback")
    return OAuthProvider(
        name=overrides.pop("name", base.name),
        client_id=overrides.pop("client_id", base.client_id),
        client_secret=overrides.pop("client_secret", base.client_secret),
        authorize_url=overrides.pop("authorize_url", base.authorize_url),
        token_url=overrides.pop("token_url", "https://mock.example/token"),
        userinfo_url=overrides.pop("userinfo_url", "https://mock.example/userinfo"),
        redirect_uri=overrides.pop("redirect_uri", base.redirect_uri),
        scope=overrides.pop("scope", base.scope),
        map_userinfo=overrides.pop("map_userinfo", base.map_userinfo),
    )


async def test_redirect_builds_the_authorize_url_and_stores_state(tmp_path: Path) -> None:
    app = await _make_app(tmp_path, providers=[_mock_provider()])

    async with client(app) as http:
        response = await http.get("/auth/google/redirect")

    assert response.status_code in (302, 303, 307, 308)
    location = urlparse(response.headers["location"])
    assert location.netloc == "accounts.google.com"
    query = parse_qs(location.query)
    assert query["client_id"] == ["cid"]
    assert query["redirect_uri"] == ["https://app.example/auth/google/callback"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid email profile"]
    assert len(query["state"][0]) > 20


async def test_redirect_generates_a_fresh_state_each_time(tmp_path: Path) -> None:
    app = await _make_app(tmp_path, providers=[_mock_provider()])

    async with client(app) as http:
        first = await http.get("/auth/google/redirect")
        second = await http.get("/auth/google/redirect")

    state_1 = parse_qs(urlparse(first.headers["location"]).query)["state"][0]
    state_2 = parse_qs(urlparse(second.headers["location"]).query)["state"][0]
    assert state_1 != state_2


async def test_redirect_to_an_unknown_provider_is_not_found(tmp_path: Path) -> None:
    app = await _make_app(tmp_path, providers=[_mock_provider()])

    async with client(app) as http:
        response = await http.get("/auth/nonexistent/redirect")

    assert response.status_code == 404


async def test_callback_to_an_unknown_provider_is_not_found(tmp_path: Path) -> None:
    app = await _make_app(tmp_path, providers=[_mock_provider()])

    async with client(app) as http:
        response = await http.get("/auth/nonexistent/callback", params={"code": "x", "state": "y"})

    assert response.status_code == 404


async def test_callback_without_ever_visiting_redirect_is_rejected(tmp_path: Path) -> None:
    app = await _make_app(tmp_path, providers=[_mock_provider()])

    async with client(app) as http:
        response = await http.get("/auth/google/callback", params={"code": "abc", "state": "whatever"})

    assert response.status_code == 403


async def test_callback_with_a_mismatched_state_is_rejected(tmp_path: Path) -> None:
    app = await _make_app(tmp_path, providers=[_mock_provider()])

    async with client(app) as http:
        await http.get("/auth/google/redirect")
        response = await http.get("/auth/google/callback", params={"code": "abc", "state": "not-the-real-state"})

    assert response.status_code == 403


async def test_callback_with_a_different_length_state_is_rejected(tmp_path: Path) -> None:
    # state comparison uses secrets.compare_digest() rather than `==` (the
    # same constant-time check zeython.csrf's own token comparison uses)
    # so a network observer can't time the comparison to help brute-force
    # a state value -- a mismatched *length* is the one input shape a
    # naive constant-time comparison could mishandle, so it's worth
    # covering on its own rather than trusting the general mismatch case.
    app = await _make_app(tmp_path, providers=[_mock_provider()])

    async with client(app) as http:
        await http.get("/auth/google/redirect")
        response = await http.get("/auth/google/callback", params={"code": "abc", "state": "short"})

    assert response.status_code == 403


async def test_callback_without_a_code_is_a_bad_request(tmp_path: Path) -> None:
    app = await _make_app(tmp_path, providers=[_mock_provider()])

    async with client(app) as http:
        redirected = await http.get("/auth/google/redirect")
        state = parse_qs(urlparse(redirected.headers["location"]).query)["state"][0]
        response = await http.get(
            "/auth/google/callback", params={"state": state, "error": "access_denied", "error_description": "denied"}
        )

    assert response.status_code == 400


async def test_callback_completes_login_with_a_valid_state_and_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            assert request.method == "POST"
            return httpx.Response(200, json={"access_token": "tok-123"})
        if request.url.path == "/userinfo":
            assert request.headers["Authorization"] == "Bearer tok-123"
            return httpx.Response(
                200, json={"sub": "g-1", "email": "ada@example.com", "name": "Ada", "picture": "https://img"}
            )
        raise AssertionError(f"unexpected request to {request.url}")

    monkeypatch.setattr(oauth_module.httpx, "AsyncClient", _mock_transport(handler))

    provider = _mock_provider(token_url="https://mock.example/token", userinfo_url="https://mock.example/userinfo")
    app = await _make_app(tmp_path, providers=[provider])

    async with client(app) as http:
        redirected = await http.get("/auth/google/redirect")
        state = parse_qs(urlparse(redirected.headers["location"]).query)["state"][0]
        response = await http.get("/auth/google/callback", params={"code": "authcode", "state": state})

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "ada@example.com"
    assert body["provider"] == "google"


async def test_callback_state_cannot_be_replayed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "tok-123"})
        return httpx.Response(200, json={"sub": "g-1", "email": "ada@example.com"})

    monkeypatch.setattr(oauth_module.httpx, "AsyncClient", _mock_transport(handler))

    provider = _mock_provider(token_url="https://mock.example/token", userinfo_url="https://mock.example/userinfo")
    app = await _make_app(tmp_path, providers=[provider])

    async with client(app) as http:
        redirected = await http.get("/auth/google/redirect")
        state = parse_qs(urlparse(redirected.headers["location"]).query)["state"][0]
        first = await http.get("/auth/google/callback", params={"code": "authcode", "state": state})
        second = await http.get("/auth/google/callback", params={"code": "authcode", "state": state})

    assert first.status_code == 200
    assert second.status_code == 403


async def test_a_second_login_with_the_same_email_reuses_the_existing_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "tok-123"})
        return httpx.Response(200, json={"sub": "g-1", "email": "ada@example.com", "name": "Ada"})

    monkeypatch.setattr(oauth_module.httpx, "AsyncClient", _mock_transport(handler))

    provider = _mock_provider(token_url="https://mock.example/token", userinfo_url="https://mock.example/userinfo")
    app = await _make_app(tmp_path, providers=[provider])

    async with client(app) as http:
        redirected = await http.get("/auth/google/redirect")
        state = parse_qs(urlparse(redirected.headers["location"]).query)["state"][0]
        first = await http.get("/auth/google/callback", params={"code": "code-1", "state": state})

        redirected_again = await http.get("/auth/google/redirect")
        state_2 = parse_qs(urlparse(redirected_again.headers["location"]).query)["state"][0]
        second = await http.get("/auth/google/callback", params={"code": "code-2", "state": state_2})

    assert first.json()["id"] == second.json()["id"]


async def test_token_exchange_without_an_access_token_is_a_bad_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        oauth_module.httpx, "AsyncClient", _mock_transport(lambda request: httpx.Response(200, json={}))
    )

    provider = _mock_provider(token_url="https://mock.example/token", userinfo_url="https://mock.example/userinfo")
    app = await _make_app(tmp_path, providers=[provider])

    async with client(app) as http:
        redirected = await http.get("/auth/google/redirect")
        state = parse_qs(urlparse(redirected.headers["location"]).query)["state"][0]
        response = await http.get("/auth/google/callback", params={"code": "authcode", "state": state})

    assert response.status_code == 400

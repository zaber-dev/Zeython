"""OAuth2 / OIDC login: "Sign in with Google/GitHub/Microsoft/your own IdP",
without your app ever seeing a password for that account.

Handles the protocol -- building the authorization redirect, the
CSRF-protected ``state`` round-trip, exchanging the authorization code for
an access token, and fetching + normalizing the provider's profile info
into an :class:`OAuthUser` -- and stops there: like Laravel Socialite,
this module hands you an identity, not an opinion about how your ``User``
model is structured. Your callback route decides how to find-or-create a
local user from it (see docs/oauth.md for the two-line version -- find by
email, create if missing, then :func:`zeython.auth.login`).

Built for confidential (server-side) clients only -- the client secret
lives in your app's own configuration, never shipped to a browser -- so
there's no PKCE dance here; that exists to protect *public* clients (an
SPA or mobile app that can't keep a secret), which this isn't. The
`state` parameter is the CSRF protection that does apply here, and it's
mandatory: a random token stored server-side in the session before the
redirect, and checked (then discarded, so it can't be replayed) when the
provider calls back.

Every provider is reached through its userinfo endpoint (OAuth2), not by
decoding an OIDC id_token -- avoids needing a JWT/JWKS verification
dependency for what the userinfo endpoint already gives you over an
authenticated HTTPS request. Ships builders for Google, GitHub, and
Microsoft (Azure AD), plus :func:`generic_oidc` for any standards-compliant
OIDC provider (Okta, Auth0, Keycloak, your own IdP) that exposes the usual
``sub``/``email``/``name``/``picture`` claims.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx
from starlette.requests import Request
from starlette.responses import RedirectResponse

from zeython.exceptions import BadRequestException, ForbiddenException, NotFoundException
from zeython.providers import ServiceProvider

DEFAULT_TIMEOUT = 10.0
_STATE_SESSION_PREFIX = "oauth_state_"


@dataclass(frozen=True)
class OAuthUser:
    """The identity :meth:`OAuthManager.handle_callback` hands back --
    normalized the same way regardless of which provider it came from.
    ``email`` is ``None`` if the provider didn't share one (GitHub, with a
    private email and no ``user:email`` scope granted); decide for
    yourself whether that's acceptable for your app. ``raw`` is the
    provider's own userinfo response, for anything not already surfaced.
    """

    provider: str
    provider_user_id: str
    email: str | None
    name: str | None
    avatar_url: str | None
    access_token: str
    raw: dict[str, Any] = field(default_factory=dict)


UserInfoMapper = Callable[[dict[str, Any], httpx.AsyncClient, str], Awaitable[OAuthUser]]


@dataclass(frozen=True)
class OAuthProvider:
    """One configured provider -- built by :func:`google`, :func:`github`,
    :func:`microsoft`, or :func:`generic_oidc` rather than constructed
    directly in ordinary use. ``redirect_uri`` must exactly match what's
    registered in the provider's own console -- it's never derived from
    the incoming request (that would let a spoofed ``Host`` header send
    the authorization code somewhere else).
    """

    name: str
    client_id: str
    client_secret: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    redirect_uri: str
    scope: str
    map_userinfo: UserInfoMapper


def _standard_claims_mapper(provider_name: str) -> UserInfoMapper:
    async def _map(data: dict[str, Any], client: httpx.AsyncClient, access_token: str) -> OAuthUser:
        return OAuthUser(
            provider=provider_name,
            provider_user_id=str(data.get("sub", data.get("id", ""))),
            email=data.get("email"),
            name=data.get("name"),
            avatar_url=data.get("picture"),
            access_token=access_token,
            raw=data,
        )

    return _map


async def _map_github_userinfo(data: dict[str, Any], client: httpx.AsyncClient, access_token: str) -> OAuthUser:
    email = data.get("email")
    if not email:
        # A private email with no public one set doesn't come back from
        # /user at all, even with the user:email scope granted -- it's
        # only visible through this separate, scope-gated endpoint.
        response = await client.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
        )
        if response.status_code == 200:
            for entry in response.json():
                if entry.get("primary"):
                    email = entry.get("email")
                    break
    return OAuthUser(
        provider="github",
        provider_user_id=str(data.get("id", "")),
        email=email,
        name=data.get("name") or data.get("login"),
        avatar_url=data.get("avatar_url"),
        access_token=access_token,
        raw=data,
    )


async def _map_microsoft_userinfo(data: dict[str, Any], client: httpx.AsyncClient, access_token: str) -> OAuthUser:
    return OAuthUser(
        provider="microsoft",
        provider_user_id=str(data.get("id", "")),
        email=data.get("mail") or data.get("userPrincipalName"),
        name=data.get("displayName"),
        avatar_url=None,  # Graph's photo is a separate binary endpoint, not a URL in this response.
        access_token=access_token,
        raw=data,
    )


def google(*, client_id: str, client_secret: str, redirect_uri: str, scope: str = "openid email profile") -> OAuthProvider:
    """A `Google Cloud Console <https://console.cloud.google.com/apis/credentials>`_
    OAuth 2.0 Client ID's credentials, wired up to Google's own endpoints.
    """
    return OAuthProvider(
        name="google",
        client_id=client_id,
        client_secret=client_secret,
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
        redirect_uri=redirect_uri,
        scope=scope,
        map_userinfo=_standard_claims_mapper("google"),
    )


def github(*, client_id: str, client_secret: str, redirect_uri: str, scope: str = "read:user user:email") -> OAuthProvider:
    """A GitHub OAuth App's (or GitHub App's) client credentials --
    see `Settings > Developer settings <https://github.com/settings/developers>`_.
    """
    return OAuthProvider(
        name="github",
        client_id=client_id,
        client_secret=client_secret,
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        userinfo_url="https://api.github.com/user",
        redirect_uri=redirect_uri,
        scope=scope,
        map_userinfo=_map_github_userinfo,
    )


def microsoft(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    tenant: str = "common",
    scope: str = "openid email profile User.Read",
) -> OAuthProvider:
    """An Azure AD app registration's credentials. ``tenant`` scopes who can
    sign in: ``"common"`` (personal + any work/school account, the
    default), ``"organizations"`` (work/school accounts only), or a
    specific tenant ID/domain to restrict sign-in to one organization --
    see `Microsoft identity platform docs
    <https://learn.microsoft.com/en-us/azure/active-directory/develop/v2-protocols-oidc>`_.
    """
    return OAuthProvider(
        name="microsoft",
        client_id=client_id,
        client_secret=client_secret,
        authorize_url=f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        token_url=f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        userinfo_url="https://graph.microsoft.com/v1.0/me",
        redirect_uri=redirect_uri,
        scope=scope,
        map_userinfo=_map_microsoft_userinfo,
    )


def generic_oidc(
    *,
    name: str,
    client_id: str,
    client_secret: str,
    authorize_url: str,
    token_url: str,
    userinfo_url: str,
    redirect_uri: str,
    scope: str = "openid email profile",
) -> OAuthProvider:
    """Any standards-compliant OIDC provider exposing the usual
    ``sub``/``email``/``name``/``picture`` userinfo claims -- Okta, Auth0,
    Keycloak, or an enterprise customer's own identity provider. Look up
    ``authorize_url``/``token_url``/``userinfo_url`` from the provider's
    ``/.well-known/openid-configuration`` discovery document (fetched once,
    by hand, when you set this up -- not at request time).
    """
    return OAuthProvider(
        name=name,
        client_id=client_id,
        client_secret=client_secret,
        authorize_url=authorize_url,
        token_url=token_url,
        userinfo_url=userinfo_url,
        redirect_uri=redirect_uri,
        scope=scope,
        map_userinfo=_standard_claims_mapper(name),
    )


class OAuthManager:
    """Builds the authorization redirect and completes the callback for
    every provider registered with it. Bound in the container by
    :class:`OAuthServiceProvider`.
    """

    def __init__(self, providers: dict[str, OAuthProvider], *, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.providers = providers
        self.timeout = timeout

    def _provider(self, name: str) -> OAuthProvider:
        provider = self.providers.get(name)
        if provider is None:
            raise NotFoundException(f"Unknown OAuth provider: {name!r}.")
        return provider

    def redirect_url(self, request: Request, provider_name: str) -> str:
        """The URL to send the browser to at ``provider_name`` -- stashes a
        fresh CSRF ``state`` token in the session first, checked by
        :meth:`handle_callback` when the provider redirects back.
        """
        provider = self._provider(provider_name)
        state = secrets.token_urlsafe(32)
        request.session[f"{_STATE_SESSION_PREFIX}{provider_name}"] = state
        params = {
            "client_id": provider.client_id,
            "redirect_uri": provider.redirect_uri,
            "response_type": "code",
            "scope": provider.scope,
            "state": state,
        }
        return f"{provider.authorize_url}?{urlencode(params)}"

    async def handle_callback(self, request: Request, provider_name: str) -> OAuthUser:
        """Validate the callback's ``state``, exchange its ``code`` for an
        access token, fetch the provider's userinfo, and return it
        normalized. Raises :class:`~zeython.exceptions.ForbiddenException`
        on a missing/mismatched ``state`` (CSRF, or a stale/replayed
        callback -- state is popped from the session on first use, so a
        second attempt with the same one fails the same way) and
        :class:`~zeython.exceptions.BadRequestException` if the provider
        didn't come back with an authorization code (the user denied
        consent, or something else went wrong at the provider).
        """
        provider = self._provider(provider_name)
        session_key = f"{_STATE_SESSION_PREFIX}{provider_name}"
        expected_state = request.session.pop(session_key, None)
        received_state = request.query_params.get("state")
        if not expected_state or not received_state or expected_state != received_state:
            raise ForbiddenException(
                "Invalid or expired OAuth state -- possible CSRF attempt, or the login flow took too long."
            )

        code = request.query_params.get("code")
        if not code:
            error = request.query_params.get("error_description") or request.query_params.get("error")
            raise BadRequestException(f"OAuth provider returned no authorization code ({error or 'unknown reason'}).")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            token_response = await client.post(
                provider.token_url,
                data={
                    "client_id": provider.client_id,
                    "client_secret": provider.client_secret,
                    "code": code,
                    "redirect_uri": provider.redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            access_token = token_response.json().get("access_token")
            if not access_token:
                raise BadRequestException("OAuth token exchange did not return an access token.")

            userinfo_response = await client.get(
                provider.userinfo_url, headers={"Authorization": f"Bearer {access_token}"}
            )
            userinfo_response.raise_for_status()

            return await provider.map_userinfo(userinfo_response.json(), client, access_token)


def oauth_redirect(request: Request, provider: str) -> RedirectResponse:
    """Send the browser to ``provider``'s login page -- call this from your
    ``GET /auth/{provider}/redirect`` route::

        async def oauth_redirect(self, request):
            return oauth_redirect(request, request.path_params["provider"])
    """
    manager: OAuthManager = request.app.state.container.make(OAuthManager)
    return RedirectResponse(manager.redirect_url(request, provider))


async def oauth_callback(request: Request, provider: str) -> OAuthUser:
    """Complete the login for ``provider`` and return the resulting
    identity -- call this from your ``GET /auth/{provider}/callback``
    route, then find-or-create your own ``User`` from it and call
    :func:`zeython.auth.login`::

        async def oauth_callback(self, request):
            identity = await oauth_callback(request, request.path_params["provider"])
            user = await User.first_where(email=identity.email)
            if user is None:
                user = await User.create(email=identity.email, name=identity.name)
            login(request, user)
            return JSONResponse(user.to_dict())
    """
    manager: OAuthManager = request.app.state.container.make(OAuthManager)
    return await manager.handle_callback(request, provider)


class OAuthServiceProvider(ServiceProvider):
    """Binds an :class:`OAuthManager` configured with the given providers::

        app.register(OAuthServiceProvider(app, providers=[
            google(client_id=..., client_secret=..., redirect_uri="https://app.example.com/auth/google/callback"),
            github(client_id=..., client_secret=..., redirect_uri="https://app.example.com/auth/github/callback"),
        ]))

    Needs ``AuthServiceProvider`` registered too (for the session
    ``state`` lives in, and for :func:`zeython.auth.login` your callback
    route calls) -- registration order between the two doesn't matter.
    See docs/oauth.md.
    """

    def __init__(self, app: Any, *, providers: list[OAuthProvider], timeout: float = DEFAULT_TIMEOUT) -> None:
        super().__init__(app)
        self.providers = providers
        self.timeout = timeout

    def register(self) -> None:
        manager = OAuthManager({provider.name: provider for provider in self.providers}, timeout=self.timeout)
        self.container.singleton(OAuthManager, lambda: manager)


__all__ = [
    "OAuthManager",
    "OAuthProvider",
    "OAuthServiceProvider",
    "OAuthUser",
    "generic_oidc",
    "github",
    "google",
    "microsoft",
    "oauth_callback",
    "oauth_redirect",
]

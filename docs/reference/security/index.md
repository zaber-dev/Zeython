# Security

Session-based web auth, OAuth2/OIDC login, SAML SSO, two-factor auth (TOTP), API token auth, RBAC-style authorization, CSRF protection, security response headers, password hashing, and multi-tenancy.

## auth

Session-based authentication.

A deliberately small design: one signed cookie (Starlette's `SessionMiddleware`, keyed off `APP_SECRET_KEY`) holding the authenticated user's ID, CSRF protection (:mod:`zeython.csrf`) that comes with it automatically -- cookie auth without it is forgeable from any other site the user's browser happens to have open -- an :class:`AuthManager` that knows how to look up and verify credentials against whichever model you designate as your user model, and a handful of functions (`login`, `logout`, `current_user`, `require_auth`) that operate on a request.

No server-side session store, no token issuance/rotation — that's a deliberate scope boundary, not an oversight. Token-based auth (for an API consumed by a separate frontend) is a reasonable future addition; it does not belong in the same code path as cookie sessions.

### Authenticatable

Mixin adding password helpers to a user model.

The concrete model declares its own password column — conventionally `password_hash: Mapped[str] = mapped_column(String(255))` — this mixin only adds behavior on top of it::

```text
class User(Model, Authenticatable):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
```

### AuthManager

```python
AuthManager(
    user_model: type[Model],
    *,
    username_field: str = "email",
    password_field: str = "password_hash",
)
```

Looks up and verifies users against a configured model and field names.

Source code in `src/zeython/auth.py`

```python
def __init__(
    self,
    user_model: type[Model],
    *,
    username_field: str = "email",
    password_field: str = "password_hash",
) -> None:
    self.user_model = user_model
    self.username_field = username_field
    self.password_field = password_field
```

#### attempt

```python
attempt(username: str, password: str) -> Model | None
```

Verify credentials, returning the user on success or `None` on failure.

Source code in `src/zeython/auth.py`

```python
async def attempt(self, username: str, password: str) -> Model | None:
    """Verify credentials, returning the user on success or ``None`` on failure."""
    if not username or not password:
        return None

    filters: dict[str, Any] = {self.username_field: username}
    user = await self.user_model.first_where(**filters)
    if user is None:
        # Still pay PBKDF2's real cost against a hash nothing can
        # ever match, rather than returning immediately -- an
        # unknown username would otherwise respond measurably faster
        # than a known one with a wrong password (hashing is
        # deliberately slow; a database miss is not), letting an
        # attacker enumerate valid usernames purely from response
        # timing without a single successful login.
        verify_password(password, _dummy_password_hash())
        return None

    hashed = getattr(user, self.password_field, None)
    if not hashed or not verify_password(password, hashed):
        return None

    return user
```

### AuthServiceProvider

```python
AuthServiceProvider(
    app: Application,
    user_model: type[Model],
    *,
    username_field: str = "email",
    password_field: str = "password_hash",
)
```

Bases: `ServiceProvider`

Wires up session-backed authentication for a chosen user model.

Adds Starlette's signed-cookie `SessionMiddleware` (keyed off `APP_SECRET_KEY`, so that must be set), CSRF protection (:class:`~zeython.csrf.CsrfMiddleware` -- see docs/csrf.md), and binds an :class:`AuthManager` into the container::

```text
app.register(AuthServiceProvider(app, user_model=User))
```

Configurable via `.env`: `SESSION_COOKIE_NAME`, `SESSION_MAX_AGE` (seconds, default 14 days), `SESSION_HTTPS_ONLY` (default `false`; set `true` once you're serving over HTTPS). `CSRF_ENABLED` (default `true`), `CSRF_COOKIE_NAME`, `CSRF_HEADER_NAME` configure the CSRF protection that comes with it -- turning it off is rarely the right call, since it's exactly what makes cookie-based auth safe to use from a browser.

Source code in `src/zeython/auth.py`

```python
def __init__(
    self,
    app: Application,
    user_model: type[Model],
    *,
    username_field: str = "email",
    password_field: str = "password_hash",
) -> None:
    super().__init__(app)
    self.user_model = user_model
    self.username_field = username_field
    self.password_field = password_field
```

### hash_password

```python
hash_password(
    password: str, *, iterations: int = _DEFAULT_ITERATIONS
) -> str
```

Hash `password` for storage.

Returns a self-describing string: `pbkdf2_sha256$<iterations>$<salt>$<hash>` (salt and hash base64-encoded), so the iteration count can be raised later without invalidating hashes already in the database.

Source code in `src/zeython/hashing.py`

```python
def hash_password(password: str, *, iterations: int = _DEFAULT_ITERATIONS) -> str:
    """Hash ``password`` for storage.

    Returns a self-describing string: ``pbkdf2_sha256$<iterations>$<salt>$<hash>``
    (salt and hash base64-encoded), so the iteration count can be raised later
    without invalidating hashes already in the database.
    """
    if not password:
        raise ValueError("password must not be empty")

    salt = os.urandom(_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(
        [
            _ALGORITHM,
            str(iterations),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(derived).decode("ascii"),
        ]
    )
```

### verify_password

```python
verify_password(password: str, hashed: str) -> bool
```

Constant-time check of `password` against a hash from :func:`hash_password`.

Source code in `src/zeython/hashing.py`

```python
def verify_password(password: str, hashed: str) -> bool:
    """Constant-time check of ``password`` against a hash from :func:`hash_password`."""
    if not password or not hashed:
        return False

    parts = hashed.split("$")
    if len(parts) != 4:
        return False
    algorithm, iterations_raw, salt_b64, hash_b64 = parts

    if algorithm != _ALGORITHM:
        return False

    try:
        iterations = int(iterations_raw)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False

    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(derived, expected)
```

### login

```python
login(request: Request, user: Model) -> None
```

Mark `user` as authenticated for the current session.

Source code in `src/zeython/auth.py`

```python
def login(request: Request, user: Model) -> None:
    """Mark ``user`` as authenticated for the current session."""
    request.session[_SESSION_KEY] = user.id
```

### logout

```python
logout(request: Request) -> None
```

Clear authentication from the current session.

Source code in `src/zeython/auth.py`

```python
def logout(request: Request) -> None:
    """Clear authentication from the current session."""
    request.session.pop(_SESSION_KEY, None)
```

### current_user

```python
current_user(request: Request) -> Model | None
```

The authenticated user for this request, or `None` if not logged in.

Source code in `src/zeython/auth.py`

```python
async def current_user(request: Request) -> Model | None:
    """The authenticated user for this request, or ``None`` if not logged in."""
    user_id = request.session.get(_SESSION_KEY)
    if user_id is None:
        return None

    manager: AuthManager = request.app.state.container.make(AuthManager)
    return await manager.user_model.find(user_id)
```

### require_auth

```python
require_auth(request: Request) -> Model
```

Return the authenticated user, or raise `UnauthorizedException`.

Call this at the top of any handler that requires a logged-in user::

```text
async def show(self, request):
    user = await require_auth(request)
```

Source code in `src/zeython/auth.py`

```python
async def require_auth(request: Request) -> Model:
    """Return the authenticated user, or raise ``UnauthorizedException``.

    Call this at the top of any handler that requires a logged-in user::

        async def show(self, request):
            user = await require_auth(request)
    """
    user = await current_user(request)
    if user is None:
        raise UnauthorizedException("Authentication required.")
    return user
```

## oauth

OAuth2 / OIDC login: "Sign in with Google/GitHub/Microsoft/your own IdP", without your app ever seeing a password for that account.

Handles the protocol -- building the authorization redirect, the CSRF-protected `state` round-trip, exchanging the authorization code for an access token, and fetching + normalizing the provider's profile info into an :class:`OAuthUser` -- and stops there: like Laravel Socialite, this module hands you an identity, not an opinion about how your `User` model is structured. Your callback route decides how to find-or-create a local user from it (see docs/oauth.md for the two-line version -- find by email, create if missing, then :func:`zeython.auth.login`).

Built for confidential (server-side) clients only -- the client secret lives in your app's own configuration, never shipped to a browser -- so there's no PKCE dance here; that exists to protect *public* clients (an SPA or mobile app that can't keep a secret), which this isn't. The `state` parameter is the CSRF protection that does apply here, and it's mandatory: a random token stored server-side in the session before the redirect, and checked (then discarded, so it can't be replayed) when the provider calls back.

Every provider is reached through its userinfo endpoint (OAuth2), not by decoding an OIDC id_token -- avoids needing a JWT/JWKS verification dependency for what the userinfo endpoint already gives you over an authenticated HTTPS request. Ships builders for Google, GitHub, and Microsoft (Azure AD), plus :func:`generic_oidc` for any standards-compliant OIDC provider (Okta, Auth0, Keycloak, your own IdP) that exposes the usual `sub`/`email`/`name`/`picture` claims.

### OAuthUser

```python
OAuthUser(
    provider: str,
    provider_user_id: str,
    email: str | None,
    name: str | None,
    avatar_url: str | None,
    access_token: str,
    raw: dict[str, Any] = dict(),
)
```

The identity :meth:`OAuthManager.handle_callback` hands back -- normalized the same way regardless of which provider it came from. `email` is `None` if the provider didn't share one (GitHub, with a private email and no `user:email` scope granted); decide for yourself whether that's acceptable for your app. `raw` is the provider's own userinfo response, for anything not already surfaced.

### OAuthProvider

```python
OAuthProvider(
    name: str,
    client_id: str,
    client_secret: str,
    authorize_url: str,
    token_url: str,
    userinfo_url: str,
    redirect_uri: str,
    scope: str,
    map_userinfo: UserInfoMapper,
)
```

One configured provider -- built by :func:`google`, :func:`github`, :func:`microsoft`, or :func:`generic_oidc` rather than constructed directly in ordinary use. `redirect_uri` must exactly match what's registered in the provider's own console -- it's never derived from the incoming request (that would let a spoofed `Host` header send the authorization code somewhere else).

### OAuthManager

```python
OAuthManager(
    providers: dict[str, OAuthProvider],
    *,
    timeout: float = DEFAULT_TIMEOUT,
)
```

Builds the authorization redirect and completes the callback for every provider registered with it. Bound in the container by :class:`OAuthServiceProvider`.

Source code in `src/zeython/oauth.py`

```python
def __init__(self, providers: dict[str, OAuthProvider], *, timeout: float = DEFAULT_TIMEOUT) -> None:
    self.providers = providers
    self.timeout = timeout
```

#### redirect_url

```python
redirect_url(request: Request, provider_name: str) -> str
```

The URL to send the browser to at `provider_name` -- stashes a fresh CSRF `state` token in the session first, checked by :meth:`handle_callback` when the provider redirects back.

Source code in `src/zeython/oauth.py`

```python
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
```

#### handle_callback

```python
handle_callback(
    request: Request, provider_name: str
) -> OAuthUser
```

Validate the callback's `state`, exchange its `code` for an access token, fetch the provider's userinfo, and return it normalized. Raises :class:`~zeython.exceptions.ForbiddenException` on a missing/mismatched `state` (CSRF, or a stale/replayed callback -- state is popped from the session on first use, so a second attempt with the same one fails the same way) and :class:`~zeython.exceptions.BadRequestException` if the provider didn't come back with an authorization code (the user denied consent, or something else went wrong at the provider).

Source code in `src/zeython/oauth.py`

```python
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
    if (
        not expected_state
        or not received_state
        or not secrets.compare_digest(expected_state, received_state)
    ):
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
```

### OAuthServiceProvider

```python
OAuthServiceProvider(
    app: Any,
    *,
    providers: list[OAuthProvider],
    timeout: float = DEFAULT_TIMEOUT,
)
```

Bases: `ServiceProvider`

Binds an :class:`OAuthManager` configured with the given providers::

```text
app.register(OAuthServiceProvider(app, providers=[
    google(client_id=..., client_secret=..., redirect_uri="https://app.example.com/auth/google/callback"),
    github(client_id=..., client_secret=..., redirect_uri="https://app.example.com/auth/github/callback"),
]))
```

Needs `AuthServiceProvider` registered too (for the session `state` lives in, and for :func:`zeython.auth.login` your callback route calls) -- registration order between the two doesn't matter. See docs/oauth.md.

Source code in `src/zeython/oauth.py`

```python
def __init__(self, app: Any, *, providers: list[OAuthProvider], timeout: float = DEFAULT_TIMEOUT) -> None:
    super().__init__(app)
    self.providers = providers
    self.timeout = timeout
```

### google

```python
google(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    scope: str = "openid email profile",
) -> OAuthProvider
```

A `Google Cloud Console <https://console.cloud.google.com/apis/credentials>`\_ OAuth 2.0 Client ID's credentials, wired up to Google's own endpoints.

Source code in `src/zeython/oauth.py`

```python
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
```

### github

```python
github(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    scope: str = "read:user user:email",
) -> OAuthProvider
```

A GitHub OAuth App's (or GitHub App's) client credentials -- see `Settings > Developer settings <https://github.com/settings/developers>`\_.

Source code in `src/zeython/oauth.py`

```python
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
```

### microsoft

```python
microsoft(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    tenant: str = "common",
    scope: str = "openid email profile User.Read",
) -> OAuthProvider
```

An Azure AD app registration's credentials. `tenant` scopes who can sign in: `"common"` (personal + any work/school account, the default), `"organizations"` (work/school accounts only), or a specific tenant ID/domain to restrict sign-in to one organization -- see `Microsoft identity platform docs <https://learn.microsoft.com/en-us/azure/active-directory/develop/v2-protocols-oidc>`\_.

Source code in `src/zeython/oauth.py`

```python
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
```

### generic_oidc

```python
generic_oidc(
    *,
    name: str,
    client_id: str,
    client_secret: str,
    authorize_url: str,
    token_url: str,
    userinfo_url: str,
    redirect_uri: str,
    scope: str = "openid email profile",
) -> OAuthProvider
```

Any standards-compliant OIDC provider exposing the usual `sub`/`email`/`name`/`picture` userinfo claims -- Okta, Auth0, Keycloak, or an enterprise customer's own identity provider. Look up `authorize_url`/`token_url`/`userinfo_url` from the provider's `/.well-known/openid-configuration` discovery document (fetched once, by hand, when you set this up -- not at request time).

Source code in `src/zeython/oauth.py`

```python
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
```

### oauth_redirect

```python
oauth_redirect(
    request: Request, provider: str
) -> RedirectResponse
```

Send the browser to `provider`'s login page -- call this from your `GET /auth/{provider}/redirect` route::

```text
async def oauth_redirect(self, request):
    return oauth_redirect(request, request.path_params["provider"])
```

Source code in `src/zeython/oauth.py`

```python
def oauth_redirect(request: Request, provider: str) -> RedirectResponse:
    """Send the browser to ``provider``'s login page -- call this from your
    ``GET /auth/{provider}/redirect`` route::

        async def oauth_redirect(self, request):
            return oauth_redirect(request, request.path_params["provider"])
    """
    manager: OAuthManager = request.app.state.container.make(OAuthManager)
    return RedirectResponse(manager.redirect_url(request, provider))
```

### oauth_callback

```python
oauth_callback(
    request: Request, provider: str
) -> OAuthUser
```

Complete the login for `provider` and return the resulting identity -- call this from your `GET /auth/{provider}/callback` route, then find-or-create your own `User` from it and call :func:`zeython.auth.login`::

```text
async def oauth_callback(self, request):
    identity = await oauth_callback(request, request.path_params["provider"])
    user = await User.first_where(email=identity.email)
    if user is None:
        user = await User.create(email=identity.email, name=identity.name)
    login(request, user)
    return JSONResponse(user.to_dict())
```

Source code in `src/zeython/oauth.py`

```python
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
```

## saml

SAML 2.0 SSO login: "Sign in with Okta/Azure AD/ADFS/your enterprise IdP", for the identity providers (and enterprise customers) that specifically require SAML rather than OAuth2/OIDC.

Built on `python3-saml <https://github.com/SAML-Toolkits/python3-saml>`\_ (`pip install zeython[saml]`), which does the part worth not reimplementing: building the AuthnRequest, and parsing + validating the IdP's signed Response (XML signature verification, replay/expiry/audience/ recipient checks). Zeython wraps it in an async, container-bound :class:`SamlManager` with the same "hands you a normalized identity, not an opinion about your `User` model" shape as :mod:`zeython.oauth`, so both flows can sit side by side in one app and share the same find-or-create-a-user callback.

Service-provider-initiated flow: your app redirects the user to the IdP (:meth:`SamlManager.login_url`), and the IdP posts a signed assertion back to your Assertion Consumer Service (ACS) URL (:meth:`SamlManager.handle_acs`). An IdP-initiated login (the IdP sends an unsolicited assertion -- common from an admin console's "test connection" button) lands at the same ACS endpoint and validates the same way, since python3-saml doesn't require a matching `InResponseTo` when none was ever sent.

There's no universal attribute-naming standard the way OIDC's userinfo claims are -- an IdP's admin configures which attribute names it sends, often a URN (`http://schemas.xmlsoap.org/ws/2005/05/identity/claims/ emailaddress`) or a short name (`email`), and it varies by IdP and by how that IdP's admin set it up. :class:`SamlUser` recognizes a handful of common ones for `email`/`name` automatically; set `email_attribute=`/`name_attribute=` on :class:`SamlProvider` when yours isn't one of them, and use :meth:`SamlUser.attribute` for anything else your app needs from the assertion.

### SamlUser

```python
SamlUser(
    name_id: str,
    email: str | None,
    name: str | None,
    attributes: dict[str, list[str]] = dict(),
    session_index: str | None = None,
)
```

The identity :meth:`SamlManager.handle_acs` hands back.

`attributes` is exactly what the IdP's assertion included, keyed however the IdP named them -- see the module docstring on why there's no universal naming standard here. Use :meth:`attribute` for anything beyond `email`/`name`.

#### attribute

```python
attribute(name: str) -> str | None
```

The first value of attribute `name`, or `None` if the assertion didn't include it.

Source code in `src/zeython/saml.py`

```python
def attribute(self, name: str) -> str | None:
    """The first value of attribute ``name``, or ``None`` if the
    assertion didn't include it."""
    values = self.attributes.get(name)
    return values[0] if values else None
```

### SamlProvider

```python
SamlProvider(
    name: str,
    idp_entity_id: str,
    idp_sso_url: str,
    idp_x509_cert: str,
    sp_entity_id: str,
    acs_url: str,
    sp_x509_cert: str | None = None,
    sp_private_key: str | None = None,
    email_attribute: str | None = None,
    name_attribute: str | None = None,
)
```

One configured IdP connection -- built by :func:`saml_provider` rather than constructed directly in ordinary use. `acs_url` (your app's Assertion Consumer Service) must exactly match what's registered at the IdP.

#### to_settings

```python
to_settings() -> dict[str, Any]
```

The `dict` shape `python3-saml`'s `OneLogin_Saml2_Settings` expects.

Source code in `src/zeython/saml.py`

```python
def to_settings(self) -> dict[str, Any]:
    """The ``dict`` shape ``python3-saml``'s ``OneLogin_Saml2_Settings`` expects."""
    return {
        "strict": True,
        "sp": {
            "entityId": self.sp_entity_id,
            "assertionConsumerService": {
                "url": self.acs_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
            "x509cert": self.sp_x509_cert or "",
            "privateKey": self.sp_private_key or "",
        },
        "idp": {
            "entityId": self.idp_entity_id,
            "singleSignOnService": {
                "url": self.idp_sso_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": self.idp_x509_cert,
        },
        "security": {
            "authnRequestsSigned": bool(self.sp_private_key and self.sp_x509_cert),
        },
    }
```

### SamlManager

```python
SamlManager(
    providers: dict[str, SamlProvider],
    *,
    replay_cache: Cache | None = None,
    replay_window: float = DEFAULT_REPLAY_WINDOW,
)
```

Builds the login redirect, validates the ACS callback, and generates SP metadata for every provider registered with it. Bound in the container by :class:`SamlServiceProvider`.

Tracks every assertion ID it accepts in `replay_cache` (a fresh :class:`~zeython.cache.InMemoryCache` by default) for `replay_window` seconds, and rejects a second callback presenting the same ID -- without this, a signed SAMLResponse a network observer captures (or an IdP-side bug/misconfiguration that redelivers one) stays valid and replayable for its entire signature-validity window, letting an attacker complete the same login again by simply resending the original request. Signature validation alone doesn't catch this: a replayed response is, cryptographically, exactly as valid the second time as the first.

Source code in `src/zeython/saml.py`

```python
def __init__(
    self,
    providers: dict[str, SamlProvider],
    *,
    replay_cache: Cache | None = None,
    replay_window: float = DEFAULT_REPLAY_WINDOW,
) -> None:
    self.providers = providers
    self.replay_cache = replay_cache if replay_cache is not None else InMemoryCache()
    self.replay_window = replay_window
    self._replay_locks: dict[str, asyncio.Lock] = {}
```

#### login_url

```python
login_url(request: Request, provider_name: str) -> str
```

The URL to send the browser to at `provider_name`'s IdP.

Source code in `src/zeython/saml.py`

```python
def login_url(self, request: Request, provider_name: str) -> str:
    """The URL to send the browser to at ``provider_name``'s IdP."""
    return self._auth(request, provider_name).login()
```

#### handle_acs

```python
handle_acs(
    request: Request, provider_name: str
) -> SamlUser
```

Validate the IdP's POSTed assertion and return the identity it asserts. Raises :class:`~zeython.exceptions.BadRequestException` if the callback carried no `SAMLResponse`, and :class:`~zeython.exceptions.ForbiddenException` if the response failed validation (bad/missing signature, expired, wrong audience/recipient, already used once before, ...).

Source code in `src/zeython/saml.py`

```python
async def handle_acs(self, request: Request, provider_name: str) -> SamlUser:
    """Validate the IdP's POSTed assertion and return the identity it
    asserts. Raises :class:`~zeython.exceptions.BadRequestException`
    if the callback carried no ``SAMLResponse``, and
    :class:`~zeython.exceptions.ForbiddenException` if the response
    failed validation (bad/missing signature, expired, wrong
    audience/recipient, already used once before, ...).
    """
    form = await request.form()
    saml_response = form.get("SAMLResponse")
    if not isinstance(saml_response, str):
        raise BadRequestException("The IdP's callback did not include a SAMLResponse.")

    auth = self._auth(request, provider_name, post_data={"SAMLResponse": saml_response})
    auth.process_response()
    errors = auth.get_errors()
    if errors:
        raise ForbiddenException(
            f"SAML response validation failed ({', '.join(errors)}): {auth.get_last_error_reason()}"
        )
    if not auth.is_authenticated():
        raise ForbiddenException("SAML authentication was not successful.")

    assertion_id = auth.get_last_assertion_id()
    replay_key = f"saml:seen-assertion:{assertion_id}"
    # Locked (not just checked) so two requests racing to replay the
    # very same assertion can't both pass the has()-then-put() check
    # before either has written its own entry.
    lock = self._replay_locks.setdefault(replay_key, asyncio.Lock())
    try:
        async with lock:
            if await self.replay_cache.has(replay_key):
                raise ForbiddenException("This SAML assertion has already been used.")
            await self.replay_cache.put(replay_key, True, ttl=self.replay_window)
    finally:
        self._replay_locks.pop(replay_key, None)

    provider = self._provider(provider_name)
    attributes: dict[str, list[str]] = auth.get_attributes()
    email = (
        attributes.get(provider.email_attribute, [None])[0]
        if provider.email_attribute
        else _first_present(attributes, _EMAIL_ATTRIBUTE_CANDIDATES)
    )
    name = (
        attributes.get(provider.name_attribute, [None])[0]
        if provider.name_attribute
        else _first_present(attributes, _NAME_ATTRIBUTE_CANDIDATES)
    )

    return SamlUser(
        name_id=auth.get_nameid(),
        email=email,
        name=name,
        attributes=attributes,
        session_index=auth.get_session_index(),
    )
```

#### metadata_xml

```python
metadata_xml(provider_name: str) -> str
```

The SP metadata XML to hand your IdP admin when they ask for it, instead of entering entity ID/ACS URL/certificate by hand.

Raises :class:`RuntimeError` if the generated metadata is invalid (a configuration error in the :class:`SamlProvider` -- this is a setup-time check, not something a real request can trigger).

Source code in `src/zeython/saml.py`

```python
def metadata_xml(self, provider_name: str) -> str:
    """The SP metadata XML to hand your IdP admin when they ask for it,
    instead of entering entity ID/ACS URL/certificate by hand.

    Raises :class:`RuntimeError` if the generated metadata is invalid
    (a configuration error in the :class:`SamlProvider` -- this is a
    setup-time check, not something a real request can trigger).
    """
    from onelogin.saml2.settings import OneLogin_Saml2_Settings

    provider = self._provider(provider_name)
    settings = OneLogin_Saml2_Settings(provider.to_settings(), sp_validation_only=True)
    metadata = settings.get_sp_metadata()
    errors = settings.validate_metadata(metadata)
    if errors:
        raise RuntimeError(f"Invalid SAML SP metadata for provider {provider_name!r}: {', '.join(errors)}")
    return metadata  # type: ignore[no-any-return]
```

### SamlServiceProvider

```python
SamlServiceProvider(
    app: Application,
    *,
    providers: list[SamlProvider],
    replay_cache: Cache | None = None,
    replay_window: float = DEFAULT_REPLAY_WINDOW,
)
```

Bases: `ServiceProvider`

Binds a :class:`SamlManager` configured with the given providers::

```text
app.register(SamlServiceProvider(app, providers=[
    saml_provider(
        name="okta",
        idp_entity_id="http://www.okta.com/exk...",
        idp_sso_url="https://your-org.okta.com/app/.../sso/saml",
        idp_x509_cert="-----BEGIN CERTIFICATE-----...",
        sp_entity_id="https://app.example.com/saml/okta/metadata",
        acs_url="https://app.example.com/saml/okta/acs",
    ),
]))
```

Needs `AuthServiceProvider` registered too (for :func:`zeython.auth.login` your ACS route calls) -- registration order between the two doesn't matter. See docs/saml.md.

Pass `replay_cache` (a :class:`~zeython.cache.RedisCache`) to share the used-assertion tracking across every process/machine instead of each one only remembering what it itself has seen -- see :class:`SamlManager` for why this tracking exists at all.

Source code in `src/zeython/saml.py`

```python
def __init__(
    self,
    app: Application,
    *,
    providers: list[SamlProvider],
    replay_cache: Cache | None = None,
    replay_window: float = DEFAULT_REPLAY_WINDOW,
) -> None:
    super().__init__(app)
    self.providers = providers
    self.replay_cache = replay_cache
    self.replay_window = replay_window
```

### saml_provider

```python
saml_provider(
    *,
    name: str,
    idp_entity_id: str,
    idp_sso_url: str,
    idp_x509_cert: str,
    sp_entity_id: str,
    acs_url: str,
    sp_x509_cert: str | None = None,
    sp_private_key: str | None = None,
    email_attribute: str | None = None,
    name_attribute: str | None = None,
) -> SamlProvider
```

Configure one IdP connection -- everything here comes from your IdP admin's console (entity ID, SSO URL, signing certificate) plus the ACS URL you register there in return. `sp_x509_cert`/`sp_private_key` are optional -- set both to have Zeython sign outgoing AuthnRequests (some IdPs require it); without them, the request goes unsigned, which most IdPs accept for SP-initiated login since the security-critical direction is the IdP's signed *response*, always required.

Source code in `src/zeython/saml.py`

```python
def saml_provider(
    *,
    name: str,
    idp_entity_id: str,
    idp_sso_url: str,
    idp_x509_cert: str,
    sp_entity_id: str,
    acs_url: str,
    sp_x509_cert: str | None = None,
    sp_private_key: str | None = None,
    email_attribute: str | None = None,
    name_attribute: str | None = None,
) -> SamlProvider:
    """Configure one IdP connection -- everything here comes from your
    IdP admin's console (entity ID, SSO URL, signing certificate) plus the
    ACS URL you register there in return. ``sp_x509_cert``/``sp_private_key``
    are optional -- set both to have Zeython sign outgoing AuthnRequests
    (some IdPs require it); without them, the request goes unsigned, which
    most IdPs accept for SP-initiated login since the security-critical
    direction is the IdP's signed *response*, always required.
    """
    return SamlProvider(
        name=name,
        idp_entity_id=idp_entity_id,
        idp_sso_url=idp_sso_url,
        idp_x509_cert=idp_x509_cert,
        sp_entity_id=sp_entity_id,
        acs_url=acs_url,
        sp_x509_cert=sp_x509_cert,
        sp_private_key=sp_private_key,
        email_attribute=email_attribute,
        name_attribute=name_attribute,
    )
```

### saml_login

```python
saml_login(
    request: Request, provider: str
) -> RedirectResponse
```

Send the browser to `provider`'s IdP login page -- call this from your `GET /saml/{provider}/login` route::

```text
async def saml_login(self, request):
    return saml_login(request, request.path_params["provider"])
```

Source code in `src/zeython/saml.py`

```python
def saml_login(request: Request, provider: str) -> RedirectResponse:
    """Send the browser to ``provider``'s IdP login page -- call this from
    your ``GET /saml/{provider}/login`` route::

        async def saml_login(self, request):
            return saml_login(request, request.path_params["provider"])
    """
    manager: SamlManager = request.app.state.container.make(SamlManager)
    return RedirectResponse(manager.login_url(request, provider))
```

### saml_acs

```python
saml_acs(request: Request, provider: str) -> SamlUser
```

Complete the login for `provider` and return the resulting identity -- call this from your `POST /saml/{provider}/acs` route (the Assertion Consumer Service URL registered at the IdP), then find-or-create your own `User` from it and call :func:`zeython.auth.login`::

```text
async def saml_acs(self, request):
    identity = await saml_acs(request, request.path_params["provider"])
    user = await User.first_where(email=identity.email)
    if user is None:
        user = await User.create(email=identity.email, name=identity.name)
    login(request, user)
    return RedirectResponse("/", status_code=303)
```

Source code in `src/zeython/saml.py`

```python
async def saml_acs(request: Request, provider: str) -> SamlUser:
    """Complete the login for ``provider`` and return the resulting
    identity -- call this from your ``POST /saml/{provider}/acs`` route
    (the Assertion Consumer Service URL registered at the IdP), then
    find-or-create your own ``User`` from it and call
    :func:`zeython.auth.login`::

        async def saml_acs(self, request):
            identity = await saml_acs(request, request.path_params["provider"])
            user = await User.first_where(email=identity.email)
            if user is None:
                user = await User.create(email=identity.email, name=identity.name)
            login(request, user)
            return RedirectResponse("/", status_code=303)
    """
    manager: SamlManager = request.app.state.container.make(SamlManager)
    return await manager.handle_acs(request, provider)
```

### saml_metadata

```python
saml_metadata(request: Request, provider: str) -> Response
```

Serve `provider`'s SP metadata XML -- call this from a `GET /saml/{provider}/metadata` route and hand your IdP admin the URL, instead of entering entity ID/ACS URL/certificate by hand::

```text
async def saml_metadata(self, request):
    return await saml_metadata(request, request.path_params["provider"])
```

Source code in `src/zeython/saml.py`

```python
async def saml_metadata(request: Request, provider: str) -> Response:
    """Serve ``provider``'s SP metadata XML -- call this from a
    ``GET /saml/{provider}/metadata`` route and hand your IdP admin the
    URL, instead of entering entity ID/ACS URL/certificate by hand::

        async def saml_metadata(self, request):
            return await saml_metadata(request, request.path_params["provider"])
    """
    manager: SamlManager = request.app.state.container.make(SamlManager)
    return Response(manager.metadata_xml(provider), media_type="application/samlmetadata+xml")
```

## mfa

Time-based one-time password (TOTP) two-factor authentication.

RFC 6238 TOTP layered on top of the existing session-auth login flow (:mod:`zeython.auth`): a user enrolls a secret, confirms it with a live code from their authenticator app to turn MFA on (issuing one-time recovery codes for when they lose that device), and from then on a password check alone isn't enough -- login is gated behind a second step. No new dependency: HMAC-SHA1 and base32 are both in the standard library, so this needs nothing beyond what's already imported for password hashing.

### MfaEnrollable

Mixin adding TOTP two-factor auth to a user model.

Declare the columns yourself, the same convention :class:`~zeython.auth.Authenticatable` uses for `password_hash`::

```text
class User(Model, Authenticatable, MfaEnrollable):
    __tablename__ = "users"
    __hidden__ = ("password_hash", "mfa_secret", "mfa_recovery_codes")

    mfa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_recovery_codes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
```

`mfa_secret` and `mfa_recovery_codes` belong in `__hidden__` -- they're as sensitive as `password_hash` and must never round-trip through `to_dict()`.

### Enrollment

```python
Enrollment(secret: str, uri: str)
```

The result of :func:`enroll` -- both forms an authenticator app accepts: `uri` for a QR code (rendered client-side; this module has no image dependency), `secret` for manual entry as a fallback.

### generate_secret

```python
generate_secret() -> str
```

A fresh random base32 TOTP secret, 160 bits -- RFC 4226's recommended minimum key length, twice what a bare 80-bit secret would give an attacker brute-forcing offline.

Source code in `src/zeython/mfa.py`

```python
def generate_secret() -> str:
    """A fresh random base32 TOTP secret, 160 bits -- RFC 4226's recommended
    minimum key length, twice what a bare 80-bit secret would give an
    attacker brute-forcing offline.
    """
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")
```

### provisioning_uri

```python
provisioning_uri(
    secret: str, *, account_name: str, issuer: str
) -> str
```

The `otpauth://totp/...` URI an authenticator app scans as a QR code (e.g. via a client-side JS QR library) or accepts pasted directly.

Source code in `src/zeython/mfa.py`

```python
def provisioning_uri(secret: str, *, account_name: str, issuer: str) -> str:
    """The ``otpauth://totp/...`` URI an authenticator app scans as a QR
    code (e.g. via a client-side JS QR library) or accepts pasted directly.
    """
    label = quote(f"{issuer}:{account_name}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&digits={_DIGITS}&period={_PERIOD}"
```

### verify_totp

```python
verify_totp(
    secret: str, code: str, *, valid_window: int = 1
) -> bool
```

`True` if `code` matches `secret` for the current 30s step, or up to `valid_window` steps either side (tolerating ordinary clock drift between server and the authenticator app -- the default of 1 accepts a ±30s window).

Source code in `src/zeython/mfa.py`

```python
def verify_totp(secret: str, code: str, *, valid_window: int = 1) -> bool:
    """``True`` if ``code`` matches ``secret`` for the current 30s step, or
    up to ``valid_window`` steps either side (tolerating ordinary clock
    drift between server and the authenticator app -- the default of 1
    accepts a ±30s window).
    """
    if not code or not code.isdigit() or len(code) != _DIGITS:
        return False
    counter = int(time.time() // _PERIOD)
    return any(
        hmac.compare_digest(_hotp(secret, counter + offset), code)
        for offset in range(-valid_window, valid_window + 1)
    )
```

### enroll

```python
enroll(
    user: Any, *, account_name: str, issuer: str = "Zeython"
) -> Enrollment
```

Start enrollment: generates a new secret and stores it on `user` -- not yet enabled, :func:`confirm` must verify a live code first. Calling this again before confirming replaces the pending secret, so an abandoned enrollment can't be confirmed later with a stale one.

Source code in `src/zeython/mfa.py`

```python
async def enroll(user: Any, *, account_name: str, issuer: str = "Zeython") -> Enrollment:
    """Start enrollment: generates a new secret and stores it on ``user`` --
    not yet enabled, :func:`confirm` must verify a live code first. Calling
    this again before confirming replaces the pending secret, so an
    abandoned enrollment can't be confirmed later with a stale one.
    """
    secret = generate_secret()
    user.mfa_secret = secret
    await user.save()
    return Enrollment(secret=secret, uri=provisioning_uri(secret, account_name=account_name, issuer=issuer))
```

### confirm

```python
confirm(user: Any, code: str) -> list[str]
```

Verify `code` against the pending secret from :func:`enroll`, turning MFA on and issuing recovery codes -- returned here in plaintext, the only time they're ever visible; only their hash is stored, the same way a password is. Raises :class:`ValidationException` if there's no enrollment in progress or the code doesn't verify.

Source code in `src/zeython/mfa.py`

```python
async def confirm(user: Any, code: str) -> list[str]:
    """Verify ``code`` against the pending secret from :func:`enroll`,
    turning MFA on and issuing recovery codes -- returned here in
    plaintext, the only time they're ever visible; only their hash is
    stored, the same way a password is. Raises :class:`ValidationException`
    if there's no enrollment in progress or the code doesn't verify.
    """
    if not user.mfa_secret:
        raise ValidationException({"code": ["No MFA enrollment in progress."]})
    if not verify_totp(user.mfa_secret, code):
        raise ValidationException({"code": ["Invalid code."]})

    codes = _generate_recovery_codes()
    user.mfa_enabled = True
    user.mfa_recovery_codes = [hash_password(c) for c in codes]
    await user.save()
    return codes
```

### disable

```python
disable(user: Any) -> None
```

Turn MFA off and forget the secret and recovery codes.

Source code in `src/zeython/mfa.py`

```python
async def disable(user: Any) -> None:
    """Turn MFA off and forget the secret and recovery codes."""
    user.mfa_secret = None
    user.mfa_enabled = False
    user.mfa_recovery_codes = None
    await user.save()
```

### verify_and_consume

```python
verify_and_consume(user: Any, code: str) -> bool
```

`True` if `code` is a valid live TOTP code, or an unused recovery code. A matching recovery code is consumed -- removed from storage -- on success, since each is one-time use; a spent code never verifies again, including under two requests racing to spend it at once (on Postgres/MySQL -- see the note below for SQLite).

The recovery-code check re-fetches `user` with `find(..., for_update=True)` rather than trusting whatever's already loaded on the `user` passed in: without a lock, two concurrent requests presenting the same code could each read it as still unused before either had written its removal, and both would be told the code was valid. Locking the row means the second request's re-fetch blocks until the first's transaction actually commits, so it then correctly sees the code already gone.

On SQLite specifically, this guarantee doesn't hold -- see :meth:`~zeython.db.Model.find`'s `for_update` docs -- so two genuinely concurrent requests there can still both succeed, same as before this existed.

Source code in `src/zeython/mfa.py`

```python
async def verify_and_consume(user: Any, code: str) -> bool:
    """``True`` if ``code`` is a valid live TOTP code, or an unused recovery
    code. A matching recovery code is consumed -- removed from storage --
    on success, since each is one-time use; a spent code never verifies
    again, including under two requests racing to spend it at once (on
    Postgres/MySQL -- see the note below for SQLite).

    The recovery-code check re-fetches ``user`` with
    ``find(..., for_update=True)`` rather than trusting whatever's already
    loaded on the ``user`` passed in: without a lock, two concurrent
    requests presenting the same code could each read it as still unused
    before either had written its removal, and both would be told the
    code was valid. Locking the row means the second request's re-fetch
    blocks until the first's transaction actually commits, so it then
    correctly sees the code already gone.

    On SQLite specifically, this guarantee doesn't hold -- see
    :meth:`~zeython.db.Model.find`'s ``for_update`` docs -- so two
    genuinely concurrent requests there can still both succeed, same as
    before this existed.
    """
    if not user.mfa_enabled or not user.mfa_secret:
        return False
    if verify_totp(user.mfa_secret, code):
        return True

    locked = await type(user).find(user.id, for_update=True)
    if locked is None:
        return False
    for hashed in locked.mfa_recovery_codes or []:
        if verify_password(code, hashed):
            locked.mfa_recovery_codes = [h for h in locked.mfa_recovery_codes if h != hashed]
            await locked.save()
            return True
    return False
```

### start_challenge

```python
start_challenge(request: Request, user: Model) -> None
```

Mark `user` as having passed the password check but still needing their second factor -- call this from a login handler instead of :func:`zeython.auth.login` whenever `user.mfa_enabled` is true::

```text
user = await manager.attempt(email, password)
if user is None:
    raise UnauthorizedException("Invalid email or password.")
if user.mfa_enabled:
    start_challenge(request, user)
    return JSONResponse({"mfa_required": True})
auth_login(request, user)
```

The user is *not* authenticated yet -- :func:`~zeython.auth.current_user` still returns `None` -- until :func:`complete_challenge` succeeds.

Source code in `src/zeython/mfa.py`

```python
def start_challenge(request: Request, user: Model) -> None:
    """Mark ``user`` as having passed the password check but still needing
    their second factor -- call this from a login handler instead of
    :func:`zeython.auth.login` whenever ``user.mfa_enabled`` is true::

        user = await manager.attempt(email, password)
        if user is None:
            raise UnauthorizedException("Invalid email or password.")
        if user.mfa_enabled:
            start_challenge(request, user)
            return JSONResponse({"mfa_required": True})
        auth_login(request, user)

    The user is *not* authenticated yet -- :func:`~zeython.auth.current_user`
    still returns ``None`` -- until :func:`complete_challenge` succeeds.
    """
    request.session[_PENDING_SESSION_KEY] = user.id
```

### pending_user_id

```python
pending_user_id(request: Request) -> int | None
```

The id of the user awaiting their second factor, or `None` if there's no challenge in progress for this session.

Source code in `src/zeython/mfa.py`

```python
def pending_user_id(request: Request) -> int | None:
    """The id of the user awaiting their second factor, or ``None`` if
    there's no challenge in progress for this session.
    """
    return request.session.get(_PENDING_SESSION_KEY)
```

### complete_challenge

```python
complete_challenge(
    request: Request, code: str
) -> Model | None
```

Verify `code` for the user :func:`start_challenge` left pending and, on success, complete login (equivalent to calling :func:`zeython.auth.login` directly) and return that user. Returns `None` if there's no pending challenge or `code` doesn't verify -- the pending state is left in place on failure so the caller can retry, subject to their own :func:`~zeython.rate_limit.throttle`.

Source code in `src/zeython/mfa.py`

```python
async def complete_challenge(request: Request, code: str) -> Model | None:
    """Verify ``code`` for the user :func:`start_challenge` left pending
    and, on success, complete login (equivalent to calling
    :func:`zeython.auth.login` directly) and return that user. Returns
    ``None`` if there's no pending challenge or ``code`` doesn't verify --
    the pending state is left in place on failure so the caller can retry,
    subject to their own :func:`~zeython.rate_limit.throttle`.
    """
    user_id = pending_user_id(request)
    if user_id is None:
        return None

    manager: AuthManager = request.app.state.container.make(AuthManager)
    user = await manager.user_model.find(user_id)
    if user is None or not await verify_and_consume(user, code):
        return None

    request.session.pop(_PENDING_SESSION_KEY, None)
    login(request, user)
    return user
```

## api_auth

API token authentication: stateless bearer tokens for clients that can't use cookies -- a mobile app, a separate SPA, a server-to-server caller.

Deliberately a separate code path from :mod:`zeython.auth`'s cookie sessions, not a mode bolted onto the same functions -- a bearer token and a session cookie are verified differently, travel in different places (an `Authorization` header vs. a cookie jar), and a handler should be unambiguous about which one it expects.

Tokens are signed with `itsdangerous` (already a framework dependency, used by Starlette's own session cookie signing) rather than a JWT library or a database-backed token table -- no new dependency, and no migration required to get started. The trade-off that buys: a token can't be revoked before it expires. There's no server-side record of it to delete. If your app needs "log this device out remotely," implement a real :class:`TokenManager` yourself against a token table you can delete rows from -- this one is the zero-setup default, not the only correct design.

### TokenManager

```python
TokenManager(
    user_model: type[Model],
    *,
    secret_key: str,
    expires_in: int,
)
```

Issues and verifies bearer tokens for a chosen user model.

Source code in `src/zeython/api_auth.py`

```python
def __init__(self, user_model: type[Model], *, secret_key: str, expires_in: int) -> None:
    self.user_model = user_model
    self.expires_in = expires_in
    self._serializer = URLSafeTimedSerializer(secret_key, salt=_SALT)
```

#### issue

```python
issue(user: Model) -> str
```

A signed token encoding `user.id`.

Signed, not encrypted: `itsdangerous` protects against *tampering* (a client can't forge or edit a valid token without the secret key) but not against *reading* -- the payload is only base64-encoded, trivially decodable by anyone holding the token, the client it was issued to included. Fine for `user_id` alone; don't extend this to encode anything that shouldn't be readable by whoever holds the token.

Source code in `src/zeython/api_auth.py`

```python
def issue(self, user: Model) -> str:
    """A signed token encoding ``user.id``.

    Signed, not encrypted: ``itsdangerous`` protects against
    *tampering* (a client can't forge or edit a valid token without
    the secret key) but not against *reading* -- the payload is only
    base64-encoded, trivially decodable by anyone holding the token,
    the client it was issued to included. Fine for ``user_id`` alone;
    don't extend this to encode anything that shouldn't be readable
    by whoever holds the token.
    """
    return self._serializer.dumps({"user_id": user.id})
```

#### verify

```python
verify(token: str) -> Model | None
```

The user the token was issued for, or `None` if it's missing, tampered, or expired.

Source code in `src/zeython/api_auth.py`

```python
async def verify(self, token: str) -> Model | None:
    """The user the token was issued for, or ``None`` if it's missing, tampered, or expired."""
    try:
        data = self._serializer.loads(token, max_age=self.expires_in)
    except BadSignature:
        return None
    user_id = data.get("user_id") if isinstance(data, dict) else None
    if user_id is None:
        return None
    return await self.user_model.find(user_id)
```

### ApiAuthServiceProvider

```python
ApiAuthServiceProvider(
    app: Application, user_model: type[Model]
)
```

Bases: `ServiceProvider`

Binds a :class:`TokenManager` into the container.

Reuses `APP_SECRET_KEY` (the same key session cookies are signed with) -- rotating it invalidates every issued token, same as it already invalidates every session. `.env`: `API_TOKEN_EXPIRES_IN` (seconds, default 30 days).

Source code in `src/zeython/api_auth.py`

```python
def __init__(self, app: Application, user_model: type[Model]) -> None:
    super().__init__(app)
    self.user_model = user_model
```

### current_api_user

```python
current_api_user(request: Request) -> Model | None
```

The user identified by this request's `Authorization: Bearer <token>` header, or `None`.

Source code in `src/zeython/api_auth.py`

```python
async def current_api_user(request: Request) -> Model | None:
    """The user identified by this request's ``Authorization: Bearer <token>`` header, or ``None``."""
    token = _bearer_token(request)
    if token is None:
        return None
    manager: TokenManager = request.app.state.container.make(TokenManager)
    return await manager.verify(token)
```

### require_api_auth

```python
require_api_auth(request: Request) -> Model
```

Return the token-authenticated user, or raise `UnauthorizedException` (401).

Call this at the top of any handler meant for bearer-token clients, the same way :func:`~zeython.auth.require_auth` guards cookie-session ones::

```text
async def me(self, request):
    user = await require_api_auth(request)
```

Source code in `src/zeython/api_auth.py`

```python
async def require_api_auth(request: Request) -> Model:
    """Return the token-authenticated user, or raise ``UnauthorizedException`` (401).

    Call this at the top of any handler meant for bearer-token clients, the
    same way :func:`~zeython.auth.require_auth` guards cookie-session ones::

        async def me(self, request):
            user = await require_api_auth(request)
    """
    user = await current_api_user(request)
    if user is None:
        raise UnauthorizedException("A valid API token is required.")
    return user
```

## authorization

Authorization: "can this specific user do this specific thing", answered separately from authentication.

`require_auth()` (see :mod:`zeython.auth`) only answers "is anyone logged in" -- a materially different, and much weaker, question than "can the logged-in user edit *this* post". Almost every mutating endpoint in a real app needs the second question answered, and there was previously nothing in the framework that helped with it beyond hand-rolled `if` checks scattered across controllers.

Modeled on Laravel's Gate/Policy split: named closures for one-off checks (`gate.define(...)`), resource-bound Policy classes (`gate.policy(...)`) for the common case of many abilities against one model, a global `gate.before(...)` hook for cross-cutting rules like "an admin can do anything", and a light :class:`HasRoles` mixin plus :meth:`Gate.role`/ :meth:`Gate.permission` sugar for role- or permission-gated abilities. All of it is optional and additive -- a project that only ever needs `gate.define("delete-post", lambda user, post: ...)` never has to touch the rest.

### Gate

```python
Gate()
```

A registry of named authorization checks ("abilities").

Source code in `src/zeython/authorization.py`

```python
def __init__(self) -> None:
    self._abilities: dict[str, Check] = {}
    self._policies: dict[type, Any] = {}
    self._before: list[BeforeCheck] = []
```

#### define

```python
define(ability: str, check: Check) -> None
```

Register `check(user, *args) -> bool` (sync or async) under `ability`::

gate.define("update-post", lambda user, post: post.author_id == user.id)

Source code in `src/zeython/authorization.py`

```python
def define(self, ability: str, check: Check) -> None:
    """Register ``check(user, *args) -> bool`` (sync or async) under ``ability``::

        gate.define("update-post", lambda user, post: post.author_id == user.id)
    """
    self._abilities[ability] = check
```

#### policy

```python
policy(model: type, policy: type | Any) -> None
```

Register a Policy for `model`: a plain class with one method per ability, e.g. `def update(self, user, post) -> bool`. `policy` may be the class itself (instantiated once, here) or an existing instance::

```text
class PostPolicy:
    def update(self, user, post) -> bool:
        return post.author_id == user.id

    def create(self, user) -> bool:
        return user.is_verified

gate.policy(Post, PostPolicy)
```

An ability not covered by :meth:`define` falls back to the policy registered for `type(args[0])` (or `args[0]` itself, when it's a class -- for abilities like `"create"` checked before an instance exists: `authorize(request, "create", Post)`). A policy method named `before(self, user, ability)` runs first if present, and a non-`None` result short-circuits the specific ability method -- the per-policy equivalent of :meth:`before`.

Source code in `src/zeython/authorization.py`

```python
def policy(self, model: type, policy: type | Any) -> None:
    """Register a Policy for ``model``: a plain class with one method per
    ability, e.g. ``def update(self, user, post) -> bool``. ``policy``
    may be the class itself (instantiated once, here) or an existing
    instance::

        class PostPolicy:
            def update(self, user, post) -> bool:
                return post.author_id == user.id

            def create(self, user) -> bool:
                return user.is_verified

        gate.policy(Post, PostPolicy)

    An ability not covered by :meth:`define` falls back to the policy
    registered for ``type(args[0])`` (or ``args[0]`` itself, when it's a
    class -- for abilities like ``"create"`` checked before an instance
    exists: ``authorize(request, "create", Post)``). A policy method
    named ``before(self, user, ability)`` runs first if present, and a
    non-``None`` result short-circuits the specific ability method --
    the per-policy equivalent of :meth:`before`.
    """
    self._policies[model] = policy() if isinstance(policy, type) else policy
```

#### before

```python
before(check: BeforeCheck) -> None
```

Register a global hook run before every :meth:`allows` check, as `check(user, ability, *args)`. A non-`None` result short-circuits the specific ability/policy check entirely -- typically used for a blanket bypass::

```text
gate.before(lambda user, ability, *args: True if getattr(user, "is_admin", False) else None)
```

Returning `None` (the default for a check that only cares about specific abilities) defers to the normal ability/policy lookup.

Source code in `src/zeython/authorization.py`

```python
def before(self, check: BeforeCheck) -> None:
    """Register a global hook run before every :meth:`allows` check,
    as ``check(user, ability, *args)``. A non-``None`` result
    short-circuits the specific ability/policy check entirely --
    typically used for a blanket bypass::

        gate.before(lambda user, ability, *args: True if getattr(user, "is_admin", False) else None)

    Returning ``None`` (the default for a check that only cares about
    specific abilities) defers to the normal ability/policy lookup.
    """
    self._before.append(check)
```

#### role

```python
role(*names: str) -> Check
```

A check requiring the user to have any of `names`, via :class:`HasRoles`::

```text
gate.define("manage-users", Gate.role("admin"))
```

Source code in `src/zeython/authorization.py`

```python
@staticmethod
def role(*names: str) -> Check:
    """A check requiring the user to have any of ``names``, via
    :class:`HasRoles`::

        gate.define("manage-users", Gate.role("admin"))
    """

    def check(user: Any, *_args: Any) -> bool:
        has_any_role = getattr(user, "has_any_role", None)
        return bool(has_any_role(*names)) if has_any_role is not None else False

    return check
```

#### permission

```python
permission(name: str) -> Check
```

A check requiring the user to have permission `name`, via :class:`HasRoles`::

```text
gate.define("delete-post", Gate.permission("posts.delete"))
```

Source code in `src/zeython/authorization.py`

```python
@staticmethod
def permission(name: str) -> Check:
    """A check requiring the user to have permission ``name``, via
    :class:`HasRoles`::

        gate.define("delete-post", Gate.permission("posts.delete"))
    """

    def check(user: Any, *_args: Any) -> bool:
        has_permission = getattr(user, "has_permission", None)
        return bool(has_permission(name)) if has_permission is not None else False

    return check
```

#### allows

```python
allows(user: Any, ability: str, *args: Any) -> bool
```

Whether `user` passes the `ability` check against `args`.

Checked in order: any :meth:`before` hook, then a :meth:`define`-d closure, then a :meth:`policy` method for `type(args[0])`. Raises `KeyError` if none of those resolve -- an authorization check for an ability that doesn't exist is a bug in the calling code, not a "deny by default" situation to swallow silently.

Source code in `src/zeython/authorization.py`

```python
async def allows(self, user: Any, ability: str, *args: Any) -> bool:
    """Whether ``user`` passes the ``ability`` check against ``args``.

    Checked in order: any :meth:`before` hook, then a :meth:`define`-d
    closure, then a :meth:`policy` method for ``type(args[0])``.
    Raises ``KeyError`` if none of those resolve -- an authorization
    check for an ability that doesn't exist is a bug in the calling
    code, not a "deny by default" situation to swallow silently.
    """
    for before_check in self._before:
        before_result = before_check(user, ability, *args)
        if inspect.isawaitable(before_result):
            before_result = await before_result
        if before_result is not None:
            return bool(before_result)

    check = self._abilities.get(ability) or self._policy_check(ability, args)
    if check is None:
        raise KeyError(
            f"No ability registered for {ability!r}. Register it with gate.define(...) or gate.policy(...)."
        )
    result = check(user, *args)
    if inspect.isawaitable(result):
        result = await result
    return bool(result)
```

### HasRoles

Mixin adding role/permission checks to a user model, for :meth:`Gate.role`/:meth:`Gate.permission` and for direct use in templates/controllers.

Duck-typed against a `roles` relationship of objects with a `name` attribute, each optionally with its own `permissions` relationship of objects with a `name` attribute -- the conventional Role/Permission many-to-many shape (a user has roles, a role has permissions), which this framework doesn't impose a schema for since it's already just regular models and relationships (see docs/authorization.md for the table definitions and :mod:`zeython.database.seeder` for seeding them)::

```text
class User(Model, Authenticatable, HasRoles):
    __tablename__ = "users"
    roles: Mapped[list["Role"]] = relationship(secondary=user_roles, lazy="selectin")

class Role(Model):
    __tablename__ = "roles"
    name: Mapped[str] = mapped_column(String(50), unique=True)
    permissions: Mapped[list["Permission"]] = relationship(secondary=role_permissions, lazy="selectin")

class Permission(Model):
    __tablename__ = "permissions"
    name: Mapped[str] = mapped_column(String(100), unique=True)
```

### AuthorizationServiceProvider

```python
AuthorizationServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Binds an empty :class:`Gate` into the container.

Define your app's abilities in your own provider's `boot()` (register this provider first, or anywhere -- `boot()` order doesn't matter, only that every provider's `register()` has already run)::

```text
class AppAuthorizationProvider(ServiceProvider):
    def boot(self) -> None:
        gate: Gate = self.container.make(Gate)
        gate.define("delete-post", lambda user, post: post.author_id == user.id)
        gate.policy(Post, PostPolicy)
        gate.before(lambda user, ability, *args: True if getattr(user, "is_admin", False) else None)
```

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

### authorize

```python
authorize(
    request: Request, ability: str, *args: Any
) -> Any
```

Require the current user to pass `ability`, or raise.

Authorization presupposes authentication: this calls :func:`~zeython.auth.require_auth` first, so an anonymous request gets `UnauthorizedException` (401) -- only a *logged-in* user who fails the ability check gets `ForbiddenException` (403). Returns the authenticated user on success::

```text
async def destroy(self, request):
    post = await Post.find(int(request.path_params["id"]))
    await authorize(request, "delete-post", post)
    await post.delete()
```

Source code in `src/zeython/authorization.py`

```python
async def authorize(request: Request, ability: str, *args: Any) -> Any:
    """Require the current user to pass ``ability``, or raise.

    Authorization presupposes authentication: this calls :func:`~zeython.auth.require_auth`
    first, so an anonymous request gets ``UnauthorizedException`` (401) --
    only a *logged-in* user who fails the ability check gets
    ``ForbiddenException`` (403). Returns the authenticated user on success::

        async def destroy(self, request):
            post = await Post.find(int(request.path_params["id"]))
            await authorize(request, "delete-post", post)
            await post.delete()
    """
    user = await require_auth(request)
    gate: Gate = request.app.state.container.make(Gate)
    if not await gate.allows(user, ability, *args):
        raise ForbiddenException(f"You are not authorized to {ability.replace('-', ' ')}.")
    return user
```

## csrf

CSRF protection for cookie-authenticated requests.

A browser attaches cookies to a request automatically, even one triggered by a completely different site -- that's exactly what session-cookie auth (:mod:`zeython.auth`) relies on, and exactly what makes it forgeable without protection: a malicious page can trigger a `POST` to this app and the victim's session cookie rides along, no user interaction beyond "visited a page" required.

This uses the double-submit-cookie pattern: a random token is set as a *readable* (non-`HttpOnly`) cookie, and any unsafe request (`POST`, `PUT`, `PATCH`, `DELETE`) must also send that same value back in a header. A cross-site attacker's page can trigger the cookie to be sent, but can't *read* its value (the same-origin policy blocks that) to also set the matching header -- so a forged request is missing the header, or has the wrong value, and gets rejected. See docs/csrf.md.

### CsrfMiddleware

```python
CsrfMiddleware(
    app: Any,
    *,
    cookie_name: str = DEFAULT_COOKIE_NAME,
    header_name: str = DEFAULT_HEADER_NAME,
    secure: bool = False,
    protect_if_cookie_present: str | None = None,
)
```

Pure ASGI middleware implementing the double-submit-cookie check.

A request is exempt if:

- its method is safe (`GET`/`HEAD`/`OPTIONS`/`TRACE` never change state, so there's nothing to forge),
- it carries an `Authorization` header -- a bearer token isn't attached to cross-site requests automatically the way a cookie is, so it isn't vulnerable to this in the first place (see :mod:`zeython.api_auth`), or
- `protect_if_cookie_present` is set and this request doesn't carry that cookie -- CSRF only matters when there's an existing cookie-authenticated session to forge an action *within*; a request with no session cookie at all (a token-issuing endpoint like `/api/token`, or the very first request from a brand new client) has nothing ambient for a forged cross-site request to ride on. :class:`~zeython.auth.AuthServiceProvider` sets this to its own session cookie's name; leave unset for blanket protection of every unsafe request regardless of cookies.

Every other response gets a fresh `csrf_token` cookie if one isn't already present; every other *request* must send that same value back via the `X-CSRF-Token` header (client-configurable name).

Source code in `src/zeython/csrf.py`

```python
def __init__(
    self,
    app: Any,
    *,
    cookie_name: str = DEFAULT_COOKIE_NAME,
    header_name: str = DEFAULT_HEADER_NAME,
    secure: bool = False,
    protect_if_cookie_present: str | None = None,
) -> None:
    self.app = app
    self.cookie_name = cookie_name
    self.header_name = header_name.lower()
    self.secure = secure
    self.protect_if_cookie_present = protect_if_cookie_present
```

### csrf_token

```python
csrf_token(request: Request) -> str | None
```

The current request's CSRF token, if :class:`CsrfMiddleware` is installed.

Useful for embedding in a server-rendered form as a hidden field, for apps that submit real HTML forms instead of driving everything through `fetch`/XHR (which can just read the cookie directly instead).

Source code in `src/zeython/csrf.py`

```python
def csrf_token(request: Request) -> str | None:
    """The current request's CSRF token, if :class:`CsrfMiddleware` is installed.

    Useful for embedding in a server-rendered form as a hidden field, for
    apps that submit real HTML forms instead of driving everything through
    ``fetch``/XHR (which can just read the cookie directly instead).
    """
    return request.scope.get("csrf_token")
```

## security_headers

Common HTTP security response headers -- opt-in, since sensible defaults for some of these (a Content-Security-Policy above all) are genuinely application-specific: a wrong default here doesn't fail loudly, it just silently breaks a legitimate asset/script your own pages load. Register :class:`SecurityHeadersServiceProvider` explicitly once you've decided what belongs in your own policy, rather than getting one imposed on you.

### SecurityHeadersMiddleware

```python
SecurityHeadersMiddleware(
    app: Any,
    *,
    content_security_policy: str | None = None,
    frame_options: str | None = "DENY",
    content_type_options: bool = True,
    referrer_policy: str
    | None = "strict-origin-when-cross-origin",
    hsts: bool = False,
    hsts_max_age: int = 60 * 60 * 24 * 365,
)
```

Pure ASGI middleware that adds security response headers to every response.

- `X-Content-Type-Options: nosniff` -- stops a browser from second-guessing a response's declared `Content-Type` (the classic case: an uploaded file served back and "sniffed" as HTML, letting it execute as a page instead of staying inert).
- `X-Frame-Options` -- `DENY` by default, so this app can't be framed by another site (clickjacking).
- `Referrer-Policy` -- `strict-origin-when-cross-origin` by default: full URL on same-origin navigation, origin-only cross-origin, nothing on a downgrade to plain HTTP.
- `Content-Security-Policy` -- unset by default. There's no universal safe default: a policy that's too strict breaks your own inline scripts or CDN-loaded assets (this framework's own Swagger UI and dev-mode Tailwind both load from a CDN -- see docs/security-headers.md), and one that's too loose isn't worth sending. Pass your own.
- `Strict-Transport-Security` (HSTS) -- off by default. Turning it on before every path to this app is actually served over HTTPS can lock users out of a plain-HTTP fallback for as long as `max_age` says; only enable it once you mean it.

Source code in `src/zeython/security_headers.py`

```python
def __init__(
    self,
    app: Any,
    *,
    content_security_policy: str | None = None,
    frame_options: str | None = "DENY",
    content_type_options: bool = True,
    referrer_policy: str | None = "strict-origin-when-cross-origin",
    hsts: bool = False,
    hsts_max_age: int = 60 * 60 * 24 * 365,
) -> None:
    self.app = app
    self.content_security_policy = content_security_policy
    self.frame_options = frame_options
    self.content_type_options = content_type_options
    self.referrer_policy = referrer_policy
    self.hsts = hsts
    self.hsts_max_age = hsts_max_age
```

### SecurityHeadersServiceProvider

```python
SecurityHeadersServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Registers :class:`SecurityHeadersMiddleware`, configured entirely via `.env`.

Not registered by default -- see the module docstring. Add it explicitly::

```text
app.register(SecurityHeadersServiceProvider)
```

- `SECURITY_HEADERS_CSP` -- your `Content-Security-Policy` value. Unset by default; no header is sent until you provide one.
- `SECURITY_HEADERS_FRAME_OPTIONS` -- default `DENY`.
- `SECURITY_HEADERS_CONTENT_TYPE_OPTIONS` -- default `true`.
- `SECURITY_HEADERS_REFERRER_POLICY` -- default `strict-origin-when-cross-origin`.
- `SECURITY_HEADERS_HSTS` -- default `false`.
- `SECURITY_HEADERS_HSTS_MAX_AGE` -- default `31536000` (1 year).

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

## hashing

Password hashing: PBKDF2-HMAC-SHA256, no C-extension dependency required.

PBKDF2 was chosen over bcrypt/argon2 deliberately: it needs no third-party crypto library (stdlib `hashlib` only), which keeps the framework installable everywhere pip and a C compiler don't necessarily agree, while still meeting OWASP's current guidance for PBKDF2-HMAC-SHA256 iteration counts.

### hash_password

```python
hash_password(
    password: str, *, iterations: int = _DEFAULT_ITERATIONS
) -> str
```

Hash `password` for storage.

Returns a self-describing string: `pbkdf2_sha256$<iterations>$<salt>$<hash>` (salt and hash base64-encoded), so the iteration count can be raised later without invalidating hashes already in the database.

Source code in `src/zeython/hashing.py`

```python
def hash_password(password: str, *, iterations: int = _DEFAULT_ITERATIONS) -> str:
    """Hash ``password`` for storage.

    Returns a self-describing string: ``pbkdf2_sha256$<iterations>$<salt>$<hash>``
    (salt and hash base64-encoded), so the iteration count can be raised later
    without invalidating hashes already in the database.
    """
    if not password:
        raise ValueError("password must not be empty")

    salt = os.urandom(_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(
        [
            _ALGORITHM,
            str(iterations),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(derived).decode("ascii"),
        ]
    )
```

### verify_password

```python
verify_password(password: str, hashed: str) -> bool
```

Constant-time check of `password` against a hash from :func:`hash_password`.

Source code in `src/zeython/hashing.py`

```python
def verify_password(password: str, hashed: str) -> bool:
    """Constant-time check of ``password`` against a hash from :func:`hash_password`."""
    if not password or not hashed:
        return False

    parts = hashed.split("$")
    if len(parts) != 4:
        return False
    algorithm, iterations_raw, salt_b64, hash_b64 = parts

    if algorithm != _ALGORITHM:
        return False

    try:
        iterations = int(iterations_raw)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False

    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(derived, expected)
```

## tenancy

Row-level multi-tenancy: isolating one tenant's rows from another's in a single shared database, rather than a database (or schema) per tenant.

A model opts in just by declaring a `tenant_id` column -- no mixin, no per-query flag. :class:`~zeython.db.Model`'s own query methods (`find`/`all`/`find_by`/`paginate`) check for that column and, if present, scope every read to :func:`current_tenant_id` automatically (see `Model._base_select()`); a new row gets `tenant_id` assigned from the same source on `save()` if it wasn't already set explicitly. Multi-tenant awareness lives in one place -- the column's presence -- rather than scattered `.where(tenant_id=...)` calls a future query is one missed line away from leaking across tenants.

:class:`TenantMiddleware` resolves *which* tenant a request belongs to and makes it available to :func:`current_tenant_id` for the request's duration via a :class:`~contextvars.ContextVar`, the same technique :func:`~zeython.request_id.request_id` and :func:`~zeython.localization.current_locale` use -- readable from a `Model` query with no `request` in hand.

### TenantMiddleware

```python
TenantMiddleware(app: Any, *, resolver: TenantResolver)
```

Pure ASGI middleware: resolves the request's tenant via `resolver` and sets it as a contextvar for :func:`current_tenant_id` for the request's duration.

Source code in `src/zeython/tenancy.py`

```python
def __init__(self, app: Any, *, resolver: TenantResolver) -> None:
    self.app = app
    self.resolver = resolver
```

### TenancyServiceProvider

```python
TenancyServiceProvider(
    app: Application, *, resolver: TenantResolver
)
```

Bases: `ServiceProvider`

Registers :class:`TenantMiddleware` with `resolver`.

`resolver` is a **required** argument -- there is deliberately no default. How a request maps to a tenant (a subdomain, a header, the logged-in user's own `tenant_id`) is entirely app-specific, and guessing wrong here is a cross-tenant data leak, not a cosmetic mistake -- the same reasoning :class:`~zeython.admin.AdminServiceProvider`'s required `guard` has.

::

```text
from zeython import Application, TenancyServiceProvider

def resolve_tenant(request):
    # e.g. acme.example.com -> "acme"
    return request.url.hostname.split(".")[0]

app.register(TenancyServiceProvider(app, resolver=resolve_tenant))
```

See docs/multi-tenancy.md.

Source code in `src/zeython/tenancy.py`

```python
def __init__(self, app: Application, *, resolver: TenantResolver) -> None:
    super().__init__(app)
    self.resolver = resolver
```

### current_tenant_id

```python
current_tenant_id() -> Any | None
```

The current request's resolved tenant ID.

`None` outside a request handled by :class:`TenantMiddleware`, or when the resolver returned nothing for this request -- in either case, `Model` query methods apply no tenant filter at all (not "filter to tenant None"), the same way an unauthenticated request has no locale override and just gets the default. A background job or script that needs tenant scoping sets it explicitly with :func:`as_tenant`.

Source code in `src/zeython/tenancy.py`

```python
def current_tenant_id() -> Any | None:
    """The current request's resolved tenant ID.

    ``None`` outside a request handled by :class:`TenantMiddleware`, or
    when the resolver returned nothing for this request -- in either case,
    ``Model`` query methods apply no tenant filter at all (not "filter to
    tenant None"), the same way an unauthenticated request has no locale
    override and just gets the default. A background job or script that
    needs tenant scoping sets it explicitly with :func:`as_tenant`.
    """
    return _current_tenant_id.get()
```

### as_tenant

```python
as_tenant(tenant_id: Any) -> Iterator[None]
```

Scope every `Model` query inside this block to `tenant_id` -- for a job, a script, or a test that has no request (and therefore no :class:`TenantMiddleware`) to resolve one from::

```text
with as_tenant(tenant.id):
    posts = await Post.all()   # only this tenant's rows
```

Source code in `src/zeython/tenancy.py`

```python
@contextmanager
def as_tenant(tenant_id: Any) -> Iterator[None]:
    """Scope every ``Model`` query inside this block to ``tenant_id`` --
    for a job, a script, or a test that has no request (and therefore no
    :class:`TenantMiddleware`) to resolve one from::

        with as_tenant(tenant.id):
            posts = await Post.all()   # only this tenant's rows
    """
    token = _current_tenant_id.set(tenant_id)
    try:
        yield
    finally:
        _current_tenant_id.reset(token)
```

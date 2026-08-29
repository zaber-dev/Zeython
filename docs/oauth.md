# OAuth2 / OIDC Login (SSO)

`zeython.oauth` adds "Sign in with Google/GitHub/Microsoft/your own
identity provider" alongside (or instead of) the password-based session
login you already have (see [Authentication](authentication.md)): a user
is sent to the provider's own login page, comes back with proof of who
they are, and your app decides what to do with that -- create an account,
log into an existing one, or reject it.

No new dependency — the framework already ships `httpx` (used for
[webhook delivery](webhooks.md)), reused here for the same two-request
job: exchange a code for a token, then fetch a profile.

## Why this exists

Enterprise customers expect to sign in with the identity provider their
organization already manages (Okta, Azure AD, a custom OIDC provider),
and everyone else increasingly expects "Continue with Google" over yet
another password to remember. Both are the same protocol underneath —
OAuth2's authorization code flow, OIDC just standardizing what the
profile response looks like — so one module covers both.

Built for confidential (server-side) clients only: your app holds a
client secret the browser never sees, so there's no PKCE dance here —
that exists to protect a client that *can't* keep a secret (a mobile app,
a browser-only SPA), which a Zeython app isn't. The security control that
does apply is the `state` parameter, and it's mandatory: a random token
stashed in the session before the redirect, checked (then discarded, so
it can't be replayed) when the provider calls back. Skip it and a
malicious site can trick a victim's browser into completing *your* login
flow with *the attacker's* account — a real, named class of OAuth
vulnerability (login CSRF), not a theoretical one.

## Setup

```python
# main.py
from zeython import Application, AuthServiceProvider, OAuthServiceProvider, oauth_google

from app.Models.user import User

app = Application()
app.register(AuthServiceProvider(app, user_model=User))  # the session `state` lives in
app.register(OAuthServiceProvider(app, providers=[
    oauth_google(
        client_id=app.config.get("oauth.google.client_id"),
        client_secret=app.config.get("oauth.google.client_secret"),
        redirect_uri="https://app.example.com/auth/google/callback",
    ),
]))
```

A generated project already has this wired up but commented out (both
here and in `routes/web.py`) -- it needs real credentials before it can do
anything, so there's no safe zero-config default the way
[MFA](mfa.md) has. Uncomment once you've registered an app with the
provider and have a `client_id`/`client_secret`.

`redirect_uri` must **exactly** match what's registered in the provider's
own console -- not derived from the incoming request's `Host` header,
deliberately: trusting that would let a spoofed header redirect a stolen
authorization code somewhere else entirely.

## Routes

```python
# routes/web.py
app.get("/auth/{provider}/redirect", name="auth.oauth_redirect")(auth.oauth_redirect)
app.get("/auth/{provider}/callback", name="auth.oauth_callback")(auth.oauth_callback)
```

```python
# app/Controllers/auth_controller.py
from zeython.oauth import oauth_callback as complete_oauth_login
from zeython.oauth import oauth_redirect as start_oauth_redirect

async def oauth_redirect(self, request):
    return start_oauth_redirect(request, request.path_params["provider"])

async def oauth_callback(self, request):
    identity = await complete_oauth_login(request, request.path_params["provider"])
    if not identity.email:
        raise BadRequestException("This provider did not share an email address.")

    user = await User.first_where(email=identity.email)
    if user is None:
        user = User(email=identity.email, name=identity.name or identity.email)
        user.set_password(secrets.token_urlsafe(32))  # unusable -- this account only logs in via OAuth
        await user.save()

    login(request, user)
    return JSONResponse(user.to_dict())
```

That's the whole integration: `{provider}` in the URL is whichever
`name=` you gave a provider in `OAuthServiceProvider(providers=[...])`
(`"google"`, `"github"`, or whatever you passed to
[`generic_oidc()`](#enterprise-sso-generic_oidc)). Like Laravel
Socialite, the module hands you a normalized identity and stops there --
finding or creating your own `User` from it is two lines you write once,
not a schema the framework imposes on you. Linking several providers to
one account, requiring an existing password-based account before OAuth
can attach to it, denying sign-up entirely and only allowing OAuth
*login* -- all of that is a few lines' difference in this same handler,
not a framework limitation.

## Supported providers

```python
from zeython import oauth_generic_oidc, oauth_github, oauth_google, oauth_microsoft

oauth_google(client_id=..., client_secret=..., redirect_uri=...)
oauth_github(client_id=..., client_secret=..., redirect_uri=...)
oauth_microsoft(client_id=..., client_secret=..., redirect_uri=..., tenant="common")
```

- **Google** — [Google Cloud Console](https://console.cloud.google.com/apis/credentials).
  Default scope `openid email profile`.
- **GitHub** — [OAuth Apps](https://github.com/settings/developers). Default
  scope `read:user user:email`. GitHub only shares an email if the user has
  a public one *or* granted `user:email`; if the profile response has none,
  the module transparently falls back to `/user/emails` and picks the
  primary one -- you don't need to handle that yourself.
- **Microsoft (Azure AD)** — an
  [app registration](https://learn.microsoft.com/en-us/azure/active-directory/develop/v2-protocols-oidc).
  `tenant` scopes who can sign in: `"common"` (default -- personal *and*
  work/school accounts), `"organizations"` (work/school only), or a
  specific tenant ID/domain to restrict sign-in to one organization.

### Enterprise SSO: `generic_oidc()`

Any standards-compliant OIDC provider -- Okta, Auth0, Keycloak, or an
enterprise customer's own identity provider -- exposing the usual
`sub`/`email`/`name`/`picture` userinfo claims:

```python
oauth_generic_oidc(
    name="okta",
    client_id=...,
    client_secret=...,
    authorize_url="https://your-org.okta.com/oauth2/v1/authorize",
    token_url="https://your-org.okta.com/oauth2/v1/token",
    userinfo_url="https://your-org.okta.com/oauth2/v1/userinfo",
    redirect_uri=...,
)
```

Look these three URLs up once, by hand, from the provider's own
`/.well-known/openid-configuration` discovery document when you set this
up -- not fetched at request time, so a provider's discovery endpoint
being slow or down never affects your login flow.

## What each provider gives you back

`oauth_callback()`/`OAuthManager.handle_callback()` return an `OAuthUser`:
`provider`, `provider_user_id`, `email`, `name`, `avatar_url`,
`access_token`, and `raw` (the provider's full userinfo response, for
anything not already surfaced). Every provider is reached through its
**userinfo endpoint** (an authenticated HTTPS request), not by decoding an
OIDC `id_token` -- that avoids needing a JWT/JWKS-verification dependency
for information the userinfo endpoint already hands over just as
reliably.

`email` can be `None` -- decide for yourself whether that's acceptable
(the worked example above rejects it with a 400; you might instead let
the user pick a local email on first login).

## Errors

- **Unknown provider** in the URL -- `NotFoundException` (404). The
  `{provider}` path segment is checked against exactly what you registered.
- **Missing or mismatched `state`** -- `ForbiddenException` (403): either
  a CSRF attempt, or the login simply took too long and the session-stored
  state expired along with the session. State is popped from the session
  on first use, so replaying an old, already-completed callback URL fails
  the same way.
- **No authorization code** in the callback -- `BadRequestException`
  (400), with the provider's own `error`/`error_description` in the
  message (most commonly: the user clicked "Deny" on the consent screen).

## API reference

See [`zeython.oauth`](reference/security.md) for the full class/function
list, including `OAuthManager`/`OAuthProvider`/`OAuthUser` if you need to
resolve or construct these directly outside of a request (a script that
refreshes cached profile data, say).

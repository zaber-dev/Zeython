# SAML SSO

`zeython.saml` adds "Sign in with Okta/Azure AD/ADFS/your enterprise IdP" via the SAML 2.0 protocol -- for the identity providers, and the enterprise customers who require them, that specifically need SAML rather than [OAuth2/OIDC](https://zeython.zaber.dev/docs/oauth/index.md). Both modules give back the same shape of thing (a normalized identity, not an opinion about your `User` model), so they sit side by side in one app and share the same find-or-create-a-user callback.

Built on [python3-saml](https://github.com/SAML-Toolkits/python3-saml) (OneLogin's toolkit), an optional dependency:

```bash
pip install zeython[saml]
```

## Why this exists, and why it's a separate module from OAuth

Plenty of enterprise IdPs speak OIDC today, but SAML is still what a lot of established identity providers (classic Okta/OneLogin/ADFS deployments, many university and government SSO setups) default to, and what an enterprise customer's security team sometimes mandates by policy regardless of what else you support. It's a meaningfully different protocol -- XML, not JSON; the security-critical direction is the IdP's **signed** response, verified with its public certificate, not a bearer-token exchange -- so it isn't a thin variant of `zeython.oauth`, it's its own protocol with its own module. `python3-saml` does the actual XML work (building the AuthnRequest, verifying the Response's XML signature, checking expiry/audience/recipient); Zeython wraps that in an async, container-bound `SamlManager`.

## Setup

```python
# main.py
from zeython import Application, AuthServiceProvider, SamlServiceProvider, saml_provider

from app.Models.user import User

app = Application()
app.register(AuthServiceProvider(app, user_model=User))  # for login() your ACS route calls
app.register(SamlServiceProvider(app, providers=[
    saml_provider(
        name="okta",
        idp_entity_id="http://www.okta.com/exk1a2b3c4d5e6f7g8h9",
        idp_sso_url="https://your-org.okta.com/app/your-org_app_1/exk.../sso/saml",
        idp_x509_cert=app.config.get("saml.okta.idp_cert"),
        sp_entity_id="https://app.example.com/saml/okta/metadata",
        acs_url="https://app.example.com/saml/okta/acs",
    ),
]))
```

Everything in `saml_provider(...)` beyond `name=`/`acs_url=` comes from your IdP admin's console: entity ID, SSO URL, and the certificate it signs assertions with. `acs_url` -- your app's Assertion Consumer Service, where the IdP posts its signed response back to -- is the one value that flows the other way: you decide it, then register it (along with `sp_entity_id`) at the IdP. Both must be **exact, absolute** URLs; SAML validates the request's actual destination/audience against them.

## Routes

Unlike `zeython.oauth`'s `oauth_redirect`/`oauth_callback`, there's no generated project wiring to uncomment here (SAML setups vary too much IdP-to-IdP to have one commented-out default) -- add the three routes yourself:

```python
# routes/web.py
app.get("/saml/{provider}/login", name="saml.login")(auth.saml_login)
app.post("/saml/{provider}/acs", name="saml.acs")(auth.saml_acs)
app.get("/saml/{provider}/metadata", name="saml.metadata")(auth.saml_metadata)
```

```python
# app/Controllers/auth_controller.py
from starlette.responses import RedirectResponse
from zeython.saml import saml_acs as complete_saml_login
from zeython.saml import saml_login as start_saml_login
from zeython.saml import saml_metadata as serve_saml_metadata

async def saml_login(self, request):
    return start_saml_login(request, request.path_params["provider"])

async def saml_acs(self, request):
    identity = await complete_saml_login(request, request.path_params["provider"])
    if not identity.email:
        raise BadRequestException("This IdP did not send an email address.")

    user = await User.first_where(email=identity.email)
    if user is None:
        user = User(email=identity.email, name=identity.name or identity.email)
        user.set_password(secrets.token_urlsafe(32))  # unusable -- this account only logs in via SAML
        await user.save()

    login(request, user)
    return RedirectResponse("/", status_code=303)

async def saml_metadata(self, request):
    return await serve_saml_metadata(request, request.path_params["provider"])
```

`{provider}` is whichever `name=` you gave a provider in `SamlServiceProvider(providers=[...])` (`"okta"` above). The ACS route must accept `POST` -- that's how the IdP delivers the signed assertion, never a redirect with a query string the way OAuth's callback works.

### Handing the IdP your SP metadata

Most IdP admin consoles offer "upload metadata XML" or "enter these values by hand" as alternatives -- point them at your `/saml/{provider}/ metadata` route instead of copying entity ID/ACS URL/certificate into separate fields one at a time:

```bash
curl https://app.example.com/saml/okta/metadata
```

## What you get back

`saml_acs()`/`SamlManager.handle_acs()` return a `SamlUser`: `name_id` (the subject identifier the IdP asserts -- an email address, in the default `NameIDFormat`), `email`, `name`, `attributes` (everything the assertion included, as `dict[str, list[str]]`), and `session_index` (for [Single Logout](#what-this-isnt), if you add it later).

There's no universal attribute-naming standard the way OIDC's userinfo claims are -- an IdP admin configures which attribute names an assertion sends, often a URN (`http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress`) or a short name (`email`), and it varies by IdP and by how that IdP's admin set it up. `SamlUser.email`/`.name` recognize a handful of common names automatically; when your IdP sends something else, tell `saml_provider()`:

```python
saml_provider(
    ...,
    email_attribute="http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
    name_attribute="displayName",
)
```

For anything beyond email/name, read it straight off the assertion:

```python
department = identity.attribute("department")
groups = identity.attributes.get("groups", [])  # every value, not just the first
```

## Signing outgoing requests (optional)

By default, the AuthnRequest Zeython sends to the IdP is unsigned -- which most IdPs accept for SP-initiated login, since the security-critical direction is the IdP's own signed *response*, always required. Some IdPs require signed requests too; give `saml_provider()` your SP's own certificate and private key to enable it:

```python
saml_provider(
    ...,
    sp_x509_cert=app.config.get("saml.sp_cert"),
    sp_private_key=app.config.get("saml.sp_key"),
)
```

## Replay protection

A signed, still-valid SAMLResponse is, cryptographically, exactly as valid the second time it's submitted as the first -- signature checking alone doesn't stop a network observer (or a buggy IdP integration) from resubmitting one it captured. `SamlManager` tracks every assertion ID it accepts and rejects a second callback presenting the same one:

```python
app.register(SamlServiceProvider(
    app,
    providers=[...],
    replay_window=300.0,  # seconds an assertion ID is remembered -- the default
))
```

Tracked in its own process-local `InMemoryCache` by default, the same in-process-only limitation [`RateLimiter`](https://zeython.zaber.dev/docs/rate-limiting/index.md) and [`Cache`](https://zeython.zaber.dev/docs/caching/index.md) already document — pass `replay_cache=` (a [`RedisCache`](https://zeython.zaber.dev/docs/redis/index.md)) to share it across every process/machine instead of each one only remembering what it itself has seen:

```python
from zeython import RedisCache, SamlServiceProvider

app.register(SamlServiceProvider(
    app,
    providers=[...],
    replay_cache=RedisCache(app.config.get("redis.url")),
))
```

## Errors

- **Unknown provider** in the URL -- `NotFoundException` (404), the same as an unknown OAuth provider name.
- **No `SAMLResponse`** in the ACS POST body -- `BadRequestException` (400): the IdP (or whoever's calling this URL) didn't send one.
- **Response failed validation, or already used once** -- `ForbiddenException` (403): a missing/invalid signature, an expired assertion, a response meant for a different SP (wrong audience), one delivered to the wrong URL (wrong recipient/destination), or an assertion ID this SP has already accepted (see "Replay protection" above). The exception message names which of python3-saml's own validation errors fired, and its detailed reason.

## What this isn't

Service-provider-initiated login and IdP-initiated login (an IdP's admin console sending an unsolicited assertion -- common from a "test connection" button) both land at the same ACS route and validate the same way. What's **not** here:

- **Single Logout (SLO)** -- ending the IdP's own session when a user logs out of your app, or vice versa. `SamlUser.session_index` is captured for when you need to add it (`python3-saml`'s `OneLogin_Saml2_Auth.logout()`/ `process_slo()` cover the protocol), but Zeython doesn't wire it up itself -- most apps get by with a local logout only.
- **SAML assertion/response encryption** -- signing (authenticity) is supported and always required; encryption (confidentiality, on top of TLS) is a `python3-saml` setting this module doesn't expose yet.
- **IdP-side (identity provider) SAML** -- this module is a Service Provider (SP) only, for signing *into* your app via someone else's IdP, not for turning your app into an IdP other services sign into.

## API reference

See [`zeython.saml`](https://zeython.zaber.dev/docs/reference/security/index.md) for the full class/function list, including `SamlManager`/`SamlProvider`/`SamlUser` if you need to resolve or construct these directly outside of a request.

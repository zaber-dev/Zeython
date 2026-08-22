# CSRF Protection

A browser attaches cookies to a request automatically — even one triggered
by a page on a completely different site. That's exactly what session-cookie
auth ([Authentication](authentication.md)) relies on, and exactly what
makes it forgeable without protection: a malicious page can trigger a
`POST` to your app and the victim's session cookie rides along, no user
interaction beyond "visited a page" required. `CsrfMiddleware` closes that
gap, and it's on by default the moment you register `AuthServiceProvider`.

(This covers `POST`/`PUT`/`PATCH`/`DELETE` over HTTP specifically. A
WebSocket handshake is *also* a plain HTTP request that carries cookies
automatically -- see [WebSockets: Origin protection](websockets.md#origin-protection)
for the equivalent guard there.)

## The double-submit-cookie pattern

A random token is set as a *readable* (non-`HttpOnly`) cookie. Any unsafe
request (`POST`, `PUT`, `PATCH`, `DELETE`) must also send that same value
back in a header (`X-CSRF-Token` by default). A cross-site attacker's page
can trigger the cookie to be sent automatically, but can't *read* its
value — the same-origin policy blocks that — so it can't also set the
matching header. A forged request is missing the header, or has the wrong
value, and gets rejected with a `403`.

```bash
curl -i http://localhost:8000/          # any response sets the csrf_token cookie
curl -X POST http://localhost:8000/posts \
  -b cookies.txt \
  -H "X-CSRF-Token: <value of the csrf_token cookie>" \
  -d '{"title": "..."}'
```

## From a browser/JS client

Read the cookie directly — no server round trip needed to fetch a token
separately:

```js
function csrfToken() {
  return document.cookie
    .split("; ")
    .find((row) => row.startsWith("csrf_token="))
    ?.split("=")[1];
}

fetch("/posts", {
  method: "POST",
  headers: { "X-CSRF-Token": csrfToken(), "Content-Type": "application/json" },
  body: JSON.stringify({ title: "..." }),
  credentials: "same-origin",
});
```

!!! warning "The first request from a new client must be a safe one"
    The **first** unsafe request after a client has never talked to your
    app before will fail — there's no cookie to read yet. Make any safe
    (`GET`) request first (loading the page itself counts), the same way
    Django's and Laravel's equivalents work.

## What's exempt

- **Safe methods** (`GET`/`HEAD`/`OPTIONS`/`TRACE`) — they never change
  state, so there's nothing to forge.
- **Requests carrying an `Authorization` header** — a bearer token
  ([API Authentication](api-authentication.md)) isn't attached to
  cross-site requests automatically the way a cookie is, so it was never
  vulnerable to this in the first place. `/api/token` and every
  `require_api_auth`-guarded route work exactly as before.
- **Requests with no session cookie at all**, when wired via
  `AuthServiceProvider` (see below) — CSRF only matters when there's an
  existing cookie-authenticated session to forge an action *within*. A
  request with no session cookie yet (a brand new client's very first
  `POST /register`) has nothing ambient for a forged request to ride on.

## Setup

Comes bundled with `AuthServiceProvider` — nothing extra to register:

```python
# main.py
from zeython import Application, AuthServiceProvider

app = Application()
app.register(AuthServiceProvider(app, user_model=User))
```

Configurable via `.env`:

- `CSRF_ENABLED` — default `true`.
- `CSRF_COOKIE_NAME` — default `csrf_token`.
- `CSRF_HEADER_NAME` — default `X-CSRF-Token`.

!!! danger "Think twice before setting CSRF_ENABLED=false"
    Turning it off is rarely the right call, since it's exactly what makes
    cookie-based auth safe to use from a browser — a pure mobile/native
    client that never runs in a browser context is the one legitimate
    reason to.

Using `CsrfMiddleware` standalone, without `AuthServiceProvider` (a
generic double-submit-cookie check with no auth-awareness, protecting
every unsafe request unconditionally):

```python
from zeython.csrf import CsrfMiddleware

app.add_middleware(CsrfMiddleware)
```

## Server-rendered forms

For an app submitting real HTML forms instead of driving everything
through `fetch`, embed the token as a hidden field using `csrf_token(request)`:

```python
from zeython.csrf import csrf_token

@app.get("/posts/new")
async def new_post_form(request):
    return render(request, "posts/new.html", {"csrf_token": csrf_token(request)})
```

```html
<form method="post" action="/posts">
  <input type="hidden" name="csrf_token" value="{{ csrf_token }}" />
  ...
</form>
```

(`CsrfMiddleware` reads the token from the header, not a form field — pair
this with a tiny bit of JS that copies the hidden field's value into the
`X-CSRF-Token` header on submit, or submit via `fetch` instead of a plain
form `action` for state-changing routes.)

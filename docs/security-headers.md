# Security Headers

A handful of HTTP response headers tell the browser to lock down behavior
that's otherwise wide open: don't let another site frame this page, don't
guess a response's content type, don't leak the full URL on a cross-origin
navigation, don't restrict which scripts/styles/assets a page is allowed to
load. `SecurityHeadersMiddleware` adds them; `SecurityHeadersServiceProvider`
wires it up from `.env`.

!!! warning "Not registered by default"
    Unlike [CSRF protection](csrf.md) or the
    [WebSocket Origin check](websockets.md#origin-protection). The headers
    with a real default here (`X-Frame-Options`, `X-Content-Type-Options`,
    `Referrer-Policy`) are safe to turn on for any app, but
    `Content-Security-Policy` genuinely isn't — a policy this framework
    picked for you would either be loose enough to be pointless, or break
    your own inline scripts, your own CDN-loaded assets, or the Swagger UI
    at `/docs`. Register the provider once you've decided what your own
    policy actually is.

## Setup

```python
# main.py
from zeython import Application, SecurityHeadersServiceProvider

app = Application()
app.register(SecurityHeadersServiceProvider)
```

Configurable via `.env`:

- `SECURITY_HEADERS_CSP` — your `Content-Security-Policy` value. Unset by
  default; no `Content-Security-Policy` header is sent at all until you
  provide one.
- `SECURITY_HEADERS_FRAME_OPTIONS` — default `DENY` (this app can't be
  framed by another site at all — clickjacking). Set to `SAMEORIGIN` if you
  legitimately frame your own pages from your own pages.
- `SECURITY_HEADERS_CONTENT_TYPE_OPTIONS` — default `true`, sends
  `X-Content-Type-Options: nosniff`. Stops a browser from "sniffing" a
  response's content and running it as something other than its declared
  `Content-Type` — the classic case is an uploaded file served back and
  executed as HTML instead of staying inert.
- `SECURITY_HEADERS_REFERRER_POLICY` — default
  `strict-origin-when-cross-origin`: the full URL is sent as the `Referer`
  on a same-origin navigation, only the origin cross-origin, and nothing at
  all on a downgrade from HTTPS to plain HTTP.
- `SECURITY_HEADERS_HSTS` — default `false`. Sends
  `Strict-Transport-Security` once enabled, telling the browser to refuse
  plain HTTP for this host for `SECURITY_HEADERS_HSTS_MAX_AGE` seconds
  going forward — including on a link the user typed themselves.
- `SECURITY_HEADERS_HSTS_MAX_AGE` — default `31536000` (1 year).

!!! danger "HSTS is hard to undo once a client has seen it"
    Only turn this on once every path to this app is actually served over
    HTTPS. There's no clean way to undo it before the max-age expires for
    a client that's already seen the header — they'll refuse plain HTTP
    to this host for the full duration, no matter what you change server-side.

## Using the middleware directly

Registering via `Application.add_middleware` skips config entirely — useful
in tests, or if you'd rather set values in code:

```python
from zeython.security_headers import SecurityHeadersMiddleware

app.add_middleware(
    SecurityHeadersMiddleware,
    content_security_policy="default-src 'self'",
    hsts=True,
)
```

Pass `None`/`False` to omit a header entirely rather than send an empty
one — `frame_options=None`, `content_type_options=False`, and
`referrer_policy=None` all work.

## Verifying it

```bash
curl -sI http://localhost:8000/ | grep -Ei '^(x-frame-options|x-content-type-options|referrer-policy|content-security-policy|strict-transport-security):'
```

With the provider unregistered, none of these appear at all — every
response is exactly what it would have been without this module.

# API Standards

Three small, independent, opt-in pieces that come up on most enterprise-readiness checklists for an HTTP API: response compression, conditional requests, and a standard error body shape. None of these are registered by default — each is a single `app.register(...)` line once you want it.

## Compression (gzip)

```python
# main.py
from zeython import Application, GzipServiceProvider

app = Application()
app.register(GzipServiceProvider)
```

A thin, `.env`-configurable wrapper over Starlette's own `GZipMiddleware` — compresses any response at or above a minimum size whose client sent `Accept-Encoding: gzip`. Configurable via `.env`:

- `GZIP_MINIMUM_SIZE` — default `500` bytes. Below this, the CPU cost of compressing isn't worth it.
- `GZIP_COMPRESS_LEVEL` — default `9` (Starlette's own default; `1` is fastest/least compression, `9` slowest/most).

## Conditional requests (ETags)

```python
# main.py
from zeython import Application, ETagServiceProvider

app = Application()
app.register(ETagServiceProvider)
```

Adds an `ETag` header (a SHA-256 hash of the body) to every `200` response to a `GET`/`HEAD` request, and short-circuits to `304 Not Modified` (empty body) when the request's `If-None-Match` already matches it — for a resource that doesn't change on every request (a list endpoint between writes, a lookup table), the client skips re-downloading a body it already has.

```bash
curl -sI http://localhost:8000/posts | grep -i etag
# ETag: "3f2504e047ad..."

curl -sI http://localhost:8000/posts -H 'If-None-Match: "3f2504e047ad..."'
# HTTP/1.1 304 Not Modified
```

Configurable via `.env`:

- `ETAG_MINIMUM_SIZE` — default `0` (every `200` response gets an ETag). Raise it to skip hashing tiny responses that aren't worth caching.

**Buffers the entire response body in memory** to compute the hash — a reasonable trade-off for a typical JSON API response, a poor fit in front of a large file download or a genuinely streamed response. Don't run this middleware in front of a download endpoint; use [`zeython.storage`](https://zeython.zaber.dev/docs/storage/index.md) for those instead, which serves files without buffering their full contents through the app.

## RFC 7807 error responses (`application/problem+json`)

Zeython's default error body —

```json
{"error": "The requested resource was not found.", "status": 404}
```

— is deliberately simple. `API_PROBLEM_JSON=true` switches every error response (from `HTTPException` subclasses and unhandled exceptions alike) to [RFC 7807](https://www.rfc-editor.org/rfc/rfc7807)'s `problem+json` shape instead, for a client or API gateway that specifically expects it:

```bash
# .env
API_PROBLEM_JSON=true
```

```text
Content-Type: application/problem+json

{
  "type": "about:blank",
  "title": "Not Found",
  "status": 404,
  "detail": "The requested resource was not found."
}
```

`type` is always `"about:blank"` — RFC 7807's own fallback meaning "no problem type more specific than the HTTP status code itself," since Zeython doesn't maintain a registry of per-error-type URIs. `title` is the standard HTTP status phrase. A `ValidationException`'s field errors still show up, as an `errors` extension member (same shape as the default format uses) — RFC 7807 explicitly permits extending the problem object this way:

```json
{
  "type": "about:blank",
  "title": "Unprocessable Entity",
  "status": 422,
  "detail": "The given data was invalid.",
  "errors": {"email": ["is required"]}
}
```

`APP_DEBUG=true` still adds `exception` and `traceback` extension members to a 500's body, the same as the default format does.

This is a single global switch, not a per-route choice — pick one error format for the whole API. Off by default, since it changes the shape of every error response and would be a breaking change for anything already parsing the default `{"error": ..., "status": ...}` shape.

## Debug mode: a browsable HTML error page

`APP_DEBUG=true` doesn't just add `exception`/`traceback` to the JSON body above — a browser hitting a route that raises an unhandled exception gets a full Laravel/Django-style debug page instead: the exception, the request line, and every stack frame with a source-code snippet around the line that raised, most relevant frame first.

Which response you get is decided per-request, by the `Accept` header, not by a global switch: a browser's default `Accept` lists `text/html`, so it gets the HTML page; an API/fetch client (Postman, `curl`, your own HTTP client) doesn't, so it still gets the plain JSON (or `problem+json`) shape above — a frontend's error-handling code never has to special-case an HTML body just because `APP_DEBUG` happens to be on. `API_PROBLEM_JSON=true` always wins over the HTML page, on the assumption that an app with it turned on is API-only.

Only ever shown for a genuine unhandled exception (a bug), never for an `HTTPException` your own code raised deliberately (`NotFoundException`, `ValidationException`, ...) — those keep returning their normal JSON body regardless of `Accept`, since they're expected control flow, not a crash.

Like every other debug-mode behavior, this leaks source code and file paths — see the [production checklist](https://zeython.zaber.dev/docs/production-checklist/index.md) for why `APP_DEBUG=false` is non-negotiable in production.

If [`RequestProfilerServiceProvider`](https://zeython.zaber.dev/docs/profiling/index.md) is registered, both the HTML page and the JSON/`problem+json` bodies also show the queries the crashed request ran before it failed — often the fastest way to see *why*.

## API versioning

`Router.version()` groups a set of routes under a version prefix, so you can change an endpoint's behavior without breaking clients still calling the old one:

```python
# main.py
from zeython import Application, current_api_version
from app.Controllers.post_controller_v1 import PostControllerV1
from app.Controllers.post_controller_v2 import PostControllerV2

app = Application()

with app.router.version("v1") as v1:
    v1.resource("/posts", PostControllerV1)

with app.router.version("v2") as v2:
    v2.resource("/posts", PostControllerV2)
```

`"v1"` mounts routes at `/v1` by default — pass `prefix=` to use something else (`app.router.version("v1", prefix="/api/v1")`), or `prefix=""` to version routes without changing their path at all (useful if the version is instead read from an `Accept` header or a path param your own code inspects).

**Build the whole group inside the `with` block** — `version()` folds the sub-router's routes into the parent only once the block exits, so a route registered after the block closes is never picked up:

```python
with app.router.version("v1") as v1:
    v1.get("/reports")(list_reports)
# too late -- v1 has already been folded into app.router by here
v1.get("/exports")(list_exports)  # never registered, don't do this
```

Inside a handler routed through a version group, `current_api_version()` returns the version label — `None` outside one, so existing unversioned routes and application code that doesn't care about versioning are unaffected:

```python
from zeython import current_api_version

async def index(request):
    if current_api_version() == "v1":
        ...  # the old response shape, kept for existing v1 clients
    return JSONResponse([...])
```

This also works for `resource()` and `websocket()`, not just `get()`/ `post()`/etc. — every registration method on a versioned `Router` wraps its handler the same way.

### Deprecating an old version

`deprecated()` marks a single endpoint deprecated with the standard [`Deprecation`](https://datatracker.ietf.org/doc/html/draft-dalal-deprecation-header) and [`Sunset`](https://www.rfc-editor.org/rfc/rfc8594) response headers, so well-behaved clients and API gateways can flag it automatically:

```python
from zeython import deprecated

with app.router.version("v1") as v1:

    @v1.get("/reports")
    @deprecated(sunset="Wed, 01 Jan 2027 00:00:00 GMT")
    async def list_reports(request):
        return JSONResponse([...])
```

Every response from `list_reports` now carries `Deprecation: true`, and `Sunset: Wed, 01 Jan 2027 00:00:00 GMT` naming when it stops working entirely. `sunset` is optional — omit it to signal "deprecated, no removal date set yet."

# API Standards

Three small, independent, opt-in pieces that come up on most
enterprise-readiness checklists for an HTTP API: response compression,
conditional requests, and a standard error body shape. None of these are
registered by default — each is a single `app.register(...)` line once
you want it.

## Compression (gzip)

```python
# main.py
from zeython import Application, GzipServiceProvider

app = Application()
app.register(GzipServiceProvider)
```

A thin, `.env`-configurable wrapper over Starlette's own `GZipMiddleware`
— compresses any response at or above a minimum size whose client sent
`Accept-Encoding: gzip`. Configurable via `.env`:

- `GZIP_MINIMUM_SIZE` — default `500` bytes. Below this, the CPU cost of
  compressing isn't worth it.
- `GZIP_COMPRESS_LEVEL` — default `9` (Starlette's own default; `1` is
  fastest/least compression, `9` slowest/most).

## Conditional requests (ETags)

```python
# main.py
from zeython import Application, ETagServiceProvider

app = Application()
app.register(ETagServiceProvider)
```

Adds an `ETag` header (a SHA-256 hash of the body) to every `200`
response to a `GET`/`HEAD` request, and short-circuits to `304 Not
Modified` (empty body) when the request's `If-None-Match` already
matches it — for a resource that doesn't change on every request (a list
endpoint between writes, a lookup table), the client skips
re-downloading a body it already has.

```bash
curl -sI http://localhost:8000/posts | grep -i etag
# ETag: "3f2504e047ad..."

curl -sI http://localhost:8000/posts -H 'If-None-Match: "3f2504e047ad..."'
# HTTP/1.1 304 Not Modified
```

Configurable via `.env`:

- `ETAG_MINIMUM_SIZE` — default `0` (every `200` response gets an ETag).
  Raise it to skip hashing tiny responses that aren't worth caching.

**Buffers the entire response body in memory** to compute the hash — a
reasonable trade-off for a typical JSON API response, a poor fit in front
of a large file download or a genuinely streamed response. Don't run this
middleware in front of a download endpoint; use
[`zeython.storage`](storage.md) for those instead, which serves files
without buffering their full contents through the app.

## RFC 7807 error responses (`application/problem+json`)

Zeython's default error body —

```json
{"error": "The requested resource was not found.", "status": 404}
```

— is deliberately simple. `API_PROBLEM_JSON=true` switches every error
response (from `HTTPException` subclasses and unhandled exceptions alike)
to [RFC 7807](https://www.rfc-editor.org/rfc/rfc7807)'s `problem+json`
shape instead, for a client or API gateway that specifically expects it:

```bash
# .env
API_PROBLEM_JSON=true
```

```
Content-Type: application/problem+json

{
  "type": "about:blank",
  "title": "Not Found",
  "status": 404,
  "detail": "The requested resource was not found."
}
```

`type` is always `"about:blank"` — RFC 7807's own fallback meaning "no
problem type more specific than the HTTP status code itself," since
Zeython doesn't maintain a registry of per-error-type URIs. `title` is
the standard HTTP status phrase. A `ValidationException`'s field errors
still show up, as an `errors` extension member (same shape as the
default format uses) — RFC 7807 explicitly permits extending the problem
object this way:

```json
{
  "type": "about:blank",
  "title": "Unprocessable Entity",
  "status": 422,
  "detail": "The given data was invalid.",
  "errors": {"email": ["is required"]}
}
```

`APP_DEBUG=true` still adds an `exception` extension member to a 500's
body, the same as the default format does.

This is a single global switch, not a per-route choice — pick one error
format for the whole API. Off by default, since it changes the shape of
every error response and would be a breaking change for anything already
parsing the default `{"error": ..., "status": ...}` shape.

# AGENTS.md

Guidance for AI coding agents (Claude Code, Cursor, Copilot Workspace, etc.)
working in a Zeython codebase — either the framework itself, or an application
built with it.

## What Zeython is

An async-first MVC framework: ASGI (Starlette) + async SQLAlchemy 2.0, a
dependency injection container, a service-provider boot lifecycle, and a
`zeython` CLI. Full details: [docs/architecture.md](docs/architecture.md).

## If you have MCP tool access

Zeython ships its own MCP server (`zeython mcp`, requires the `mcp` extra).
If it's connected, prefer `list_routes`/`list_models`/`app_info` over
grepping `routes/web.py` or `app/Models/*.py` by hand — they reflect the
project's actual registered routes and mapped schema, not what the source
*looks like* it does. Prefer `search_docs` over recalling a Zeython API
from training data; it searches the docs bundled with the exact installed
framework version. See [docs/ai-agents.md](docs/ai-agents.md).

## If you're working in the framework itself (`src/zeython/`)

- Read `docs/architecture.md` first — it explains the container/provider/router
  relationship; don't guess at it from file names.
- Every public API needs type hints. `mypy src/zeython` must pass with zero
  errors before you're done.
- Add or update tests in `tests/` for any behavior change. `pytest` must pass.
- Run `ruff check src tests` — fix, don't suppress, unless there's a real
  reason (document it with a `# noqa: CODE` and a one-line comment why).
- `src/zeython/cli/templates/starter/` is copied verbatim by `zeython new` and
  is **not** type-checked or linted as part of the package (see the `exclude`
  entries in `pyproject.toml`) — those files run in a *generated project's*
  context, not the framework's. If you touch them, verify by hand:
  ```bash
  pip install -e .
  zeython new "Agent Smoke Test" --path /tmp/agent-smoke-test
  cd /tmp/agent-smoke-test && cp .env.example .env && pip install -e ".[dev]"
  python -m alembic revision --autogenerate -m x && python -m alembic upgrade head
  pytest
  ```
- Don't add a dependency to `pyproject.toml` for something solvable in a few
  lines of stdlib. The framework's value is a small, trustworthy core.

## If you're working in an application built with Zeython

- Models go in `app/Models/`, subclass `zeython.Model`, and get registered in
  `app/Models/__init__.py` (so Alembic autogenerate can see them). Use
  `zeython make model <Name>` rather than hand-rolling this.
- Relationships are plain SQLAlchemy `relationship()` — no framework wrapper
  needed to define one. Loading is where it matters: NEVER touch a
  relationship attribute you didn't fetch with `include=("name",)` (on
  `find`/`all`/`find_by`/`first_where`) — it raises `MissingGreenlet` in
  async code, not a normal lazy load. Same rule for `to_dict()`: pass
  `include=` only for relationships you eager-loaded, or it raises a clear
  `RuntimeError` telling you so (better than `MissingGreenlet`, still an
  error). See `docs/relationships.md`.
- Validate on the model, not in the controller: set `__rules__` on the model
  (`docs/validation.md`) instead of hand-checking `request.json()` fields —
  `create()`/`save()`/`update()` already raise `ValidationException` (a 422
  JSON response) for you.
- For behavior that should always run around a save or delete (normalizing
  a field, deriving one, cache invalidation), override the model's
  lifecycle hooks (`creating`/`created`/`updating`/`updated`/`deleting`/
  `deleted`, plus `saving`/`saved` for both create and update) rather than
  repeating that logic in every controller that touches the model.
  `creating()`/`updating()` run *before* `__rules__` validation, so they're
  the right place to derive a field validation then checks. See
  `docs/model-events.md`.
- Server-rendered HTML goes through `zeython.views.render(request, name,
  context)`, reading from `resources/views/` — register `ViewServiceProvider`
  in `main.py` first (`docs/views.md`). Don't hand-roll Jinja2 environments.
- Auth is session-based (`docs/authentication.md`): mix `Authenticatable`
  into your user model for `set_password()`/`check_password()`, register
  `AuthServiceProvider(app, user_model=User)`, and guard routes with
  `await require_auth(request)` (raises 401) or `await current_user(request)`
  (returns `None`). Never hand-roll password hashing — use
  `zeython.hash_password`/`verify_password` (PBKDF2-HMAC-SHA256), and never
  log or serialize a password/hash field — put it in the model's `__hidden__`.
- `AuthServiceProvider` turns on CSRF protection automatically (`docs/csrf.md`)
  — every `POST`/`PUT`/`PATCH`/`DELETE` against a session-authenticated
  route needs the `X-CSRF-Token` header matching the `csrf_token` cookie.
  Don't turn `CSRF_ENABLED` off to make a request "just work" — fix the
  client (read the cookie, send the header) instead; in tests,
  `zeython.testing.client()` already does this automatically once the
  client has made one prior safe (`GET`) request.
- `SecurityHeadersServiceProvider` (`docs/security-headers.md`) adds
  `X-Frame-Options`/`X-Content-Type-Options`/`Referrer-Policy`/CSP/HSTS
  response headers -- unlike CSRF, it is **not** registered by default
  (a wrong `Content-Security-Policy` breaks a legitimate app silently, so
  this framework won't guess one for you). Register it explicitly once
  you've decided on a policy; don't assume a generated project already
  sends these headers.
- Cookie sessions (`require_auth`, `docs/authentication.md`) and bearer
  tokens (`require_api_auth`, `docs/api-authentication.md`) are two
  separate auth paths -- never mix them in one handler, and don't reach
  for token auth by default. Cookies are the right choice for a browser
  client; add `zeython.api_auth` specifically for clients that can't carry
  a cookie jar (a mobile app, a separate SPA, a server-to-server caller).
- "Is anyone logged in" (`require_auth`) is not "can this user do this
  specific thing." For that, define a named ability on `Gate`
  (`gate.define("delete-post", lambda user, post: post.author_id ==
  user.id)`, typically in a provider's `boot()`) and call `await
  authorize(request, "delete-post", post)` at the top of the handler --
  never hand-roll the ownership `if` check inline. See
  `docs/authorization.md`.
- File uploads always go through `zeython.storage.store_upload()`, never
  `open(f"uploads/{upload.filename}", "wb")` or similar — the client's
  filename is untrusted input, and `store_upload()` is what keeps a stored
  key from becoming a path-traversal or overwrite vector. Pass
  `allowed_extensions`/`max_size` explicitly; don't accept arbitrary files
  at an unbounded size. See `docs/storage.md`.
- Any endpoint that checks a credential or secret (login, password reset,
  token verification, invite-code redemption) must call
  `await throttle(request, limit=..., window=...)` from `zeython.rate_limit`
  before doing the check — an unthrottled credential check is a brute-force
  oracle. The generated `AuthController` already does this for
  login/register; carry the same pattern to any auth-adjacent endpoint you
  add. See `docs/rate-limiting.md`.
- Anything that shouldn't block the response (sending an email, calling a
  slow third-party API, generating a report) is a `Job` in `app/Jobs/`,
  dispatched with `await dispatch(request, SomeJob(...))` from
  `zeython.queue` — not awaited inline in the handler. `zeython make job
  <Name>` scaffolds one. Remember the default queue is process-local (a job
  pushed but not yet run is lost on crash/restart) — that's fine for a
  welcome email, not for anything you'd be upset to silently lose. A job's
  `handle()` can declare typed params (e.g. `handle(self, mailer: Mailer)`)
  and get them autowired from the container, same as anywhere else. See
  `docs/queues.md`.
- For a read path worth caching, use `zeython.Cache` (bound in the
  container) rather than hand-rolling a module-level dict: `await
  cache.remember(key, ttl, callback)` covers the common
  check-then-compute-then-store pattern in one call. Remember to
  `cache.forget(key)` wherever the underlying data changes — a cache with
  no invalidation path just serves stale data forever. See
  `docs/caching.md`. Both `Cache` and `RateLimiter` default to in-memory,
  process-local backends; if you're running more than one worker
  process/machine, bind `RedisCache`/`RedisRateLimiter` instead (`pip
  install zeython[redis]`) so cached values and rate-limit counts are
  actually shared, not per-worker. See `docs/redis.md`.
- To call an LLM from app code (not to give an AI agent tools to operate on
  the project itself -- that's `zeython.mcp`, see `docs/ai-agents.md`), use
  `zeython.AI` (bound in the container once `AIServiceProvider` is
  registered): `await ai.complete(prompt, system=...)`. Defaults to
  `EchoAI` (no network, no credentials) until `AI_PROVIDER=anthropic` is
  configured. See `docs/ai.md`.
- A one-off or scheduled script that needs the app's own container/config
  (a data import, a cron-driven cleanup) is a `Command` in
  `app/Console/Commands/`, not a standalone script hand-rolling its own
  `Application()`. `zeython make command <Name>` scaffolds one; run it with
  `zeython command <name>`, list them with `zeython commands`. There's no
  in-process scheduler — point cron (or your platform's equivalent) at the
  command itself. See `docs/console-commands.md`.
- Need realistic model instances for a test, or demo/reference data in the
  database? Write a `Factory` in `database/factories/` (`zeython make
  factory <Model>`) rather than constructing a model by hand in every test
  -- `await SomeFactory().create()` persists one, `.create_many(n)` persists
  several, `.make()` builds one without touching the database. Compose
  factories into a `Seeder` (`database/seeders/`, `zeython make seeder
  <Name>`) and run it with `zeython db seed`. See `docs/database-seeding.md`.
- Send email via `zeython.Mailer`/`Message` (`docs/mail.md`), never
  `smtplib` directly in a handler — and send it from a `Job`
  (`await dispatch(request, ...)`), not inline in the request. `MAIL_DRIVER`
  defaults to `log` (writes to logs, doesn't actually send), which is
  correct for local dev — don't switch it to `smtp` without the user asking.
- Controllers go in `app/Controllers/`, subclass `zeython.Controller`. Methods
  are plain `async def method(self, request) -> Response`. Every route
  already appears at `/docs` (Swagger UI) with a generic response; add
  `@describe(summary=..., tags=[...], request_body=..., responses=...)`
  from `zeython.openapi` to a handler when you want a real one instead of
  the placeholder -- `model_schema(SomeModel)` builds the schema fragment
  from the model's actual columns. See `docs/openapi.md`.
- Routes are wired in `routes/web.py`, imported via `RouteServiceProvider` in
  `main.py`. Function routes use `@app.get(...)`; CRUD resources use
  `app.router.resource("/path", SomeController)`.
- Real-time (chat, live updates, "someone else is editing this") is
  `@app.websocket(path)` in `routes/web.py`, not polling. Handlers receive
  a `WebSocket`, not a `Request` -- `await websocket.receive_text()`/
  `.send_text()`, catch `WebSocketDisconnect`. To reach more than the
  sender, use `WebSocketHub` (bound by default): `hub.connect(websocket)`
  returns a bool -- `if not await hub.connect(websocket): return` before
  doing anything else, then `hub.broadcast(message, exclude=websocket)`,
  and always `hub.disconnect(websocket)` in a `finally` block. Set
  `WEBSOCKET_ALLOWED_ORIGINS` once real browser clients are involved --
  unset, `connect()` accepts every origin (cross-site WebSocket hijacking
  is otherwise possible, the same threat CSRF protects HTTP routes from).
  Set `WEBSOCKET_MAX_CONNECTIONS_PER_IP` too if the app is public --
  unset, a single client can open unlimited connections against the hub.
  Test with `zeython.testing.websocket_client()` (plain `def test_...`,
  not `async def` -- it's sync). See `docs/websockets.md`.
- A generated project already exposes `/up` (`HealthCheckServiceProvider`,
  registered in `main.py` by default) for load balancers/container
  orchestrators -- don't add a second one. See `docs/health-check.md`.
- Every request already gets a correlation ID (`RequestIdServiceProvider`,
  registered by default): `X-Request-ID` on the response, and
  `request_id()` (`zeython.request_id`) inside a handler or any log line
  formatted with `%(request_id)s`. Don't hand-roll a second ID scheme --
  reuse this one. See `docs/observability.md`.
- Database access inside a request handler never needs a session parameter —
  `Model.create/find/all/...` pull the request-scoped session automatically.
  Outside a request (scripts, one-off tasks), wrap the code in
  `async with database.session():` — see docs/architecture.md.
- After changing a model's columns, generate and apply a migration:
  `zeython db revision -m "..."` then `zeython db migrate`. Never edit
  `database.db` directly or hand-edit an already-applied migration file.
- `DATABASE_POOL_SIZE`/`DATABASE_MAX_OVERFLOW` tune the connection pool for
  Postgres/MySQL in production -- also fine on the file-based SQLite URL
  `zeython new` scaffolds, but leave them unset for `sqlite+aiosqlite:///:memory:`
  specifically (its default pool doesn't accept either and raises
  `TypeError` if you set them). See `docs/database.md#connection-pooling`.
- Use `zeython.testing.client` for endpoint tests — it hits the ASGI app
  in-process (no real server, no port binding).

## Common pitfalls specific to this framework

- **Routes registered after boot don't appear.** `Application` builds the
  underlying Starlette app lazily, on first request. If you programmatically
  add routes, do it inside a `ServiceProvider.register()` (or before the app's
  `.asgi` property is first accessed), not after.
- **`current_session()` raises `RuntimeError` outside a request/session
  block** — this is intentional (no silent session-per-call fallback). If you
  hit it in a script or test, wrap the code in `async with database.session():`.
- **Soft delete is the default.** `model.delete()` sets `is_deleted=True`
  rather than removing the row; pass `soft=False` for a hard delete, and
  remember `find`/`all`/`find_by` exclude soft-deleted rows unless you pass
  `include_deleted=True`.

## Verifying your work

There is no manual QA substitute here — run the actual checks:

```bash
pytest                        # framework tests, or the app's own tests
ruff check src tests          # framework only
mypy src/zeython              # framework only
```

For an app, also boot it and hit a real endpoint (`zeython serve` +
`curl`), don't just rely on the test suite passing.

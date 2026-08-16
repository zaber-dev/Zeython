# AGENTS.md

Guidance for AI coding agents (Claude Code, Cursor, Copilot Workspace, etc.)
working in a Zeython codebase — either the framework itself, or an application
built with it.

## What Zeython is

An async-first MVC framework: ASGI (Starlette) + async SQLAlchemy 2.0, a
dependency injection container, a service-provider boot lifecycle, and a
`zeython` CLI. Full details: [docs/architecture.md](docs/architecture.md).

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
  cd /tmp/agent-smoke-test && cp .env.example .env && pip install -e .
  python -m alembic revision --autogenerate -m x && python -m alembic upgrade head
  pytest
  ```
- Don't add a dependency to `pyproject.toml` for something solvable in a few
  lines of stdlib. The framework's value is a small, trustworthy core.

## If you're working in an application built with Zeython

- Models go in `app/Models/`, subclass `zeython.Model`, and get registered in
  `app/Models/__init__.py` (so Alembic autogenerate can see them). Use
  `zeython make model <Name>` rather than hand-rolling this.
- Validate on the model, not in the controller: set `__rules__` on the model
  (`docs/validation.md`) instead of hand-checking `request.json()` fields —
  `create()`/`save()`/`update()` already raise `ValidationException` (a 422
  JSON response) for you.
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
- Controllers go in `app/Controllers/`, subclass `zeython.Controller`. Methods
  are plain `async def method(self, request) -> Response`.
- Routes are wired in `routes/web.py`, imported via `RouteServiceProvider` in
  `main.py`. Function routes use `@app.get(...)`; CRUD resources use
  `app.router.resource("/path", SomeController)`.
- Database access inside a request handler never needs a session parameter —
  `Model.create/find/all/...` pull the request-scoped session automatically.
  Outside a request (scripts, one-off tasks), wrap the code in
  `async with database.session():` — see docs/architecture.md.
- After changing a model's columns, generate and apply a migration:
  `zeython db revision -m "..."` then `zeython db migrate`. Never edit
  `database.db` directly or hand-edit an already-applied migration file.
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

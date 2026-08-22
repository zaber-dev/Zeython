# Testing

Zeython ships `zeython.testing.client`, an `httpx.AsyncClient` wired directly to your application's ASGI callable — no real sockets, no running server required.

```python
# tests/test_users.py
from zeython.testing import client
from main import app

async def test_create_user():
    async with client(app) as http:
        response = await http.post("/users", json={"name": "Ada", "email": "ada@example.com"})

    assert response.status_code == 201
    assert response.json()["email"] == "ada@example.com"
```

Generated projects come with `asyncio_mode = "auto"` set in `pyproject.toml` (via pytest-asyncio), so `async def test_...` functions run without extra markers or fixtures. `pytest`/`pytest-asyncio`/`httpx` live behind the `dev` extra (`pip install -e ".[dev]"` — see the project's own README), not the base install, so a production deployment doesn't pull in test tooling it'll never use. Run the suite with:

```bash
pytest
```

## Testing routes protected by CSRF

If the app under test registers `AuthServiceProvider`, unsafe requests (`POST`/`PUT`/`PATCH`/`DELETE`) against a session-authenticated route need a valid CSRF token -- see [CSRF Protection](https://zeython.zaber.dev/docs/csrf/index.md). `client()` handles this for you automatically, reading the token from its own cookie jar and attaching it as a header, the same way a real browser-based client reading `document.cookie` would. The one thing it can't do for you: the *first* unsafe request in a test still needs a prior safe (`GET`) request to actually receive that cookie in the first place.

```python
async def test_create_post():
    async with client(app) as http:
        await http.post("/register", json={"email": "ada@example.com", "password": "hunter2"})
        # a session cookie now exists; a fresh csrf_token cookie came back
        # with that response too, and this next call picks it up automatically
        response = await http.post("/posts", json={"title": "Hello"})
        assert response.status_code == 201
```

(`/register` itself needed no priming here: a brand new client has no session cookie yet, and CSRF is only enforced once one exists.)

## Logging a test client in directly

Most tests that need an authenticated request aren't testing the login flow itself — going through a real `POST /login` every time is boilerplate. `login_as()` sets the same signed session cookie a real login would, directly:

```python
from zeython.testing import client, login_as

async def test_only_the_owner_can_delete_their_post():
    user = await User.create(email="ada@example.com", ...)

    async with client(app) as http:
        login_as(http, app, user)
        response = await http.delete(f"/posts/{post.id}")

    assert response.status_code == 204
```

Requires `AuthServiceProvider` to be registered (same requirement `login()` itself has) — the cookie it builds is accepted by `require_auth()`/`current_user()` exactly the way a real login's would be, since it's built with the same secret key, cookie name, and encoding Starlette's `SessionMiddleware` uses internally. Still test the real login endpoint itself somewhere, of course — `login_as()` is for everything *downstream* of being logged in.

## Testing models directly

For unit tests that don't need HTTP, open a session yourself:

```python
from zeython.db.session import Database

async def test_post_creation():
    db = Database("sqlite+aiosqlite:///:memory:")
    async with db.engine.begin() as conn:
        await conn.run_sync(Post.metadata.create_all)

    async with db.session():
        post = await Post.create(title="Hello", body="World")
        assert post.id is not None
```

For anything beyond a one-off row, a `Factory` (`database/factories/`) is usually less repetitive than constructing models by hand in every test -- see [Factories & Seeders](https://zeython.zaber.dev/docs/database-seeding/index.md).

## Rolling back writes between tests

A fresh `sqlite+aiosqlite:///:memory:` database per test (the pattern above, and what `zeython new` scaffolds by default) already gives each test a clean slate for free — nothing to roll back, because nothing from a previous test could still be there. That stops being free once tests run against a real Postgres/MySQL database instead (a staging DB, a Postgres service container in CI): recreating the schema before every single test gets slow fast. `transactional_session()` is the usual fix — open one session for the whole test, and roll it back unconditionally at the end instead of creating fresh tables:

```python
import pytest_asyncio
from zeython.testing import transactional_session

@pytest_asyncio.fixture
async def db_session(database):
    async with transactional_session(database):
        yield

async def test_creating_a_post(db_session):
    post = await Post.create(title="Hello")
    assert post.id is not None
    # rolled back automatically once the test (and the fixture) exits --
    # the next test's queries never see this row
```

Writes made through the Active Record API are visible to any query made later in the same test (it's a real session, not a mock), but never committed — the schema itself still needs to exist already (via migrations against that database, run once, not per test).

## Testing WebSocket routes

`client()` (above) is httpx-based, and httpx has no WebSocket support -- use `zeython.testing.websocket_client()` instead, and write those tests as plain `def`, not `async def`. See [WebSockets](https://zeython.zaber.dev/docs/websockets/#testing).

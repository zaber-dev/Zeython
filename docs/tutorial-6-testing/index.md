# Part 6: Testing

Five `curl` commands ago you proved Bob can't delete Ada's task. That proof is only good until the next code change quietly breaks it. Turn it into a real test instead, using `zeython.testing` — the same helpers `zeython new` already wired into `tests/test_home.py`.

## How a generated test talks to the app

Open `tests/test_home.py` — it's been there since [Part 1](https://zeython.zaber.dev/docs/tutorial-1-setup/index.md):

```python
from main import app

from zeython.testing import client


async def test_index_returns_welcome_message():
    async with client(app) as http:
        response = await http.get("/")

    assert response.status_code == 200
    assert "message" in response.json()
```

`client(app)` gives you an `httpx.AsyncClient` wired directly to your app's ASGI callable — no socket, no `zeython serve` needed. `pyproject.toml` already sets `asyncio_mode = "auto"`, so a plain `async def test_...` function is all pytest needs; no `@pytest.mark.asyncio` decorator. Run it now, before writing anything new, to confirm the baseline works:

```bash
pytest
```

## A fresh database for every test

Every generated project also ships `tests/conftest.py`, which points `DATABASE_URL` at `sqlite+aiosqlite:///:memory:` for the whole test run and rebuilds every table before each test function. Without it, `pytest` would share the same `database.db` file `zeython serve` has been writing to all tutorial long — registering `ada@example.com` in a test would collide with the real Ada you registered by hand back in [Part 1](https://zeython.zaber.dev/docs/tutorial-1-setup/index.md). You don't need to touch this file; it's worth knowing it's there so "why does my test see no data from `curl`" never becomes a mystery.

## Test the Task CRUD routes

Create `tests/test_tasks.py`. Build every fixture — the project, Ada, Bob — through the same routes `curl` used in Parts 3 and 5, not by poking the database directly; `/register` logs the client in too, so a real request is *less* code than constructing a session by hand:

```python
from main import app

from zeython.testing import client


async def test_creating_a_task_requires_login():
    async with client(app) as http:
        project = (await http.post("/projects", json={"name": "Website Redesign"})).json()
        response = await http.post("/tasks", json={"title": "Ship it", "project_id": project["id"]})

    assert response.status_code == 401


async def test_logged_in_user_can_create_and_see_their_task():
    async with client(app) as http:
        # /register logs the client in too -- see docs/authentication.md.
        await http.post("/register", json={"name": "Ada", "email": "ada@example.com", "password": "hunter2222"})
        project = (await http.post("/projects", json={"name": "Website Redesign"})).json()

        response = await http.post("/tasks", json={"title": "Ship it", "project_id": project["id"]})
        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "Ship it"
        assert body["project"]["name"] == "Website Redesign"

        show = await http.get(f"/tasks/{body['id']}")
        assert show.status_code == 200
        assert show.json()["title"] == "Ship it"
```

No `login_as()` needed here — `/register` already sets the session cookie, same as it did for real against `zeython serve` in Part 1. Reach for `login_as()` (see [Testing](https://zeython.zaber.dev/docs/testing/#logging-a-test-client-in-directly)) instead when a test's fixture user already exists some other way and a real register/login round trip would just be noise.

## Test the authorization scenario from Part 5

This is the one that matters — Ada can delete her own task, Bob can't:

```python
async def test_only_the_author_can_delete_their_task():
    async with client(app) as ada_http:
        await ada_http.post("/register", json={"name": "Ada", "email": "ada@example.com", "password": "hunter2222"})
        project = (await ada_http.post("/projects", json={"name": "Website Redesign"})).json()
        task = (await ada_http.post("/tasks", json={"title": "Ship it", "project_id": project["id"]})).json()

        async with client(app) as bob_http:
            await bob_http.post("/register", json={"name": "Bob", "email": "bob@example.com", "password": "hunter2222"})
            response = await bob_http.delete(f"/tasks/{task['id']}")
            assert response.status_code == 403

        response = await ada_http.delete(f"/tasks/{task['id']}")
        assert response.status_code == 204
```

Two separate `client(app)` instances, not one client re-logged-in twice — each gets its own cookie jar, so there's no risk of Bob's session leaking onto Ada's requests or vice versa. `403` because Bob *is* authenticated (an anonymous request would get `401`, exactly like `test_creating_a_task_requires_login` above) but the `TaskPolicy` says no; `204` because Ada, the actual author, is allowed.

Run it:

```bash
pytest tests/test_tasks.py -v
```

```text
tests/test_tasks.py::test_creating_a_task_requires_login PASSED
tests/test_tasks.py::test_logged_in_user_can_create_and_see_their_task PASSED
tests/test_tasks.py::test_only_the_author_can_delete_their_task PASSED
```

That's the entire Part 5 scenario, pinned down as three tests that run in milliseconds and will fail loudly the moment someone removes the `authorize()` call from `destroy` by accident. See [Testing](https://zeython.zaber.dev/docs/testing/index.md) for `transactional_session` (isolating tests against a real Postgres/MySQL database instead of SQLite's default `:memory:`), factories, and `websocket_client`.

## Where TaskFlow goes from here

You've built a real, tested, multi-user application: models with validation, full CRUD controllers, a relationship loaded without an N+1 query, and authorization enforced by a policy instead of scattered `if` checks. Everything you used has a deeper reference page for the cases this tutorial didn't cover:

- [Database & Migrations](https://zeython.zaber.dev/docs/database/index.md) — querying beyond `find`/`all`, transactions, raw SQL
- [Relationships](https://zeython.zaber.dev/docs/relationships/index.md) — many-to-many, nested `include=`
- [Validation](https://zeython.zaber.dev/docs/validation/index.md) — the full built-in rule set, writing your own
- [Authorization](https://zeython.zaber.dev/docs/authorization/index.md) — `gate.before()`, ability closures without a policy class
- [Testing](https://zeython.zaber.dev/docs/testing/index.md) — factories, transactional isolation, WebSocket tests
- [Production Checklist](https://zeython.zaber.dev/docs/production-checklist/index.md) — taking TaskFlow to production

Or jump back to the [documentation home](https://zeython.zaber.dev/docs/index.md) and pick whatever's next for what you're building.

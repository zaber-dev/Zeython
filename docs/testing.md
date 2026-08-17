# Testing

Zeython ships `zeython.testing.client`, an `httpx.AsyncClient` wired directly to
your application's ASGI callable — no real sockets, no running server required.

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

Generated projects come with `asyncio_mode = "auto"` set in `pyproject.toml`
(via pytest-asyncio), so `async def test_...` functions run without extra
markers or fixtures. `pytest`/`pytest-asyncio`/`httpx` live behind the
`dev` extra (`pip install -e ".[dev]"` — see the project's own README),
not the base install, so a production deployment doesn't pull in test
tooling it'll never use. Run the suite with:

```bash
pytest
```

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

For anything beyond a one-off row, a `Factory` (`database/factories/`) is
usually less repetitive than constructing models by hand in every test --
see [Factories & Seeders](database-seeding.md).

## Testing WebSocket routes

`client()` (above) is httpx-based, and httpx has no WebSocket support --
use `zeython.testing.websocket_client()` instead, and write those tests as
plain `def`, not `async def`. See [WebSockets](websockets.md#testing).

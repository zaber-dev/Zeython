"""Tests for zeython.idempotency -- IdempotencyMiddleware/IdempotencyServiceProvider."""

import asyncio
from pathlib import Path

from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.cache import InMemoryCache
from zeython.config import Config
from zeython.idempotency import IdempotencyServiceProvider
from zeython.testing import client


async def _make_app(tmp_path: Path, **kwargs) -> tuple[Application, list[int]]:
    app = Application(Config.load(tmp_path))
    app.register(IdempotencyServiceProvider(app, **kwargs))
    calls: list[int] = []

    @app.post("/orders")
    async def create_order(request):
        payload = await request.json()
        calls.append(len(calls) + 1)
        return JSONResponse({"call": len(calls), "amount": payload.get("amount")}, status_code=201)

    return app, calls


async def test_a_repeated_key_replays_the_first_response(tmp_path: Path) -> None:
    app, calls = await _make_app(tmp_path)

    async with client(app) as http:
        first = await http.post("/orders", json={"amount": 100}, headers={"Idempotency-Key": "abc"})
        second = await http.post("/orders", json={"amount": 100}, headers={"Idempotency-Key": "abc"})

    assert len(calls) == 1  # the handler only actually ran once
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json() == {"call": 1, "amount": 100}
    assert "Idempotency-Replayed" not in first.headers
    assert second.headers["Idempotency-Replayed"] == "true"


async def test_a_different_key_runs_the_handler_again(tmp_path: Path) -> None:
    app, calls = await _make_app(tmp_path)

    async with client(app) as http:
        await http.post("/orders", json={"amount": 100}, headers={"Idempotency-Key": "abc"})
        await http.post("/orders", json={"amount": 100}, headers={"Idempotency-Key": "xyz"})

    assert len(calls) == 2


async def test_no_key_never_replays(tmp_path: Path) -> None:
    app, calls = await _make_app(tmp_path)

    async with client(app) as http:
        first = await http.post("/orders", json={"amount": 100})
        second = await http.post("/orders", json={"amount": 100})

    assert len(calls) == 2
    assert "Idempotency-Replayed" not in first.headers
    assert "Idempotency-Replayed" not in second.headers


async def test_an_unconfigured_method_is_never_touched(tmp_path: Path) -> None:
    app, calls = await _make_app(tmp_path)

    @app.get("/orders")
    async def list_orders(request):
        calls.append(len(calls) + 1)
        return JSONResponse([])

    async with client(app) as http:
        await http.get("/orders", headers={"Idempotency-Key": "abc"})
        await http.get("/orders", headers={"Idempotency-Key": "abc"})

    assert len(calls) == 2


async def test_a_repeated_key_with_a_different_body_is_a_conflict(tmp_path: Path) -> None:
    app, calls = await _make_app(tmp_path)

    async with client(app) as http:
        first = await http.post("/orders", json={"amount": 100}, headers={"Idempotency-Key": "abc"})
        second = await http.post("/orders", json={"amount": 200}, headers={"Idempotency-Key": "abc"})

    assert len(calls) == 1
    assert first.status_code == 201
    assert second.status_code == 409


async def test_concurrent_requests_with_the_same_key_only_run_the_handler_once(tmp_path: Path) -> None:
    app = Application(Config.load(tmp_path))
    app.register(IdempotencyServiceProvider(app))
    calls: list[int] = []

    @app.post("/orders")
    async def create_order(request):
        calls.append(len(calls) + 1)
        await asyncio.sleep(0.05)
        return JSONResponse({"call": len(calls)}, status_code=201)

    async with client(app) as http:
        results = await asyncio.gather(
            http.post("/orders", json={}, headers={"Idempotency-Key": "same"}),
            http.post("/orders", json={}, headers={"Idempotency-Key": "same"}),
            http.post("/orders", json={}, headers={"Idempotency-Key": "same"}),
        )

    assert len(calls) == 1
    bodies = [r.json() for r in results]
    assert all(body == {"call": 1} for body in bodies)


async def test_custom_header_name(tmp_path: Path) -> None:
    app, calls = await _make_app(tmp_path, header="X-Request-Id")

    async with client(app) as http:
        await http.post("/orders", json={"amount": 100}, headers={"X-Request-Id": "abc"})
        await http.post("/orders", json={"amount": 100}, headers={"X-Request-Id": "abc"})
        # The default header name no longer does anything once overridden.
        await http.post("/orders", json={"amount": 100}, headers={"Idempotency-Key": "abc"})

    assert len(calls) == 2


async def test_custom_methods(tmp_path: Path) -> None:
    app, calls = await _make_app(tmp_path, methods=["PUT"])

    async with client(app) as http:
        await http.post("/orders", json={"amount": 100}, headers={"Idempotency-Key": "abc"})
        await http.post("/orders", json={"amount": 100}, headers={"Idempotency-Key": "abc"})

    # POST is no longer covered once `methods=` is overridden to just PUT.
    assert len(calls) == 2


async def test_a_shared_cache_can_be_passed_explicitly(tmp_path: Path) -> None:
    shared_cache = InMemoryCache()
    app, calls = await _make_app(tmp_path, cache=shared_cache)

    async with client(app) as http:
        await http.post("/orders", json={"amount": 100}, headers={"Idempotency-Key": "abc"})

    assert await shared_cache.has("idempotency:POST:/orders:abc")

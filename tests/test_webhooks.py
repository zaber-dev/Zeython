"""Tests for zeython.webhooks -- outbound HMAC-signed webhook delivery,
the mirror image of zeython.notifications.
"""

import functools
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from starlette.responses import JSONResponse

import zeython.webhooks as webhooks_module
from zeython.application import Application
from zeython.config import Config
from zeython.container import Container
from zeython.db import Model
from zeython.db.session import Database
from zeython.providers import DatabaseServiceProvider
from zeython.queue import InMemoryQueue, Queue, QueueServiceProvider, SyncQueue
from zeython.testing import client
from zeython.webhooks import (
    DeliverWebhookJob,
    WebhookManager,
    WebhookServiceProvider,
    fire_webhook,
    sign_payload,
    verify_signature,
)


class WebhookEndpoint(Model):
    __tablename__ = "webhook_test_endpoints"

    url: Mapped[str] = mapped_column(String(255))
    event: Mapped[str] = mapped_column(String(255))
    secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class WebhookDelivery(Model):
    __tablename__ = "webhook_test_deliveries"

    endpoint_id: Mapped[int] = mapped_column(Integer)
    event: Mapped[str] = mapped_column(String(255))
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)


def _mock_transport(handler: Any) -> None:
    """Point every httpx.AsyncClient the webhooks module builds at ``handler``
    instead of a real socket -- the standard httpx testing pattern
    (httpx.MockTransport), applied via monkeypatch since WebhookManager.deliver()
    constructs its own client internally rather than accepting one.
    """
    return functools.partial(httpx.AsyncClient, transport=httpx.MockTransport(handler))


# -- sign_payload() / verify_signature() ------------------------------------------------


def test_sign_payload_is_deterministic_hmac_sha256_hex() -> None:
    signature = sign_payload("secret", b'{"a":1}')
    assert signature == sign_payload("secret", b'{"a":1}')
    assert len(signature) == 64  # hex-encoded SHA-256 digest
    assert all(c in "0123456789abcdef" for c in signature)


def test_sign_payload_differs_for_different_secrets_or_bodies() -> None:
    base = sign_payload("secret", b"body")
    assert sign_payload("other-secret", b"body") != base
    assert sign_payload("secret", b"different-body") != base


def test_verify_signature_accepts_a_correct_signature() -> None:
    body = b'{"event":"user.created"}'
    signature = sign_payload("shh", body)
    assert verify_signature("shh", body, signature) is True


def test_verify_signature_rejects_a_wrong_signature() -> None:
    body = b'{"event":"user.created"}'
    assert verify_signature("shh", body, "0" * 64) is False
    assert verify_signature("shh", body, sign_payload("wrong-secret", body)) is False


# -- DeliverWebhookJob --------------------------------------------------------------------


def test_deliver_webhook_job_defaults_to_five_attempts() -> None:
    job = DeliverWebhookJob(endpoint_id=1, event="user.created", payload={"id": 1})
    assert job.max_attempts == 5


async def test_deliver_webhook_job_handle_delegates_to_the_manager() -> None:
    calls: list[tuple[int, str, dict]] = []

    class _FakeManager:
        async def deliver(self, endpoint_id: int, event: str, payload: dict) -> None:
            calls.append((endpoint_id, event, payload))

    job = DeliverWebhookJob(endpoint_id=7, event="order.shipped", payload={"order_id": 7})
    await job.handle(_FakeManager())  # type: ignore[arg-type]

    assert calls == [(7, "order.shipped", {"order_id": 7})]


# -- WebhookManager.deliver() ---------------------------------------------------------------


@pytest.fixture
async def database() -> Any:
    db = Database("sqlite+aiosqlite:///:memory:")
    async with db.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)
    yield db
    await db.dispose()


async def test_deliver_sends_a_correctly_signed_post(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["headers"] = request.headers
        received["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(webhooks_module.httpx, "AsyncClient", _mock_transport(handler))

    async with database.session():
        endpoint = await WebhookEndpoint.create(
            url="https://example.com/hook", event="user.created", secret="topsecret", active=True
        )

        manager = WebhookManager(Container(), endpoint_model=WebhookEndpoint, delivery_model=WebhookDelivery)
        await manager.deliver(endpoint.id, "user.created", {"id": 1, "email": "ada@example.com"})

    assert received["headers"]["X-Webhook-Event"] == "user.created"
    assert received["headers"]["X-Webhook-Signature"] == sign_payload("topsecret", received["body"])
    assert b'"id":1' in received["body"]


async def test_deliver_without_a_secret_sends_no_signature_header(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["headers"] = request.headers
        return httpx.Response(200)

    monkeypatch.setattr(webhooks_module.httpx, "AsyncClient", _mock_transport(handler))

    async with database.session():
        endpoint = await WebhookEndpoint.create(url="https://example.com/hook", event="user.created", active=True)
        manager = WebhookManager(Container(), endpoint_model=WebhookEndpoint)
        await manager.deliver(endpoint.id, "user.created", {})

    assert "X-Webhook-Signature" not in received["headers"]


async def test_deliver_records_a_successful_delivery(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        webhooks_module.httpx, "AsyncClient", _mock_transport(lambda request: httpx.Response(200))
    )

    async with database.session():
        endpoint = await WebhookEndpoint.create(url="https://example.com/hook", event="user.created", active=True)
        manager = WebhookManager(Container(), endpoint_model=WebhookEndpoint, delivery_model=WebhookDelivery)
        await manager.deliver(endpoint.id, "user.created", {})

        deliveries = await WebhookDelivery.all()

    assert len(deliveries) == 1
    assert deliveries[0].success is True
    assert deliveries[0].status_code == 200
    assert deliveries[0].error is None


async def test_deliver_records_a_failed_delivery_and_reraises(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        webhooks_module.httpx,
        "AsyncClient",
        _mock_transport(lambda request: httpx.Response(500, text="boom")),
    )

    async with database.session():
        endpoint = await WebhookEndpoint.create(url="https://example.com/hook", event="user.created", active=True)
        manager = WebhookManager(Container(), endpoint_model=WebhookEndpoint, delivery_model=WebhookDelivery)

        with pytest.raises(httpx.HTTPStatusError):
            await manager.deliver(endpoint.id, "user.created", {})

        deliveries = await WebhookDelivery.all()

    assert len(deliveries) == 1
    assert deliveries[0].success is False
    assert deliveries[0].status_code == 500
    assert deliveries[0].error is not None


async def test_deliver_skips_a_no_longer_active_endpoint(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    monkeypatch.setattr(webhooks_module.httpx, "AsyncClient", _mock_transport(handler))

    async with database.session():
        endpoint = await WebhookEndpoint.create(url="https://example.com/hook", event="user.created", active=False)
        manager = WebhookManager(Container(), endpoint_model=WebhookEndpoint, delivery_model=WebhookDelivery)
        await manager.deliver(endpoint.id, "user.created", {})

        deliveries = await WebhookDelivery.all()

    assert called is False
    assert deliveries == []


async def test_deliver_skips_a_deleted_endpoint(database: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    monkeypatch.setattr(webhooks_module.httpx, "AsyncClient", _mock_transport(handler))

    async with database.session():
        manager = WebhookManager(Container(), endpoint_model=WebhookEndpoint)
        await manager.deliver(999999, "user.created", {})

    assert called is False


# -- WebhookManager.fire() ------------------------------------------------------------------


async def test_fire_queues_a_delivery_for_every_active_matching_endpoint(database: Database) -> None:
    calls: list[int] = []

    class _RecordingQueue(Queue):
        async def push(self, job, *, delay: float = 0.0) -> None:  # type: ignore[override]
            calls.append(job.endpoint_id)

    container = Container()
    container.singleton(Queue, lambda: _RecordingQueue())

    async with database.session():
        matching_1 = await WebhookEndpoint.create(url="https://a.example/hook", event="user.created", active=True)
        matching_2 = await WebhookEndpoint.create(url="https://b.example/hook", event="user.created", active=True)
        await WebhookEndpoint.create(url="https://c.example/hook", event="user.created", active=False)
        await WebhookEndpoint.create(url="https://d.example/hook", event="order.shipped", active=True)

        manager = WebhookManager(container, endpoint_model=WebhookEndpoint)
        await manager.fire("user.created", {"id": 1})

    assert sorted(calls) == sorted([matching_1.id, matching_2.id])


async def test_fire_with_no_subscribers_is_a_silent_no_op(database: Database) -> None:
    container = Container()
    container.singleton(Queue, lambda: SyncQueue(container=container))

    async with database.session():
        manager = WebhookManager(container, endpoint_model=WebhookEndpoint)
        await manager.fire("nobody.subscribed", {})  # must not raise


async def test_fire_isolates_a_dispatch_failure_to_one_endpoint(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    reported: list[BaseException] = []
    monkeypatch.setattr(webhooks_module, "report_exception", lambda exc, **tags: reported.append(exc))

    class _FlakyQueue(Queue):
        async def push(self, job, *, delay: float = 0.0) -> None:  # type: ignore[override]
            if job.endpoint_id == bad_id:
                raise RuntimeError("queue is down")

    container = Container()
    container.singleton(Queue, lambda: _FlakyQueue())

    async with database.session():
        bad = await WebhookEndpoint.create(url="https://bad.example/hook", event="user.created", active=True)
        bad_id = bad.id
        good = await WebhookEndpoint.create(url="https://good.example/hook", event="user.created", active=True)

        manager = WebhookManager(container, endpoint_model=WebhookEndpoint)
        await manager.fire("user.created", {})  # must not raise despite the bad endpoint

    assert len(reported) == 1
    assert good.id != bad_id  # sanity: two distinct endpoints were involved


# -- End-to-end: fire() through a real queue, HMAC-verified on the receiving end -------------


async def test_end_to_end_delivery_through_the_in_memory_queue(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["signature"] = request.headers["X-Webhook-Signature"]
        received["body"] = request.content
        return httpx.Response(200)

    monkeypatch.setattr(webhooks_module.httpx, "AsyncClient", _mock_transport(handler))

    container = Container()
    queue = InMemoryQueue(container=container)
    container.singleton(Queue, lambda: queue)

    async with database.session():
        endpoint = await WebhookEndpoint.create(
            url="https://example.com/hook", event="user.created", secret="s3cr3t", active=True
        )
        manager = WebhookManager(container, endpoint_model=WebhookEndpoint, delivery_model=WebhookDelivery)
        container.singleton(WebhookManager, lambda: manager)

        await manager.fire("user.created", {"id": endpoint.id})
        await queue.join()

        deliveries = await WebhookDelivery.all()

    assert verify_signature("s3cr3t", received["body"], received["signature"])
    assert len(deliveries) == 1
    assert deliveries[0].success is True
    await queue.close()


async def test_a_transient_failure_is_retried_and_each_attempt_is_logged(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503)
        return httpx.Response(200)

    monkeypatch.setattr(webhooks_module.httpx, "AsyncClient", _mock_transport(handler))

    container = Container()
    queue = InMemoryQueue(container=container)
    container.singleton(Queue, lambda: queue)

    async with database.session():
        endpoint = await WebhookEndpoint.create(url="https://example.com/hook", event="user.created", active=True)
        manager = WebhookManager(container, endpoint_model=WebhookEndpoint, delivery_model=WebhookDelivery)
        container.singleton(WebhookManager, lambda: manager)

        await queue.push(DeliverWebhookJob(endpoint_id=endpoint.id, event="user.created", payload={}))
        await queue.join()

        deliveries = await WebhookDelivery.all()

    # Two failed attempts, then a third that succeeded -- one delivery row per
    # attempt, since the finally-block audit trail records every try.
    assert attempts == 3
    assert [d.success for d in deliveries] == [False, False, True]
    await queue.close()


async def test_a_permanently_failing_delivery_exhausts_its_attempts(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        webhooks_module.httpx, "AsyncClient", _mock_transport(lambda request: httpx.Response(500))
    )

    container = Container()
    queue = InMemoryQueue(container=container)
    container.singleton(Queue, lambda: queue)

    async with database.session():
        endpoint = await WebhookEndpoint.create(url="https://example.com/hook", event="user.created", active=True)
        manager = WebhookManager(container, endpoint_model=WebhookEndpoint, delivery_model=WebhookDelivery)
        container.singleton(WebhookManager, lambda: manager)

        await queue.push(DeliverWebhookJob(endpoint_id=endpoint.id, event="user.created", payload={}, max_attempts=2))
        await queue.join()

        deliveries = await WebhookDelivery.all()

    assert len(deliveries) == 2
    assert all(not d.success for d in deliveries)
    await queue.close()


# -- HTTP round-trip: fire_webhook() + WebhookServiceProvider --------------------------------


async def _make_app(tmp_path: Path, *, queue_driver: str = "sync") -> Application:
    (tmp_path / ".env").write_text(
        "APP_SECRET_KEY=test-only-secret-not-for-production\n"
        "DATABASE_URL=sqlite+aiosqlite:///:memory:\n"
        f"QUEUE_DRIVER={queue_driver}\n"
    )
    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)
    app.register(QueueServiceProvider)
    app.register(WebhookServiceProvider(app, endpoint_model=WebhookEndpoint, delivery_model=WebhookDelivery))

    database = app.container.make(Database)
    async with database.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)

    @app.post("/orders")
    async def create_order(request):
        await fire_webhook(request, "order.shipped", {"order_id": 42})
        return JSONResponse({"ok": True}, status_code=201)

    return app


async def test_fire_webhook_delivers_over_http_with_a_valid_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["event"] = request.headers["X-Webhook-Event"]
        received["signature"] = request.headers["X-Webhook-Signature"]
        received["body"] = request.content
        return httpx.Response(200)

    monkeypatch.setattr(webhooks_module.httpx, "AsyncClient", _mock_transport(handler))

    app = await _make_app(tmp_path)
    async with app.container.make(Database).session():
        await WebhookEndpoint.create(
            url="https://example.com/hook", event="order.shipped", secret="webhook-secret", active=True
        )

    async with client(app) as http:
        response = await http.post("/orders")

    assert response.status_code == 201
    assert received["event"] == "order.shipped"
    assert verify_signature("webhook-secret", received["body"], received["signature"])
    assert b'"order_id":42' in received["body"]


async def test_delivery_via_the_default_in_memory_queue_actually_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: InMemoryQueue's worker runs on a background task
    created once and reused for every future job, which used to inherit
    whatever database session happened to be live at the moment that task
    was first spawned -- almost always a request's own session, already
    committed and closed by the time the job actually ran. The delivery's
    own `WebhookDelivery.create()` call didn't raise (a closed AsyncSession
    silently reopens a transaction on next use), so nothing looked wrong --
    the row was just flushed into a transaction nothing ever committed
    again, invisible to every other connection. Queue._invoke() now opens
    its own fresh, properly committed session per job. Left out the
    `QUEUE_DRIVER=sync` override the other HTTP test above uses -- sync
    runs the job inline on the request's own task and never exhibited this,
    so only the default in-memory driver actually exercises the fix.
    """
    monkeypatch.setattr(
        webhooks_module.httpx, "AsyncClient", _mock_transport(lambda request: httpx.Response(200))
    )

    app = await _make_app(tmp_path, queue_driver="memory")
    async with app.container.make(Database).session():
        await WebhookEndpoint.create(
            url="https://example.com/hook", event="order.shipped", secret="webhook-secret", active=True
        )

    async with client(app) as http:
        response = await http.post("/orders")
    assert response.status_code == 201

    queue = app.container.make(Queue)
    assert isinstance(queue, InMemoryQueue)
    await queue.join()

    # A brand-new session, opened well after the request's own has closed --
    # exactly what a completely separate reader (an admin dashboard, this
    # very assertion) looks like. Before the fix, this saw nothing.
    async with app.container.make(Database).session():
        deliveries = await WebhookDelivery.all()

    assert len(deliveries) == 1
    assert deliveries[0].success is True
    await queue.close()

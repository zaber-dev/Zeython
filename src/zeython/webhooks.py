"""Outbound webhooks: notify a third party's URL whenever something
happens in your app, the mirror image of :mod:`zeython.notifications`
(which notifies a recipient *inside* your own app).

An endpoint subscribes to one event name; :func:`fire_webhook`/
:meth:`WebhookManager.fire` looks up every active subscriber for that
event and hands each one off to the existing background-job queue
(:mod:`zeython.queue`) as a :class:`DeliverWebhookJob` -- delivery,
retries, and backoff are all the queue's own well-tested machinery, not
reinvented here. Each POST carries an HMAC-SHA256 signature the
receiver can verify, the same double-submit-adjacent idea CSRF uses:
proof the payload came from you, not from whoever guessed the URL.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
from starlette.requests import Request

from zeython.container import Container
from zeython.error_monitoring import report_exception
from zeython.providers import ServiceProvider
from zeython.queue import Job, Queue

if TYPE_CHECKING:
    from zeython.db import Model

logger = logging.getLogger("zeython.webhooks")

DEFAULT_TIMEOUT = 10.0
SIGNATURE_HEADER = "X-Webhook-Signature"
EVENT_HEADER = "X-Webhook-Event"


def sign_payload(secret: str, body: bytes) -> str:
    """The hex-encoded HMAC-SHA256 signature of ``body`` under ``secret`` --
    sent as the ``X-Webhook-Signature`` header on every delivery, and what
    :func:`verify_signature` checks a received payload against.
    """
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, body: bytes, signature: str) -> bool:
    """``True`` if ``signature`` is the correct HMAC-SHA256 of ``body`` under
    ``secret`` -- for code on the *receiving* end of a webhook (a Zeython
    app included) to check before trusting a delivered payload::

        async def receive_webhook(request):
            body = await request.body()
            signature = request.headers.get("X-Webhook-Signature", "")
            if not verify_signature(known_secret, body, signature):
                raise ForbiddenException("Bad webhook signature.")

    Uses :func:`hmac.compare_digest` rather than ``==`` -- a naive string
    comparison leaks how many leading bytes matched through response
    timing, letting an attacker recover the correct signature one byte at
    a time.
    """
    return hmac.compare_digest(sign_payload(secret, body), signature)


@dataclass
class DeliverWebhookJob(Job):
    """Delivers one webhook, dispatched by :meth:`WebhookManager.fire` --
    retried by whichever :class:`~zeython.queue.Queue` is configured
    (capped exponential backoff under :class:`~zeython.queue.RedisQueue`)
    up to ``max_attempts`` times before giving up.
    """

    endpoint_id: int
    event: str
    payload: dict[str, Any] = field(default_factory=dict)
    max_attempts: int = 5

    async def handle(self, manager: WebhookManager) -> None:
        await manager.deliver(self.endpoint_id, self.event, self.payload)


class WebhookManager:
    """Looks up subscribers for an event and hands delivery off to the
    queue. Bound in the container by :class:`WebhookServiceProvider`.
    """

    def __init__(
        self,
        container: Container,
        *,
        endpoint_model: type[Model],
        delivery_model: type[Model] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._container = container
        self.endpoint_model = endpoint_model
        self.delivery_model = delivery_model
        self.timeout = timeout

    async def fire(self, event: str, payload: dict[str, Any]) -> None:
        """Queue a delivery to every active endpoint subscribed to
        ``event``. A given endpoint's own dispatch failure (only possible
        under :class:`~zeython.queue.SyncQueue`, which runs a job inline
        rather than truly queuing it) is logged and reported, not raised
        -- the same isolation :class:`~zeython.notifications.NotificationManager`
        applies per channel, so one bad subscriber can't block delivery
        to the rest.
        """
        endpoints = await self.endpoint_model.find_by(event=event, active=True)
        if not endpoints:
            return

        queue: Queue = self._container.make(Queue)
        for endpoint in endpoints:
            try:
                await queue.push(DeliverWebhookJob(endpoint_id=endpoint.id, event=event, payload=payload))
            except Exception as exc:
                report_exception(exc, endpoint_id=endpoint.id, event=event)
                logger.exception(
                    "Failed to dispatch webhook delivery for endpoint %s (event %r)", endpoint.id, event
                )

    async def deliver(self, endpoint_id: int, event: str, payload: dict[str, Any]) -> None:
        """Actually perform one delivery attempt -- called by
        :class:`DeliverWebhookJob`, but usable directly too (a
        `zeython.mcp`-style introspection tool, or your own "resend this
        delivery" admin action).

        Re-fetches the endpoint rather than trusting the state at the
        moment :meth:`fire` ran -- it may have been disabled or deleted in
        the time a retried delivery sat in the queue.
        """
        endpoint: Any = await self.endpoint_model.find(endpoint_id)
        if endpoint is None or not endpoint.active:
            logger.info("Skipping webhook delivery for endpoint %s -- no longer active.", endpoint_id)
            return

        body = json.dumps({"event": event, "data": payload}, separators=(",", ":")).encode()
        headers = {"Content-Type": "application/json", EVENT_HEADER: event}
        secret = getattr(endpoint, "secret", None)
        if secret:
            headers[SIGNATURE_HEADER] = sign_payload(secret, body)
        else:
            logger.warning(
                "Webhook endpoint %s (event %r) has no secret -- delivering unsigned. "
                "The receiver has no way to verify this payload actually came from you.",
                endpoint_id,
                event,
            )

        status_code: int | None = None
        error: str | None = None
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(endpoint.url, content=body, headers=headers)
                status_code = response.status_code
                response.raise_for_status()
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            if self.delivery_model is not None:
                await self.delivery_model.create(
                    endpoint_id=endpoint_id,
                    event=event,
                    status_code=status_code,
                    success=error is None,
                    error=error,
                )


async def fire_webhook(request: Request, event: str, payload: dict[str, Any]) -> None:
    """Fire ``event`` at every subscribed endpoint using whichever
    :class:`WebhookManager` is bound in the container (see
    :class:`WebhookServiceProvider`). Outside of a request -- an event
    listener, a scheduled task -- resolve directly instead::

        manager = app.container.make(WebhookManager)
        await manager.fire("order.shipped", {"order_id": order.id})
    """
    manager: WebhookManager = request.app.state.container.make(WebhookManager)
    await manager.fire(event, payload)


class WebhookServiceProvider(ServiceProvider):
    """Binds a :class:`WebhookManager` into the container.

        app.register(WebhookServiceProvider(app, endpoint_model=WebhookEndpoint))

    ``endpoint_model`` is your own ``Model`` subclass for endpoint
    subscriptions (columns: ``url``, ``event``, ``secret``, ``active``) --
    one row per (url, event) pair, so a single receiving URL that wants
    several event types just gets several rows. ``delivery_model`` is
    optional (columns: ``endpoint_id``, ``event``, ``status_code``,
    ``success``, ``error``) -- if given, every delivery *attempt*
    (including retries) is logged there for an audit trail of what was
    sent and whether it arrived, mirroring what Stripe/GitHub show in
    their own webhook dashboards. Neither model is mandated by the
    framework, the same `record_model` pattern
    :class:`~zeython.notifications.NotificationServiceProvider` uses --
    see docs/webhooks.md.
    """

    def __init__(
        self,
        app: Any,
        *,
        endpoint_model: type[Model],
        delivery_model: type[Model] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        super().__init__(app)
        self.endpoint_model = endpoint_model
        self.delivery_model = delivery_model
        self.timeout = timeout

    def register(self) -> None:
        manager = WebhookManager(
            self.container,
            endpoint_model=self.endpoint_model,
            delivery_model=self.delivery_model,
            timeout=self.timeout,
        )
        self.container.singleton(WebhookManager, lambda: manager)


__all__ = [
    "DeliverWebhookJob",
    "WebhookManager",
    "WebhookServiceProvider",
    "fire_webhook",
    "sign_payload",
    "verify_signature",
]

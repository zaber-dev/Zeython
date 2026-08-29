# Webhooks

`zeython.webhooks` sends an HMAC-signed HTTP POST to a third party's URL whenever something happens in your app -- the mirror image of [Notifications](https://zeython.zaber.dev/docs/notifications/index.md), which notify a recipient *inside* your own app instead.

## Why this exists

Once your app has integrations, "tell Slack/Zapier/a customer's own backend the moment an order ships" stops being optional -- and building it well means more than a bare `httpx.post()` at the call site: delivery has to survive a flaky receiver (retries with backoff), a receiver has to be able to trust the payload actually came from you (a signature), and one subscriber's outage can't be allowed to slow down or break the request that triggered the event. `zeython.webhooks` hands all three off to infrastructure the framework already has and has already tested -- [the background job queue](https://zeython.zaber.dev/docs/queues/index.md) for delivery/retries, HMAC-SHA256 for the signature -- rather than reinventing them.

## Setup

```python
# main.py
from zeython import Application, DatabaseServiceProvider, QueueServiceProvider, WebhookServiceProvider

from app.Models.webhook_endpoint import WebhookEndpoint
from app.Models.webhook_delivery import WebhookDelivery

app = Application()
app.register(DatabaseServiceProvider)
app.register(QueueServiceProvider)
app.register(WebhookServiceProvider(app, endpoint_model=WebhookEndpoint, delivery_model=WebhookDelivery))
```

A generated project already has this wired up -- see `app/Models/webhook_endpoint.py`, `app/Models/webhook_delivery.py`, and `main.py`. `QueueServiceProvider` has to be registered too: every delivery goes through whichever `Queue` it binds (see [Background Jobs](https://zeython.zaber.dev/docs/queues/index.md)).

## Your own models

Neither model is mandated by the framework -- the same `record_model` pattern [Audit Logging](https://zeython.zaber.dev/docs/audit-log/index.md) and [Notifications](https://zeython.zaber.dev/docs/notifications/index.md) use -- so each project owns its own migration instead of the framework dictating a fixed schema.

`endpoint_model` is *who's subscribed to what* -- one row per (url, event) pair, so a single receiving URL that wants several event types just gets several rows:

```python
# app/Models/webhook_endpoint.py
from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from zeython import Model


class WebhookEndpoint(Model):
    __tablename__ = "webhook_endpoints"

    url: Mapped[str] = mapped_column(String(2048))
    event: Mapped[str] = mapped_column(String(255), index=True)
    secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
```

`delivery_model` is optional: if given, every delivery *attempt* -- including retries -- is logged there, an audit trail of what was sent and whether it arrived, mirroring what Stripe/GitHub show in their own webhook dashboards. Omit it in `WebhookServiceProvider(...)` if you don't need one.

```python
# app/Models/webhook_delivery.py
from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from zeython import Model


class WebhookDelivery(Model):
    __tablename__ = "webhook_deliveries"

    endpoint_id: Mapped[int] = mapped_column(Integer, ForeignKey("webhook_endpoints.id"), index=True)
    event: Mapped[str] = mapped_column(String(255))
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
```

Already generated for you as part of `zeython new` -- run `zeython db revision --autogenerate -m "add webhook tables"` once you're ready to migrate them.

There's no admin UI or API for creating a subscription yet -- add one yourself via `zeython tinker` or a seeder:

```python
import secrets
from app.Models.webhook_endpoint import WebhookEndpoint

await WebhookEndpoint.create(
    url="https://example.com/hooks/zeython",
    event="user.registered",
    secret=secrets.token_hex(32),
    active=True,
)
```

## Firing an event

```python
from zeython.webhooks import fire_webhook

await fire_webhook(request, "order.shipped", {"order_id": order.id, "tracking_number": order.tracking_number})
```

Every active `WebhookEndpoint` subscribed to `"order.shipped"` gets a `DeliverWebhookJob` pushed onto the queue -- the request returns immediately, delivery happens in the background. Outside of a request -- a scheduled task, a console command -- resolve the manager directly instead:

```python
manager = app.container.make(WebhookManager)
await manager.fire("order.shipped", {"order_id": order.id})
```

A generated project fires `"user.registered"` from `app/Listeners/notify_webhooks_of_registration.py`, a listener on the same `UserRegistered` event [Events](https://zeython.zaber.dev/docs/events/index.md) already dispatches -- add your own listener the same way for any other event you want to notify subscribers about, without touching the code that raises it.

## What gets sent

```text
POST https://example.com/hooks/zeython
Content-Type: application/json
X-Webhook-Event: order.shipped
X-Webhook-Signature: 5d41402abc4b2a76b9719d911017c59...

{"event":"order.shipped","data":{"order_id":42,"tracking_number":"1Z..."}}
```

`X-Webhook-Signature` is the hex-encoded HMAC-SHA256 of the exact request body under the endpoint's own `secret` -- proof the payload came from you, not from whoever guessed the URL. An endpoint with no `secret` set still gets delivered to, unsigned, with a warning logged; set one for anything you'd be upset to see spoofed.

## Verifying a signature you receive

If your own app is on the *receiving* end of someone else's webhook (or another Zeython app's), verify it the same way before trusting the body:

```python
from zeython import ForbiddenException
from zeython.webhooks import verify_signature

async def receive_webhook(request):
    body = await request.body()
    signature = request.headers.get("X-Webhook-Signature", "")
    if not verify_signature(known_secret, body, signature):
        raise ForbiddenException("Bad webhook signature.")
    ...
```

`verify_signature()` uses `hmac.compare_digest` rather than `==` -- a naive string comparison leaks how many leading bytes matched through response timing, letting an attacker recover the correct signature one byte at a time.

## Retries and isolation

Delivery failures (a non-2xx response, a connection error, a timeout) are retried by the queue up to `DeliverWebhookJob.max_attempts` (default `5`) -- under `RedisQueue`, with the same capped exponential backoff every other job gets (see [Background Jobs](https://zeython.zaber.dev/docs/queues/#retries-and-backoff)). If `delivery_model` is set, every attempt writes its own row, so you can see exactly when a subscriber started failing and whether it eventually came back.

One subscriber's failure never affects another's: `fire()` queues a separate job per endpoint, and a queuing failure for one endpoint (only possible under `SyncQueue`, which runs a job inline rather than truly queuing it) is logged and reported, not raised -- the same isolation [Notifications](https://zeython.zaber.dev/docs/notifications/index.md) applies per channel.

## Re-fetching before delivery

`WebhookManager.deliver()` re-fetches the endpoint from the database rather than trusting the state `fire()` saw -- an endpoint disabled or deleted in the time a retried delivery sat in the queue is skipped instead of delivered to.

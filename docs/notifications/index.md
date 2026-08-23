# Notifications

`zeython.notifications` gives you a `Notification` class: describe what happened and which channels (`mail`, `database`, `broadcast`) should carry it to one recipient, then fire it with `notify()`. Mirrors Laravel's Notification system.

## Why this exists

A "you have a new comment" message often needs to reach a user more than one way: an email, a row in an in-app notification list, maybe a live WebSocket push if they're online right now. Without this, that's three separate call sites to keep in sync every time the content changes. A `Notification` describes its own rendering per channel once; `notify()` fires whichever channels it asks for.

This is deliberately separate from [Events](https://zeython.zaber.dev/docs/events/index.md) -- an event is "this happened, react however you like" (any number of independent listeners, no fixed shape); a notification is "tell *this one recipient*, on *these* channels, in *this* format."

## Setup

```python
# main.py
from zeython import Application, DatabaseServiceProvider, NotificationServiceProvider

from app.Models.notification import Notification  # your own record model, below

app = Application()
app.register(DatabaseServiceProvider)
app.register(NotificationServiceProvider(app, record_model=Notification))
```

A generated project already has this wired up -- see `app/Models/notification.py`, `app/Notifications/welcome_notification.py`, and the `notify()` call in `AuthController.register`.

`record_model` is only required if you use the `database` channel; omit it if every notification you write only ever uses `mail`/`broadcast`.

## Defining a notification

```python
# app/Notifications/invoice_paid_notification.py
from typing import Any

from zeython import Message, Notification


class InvoicePaidNotification(Notification):
    def __init__(self, invoice) -> None:
        self.invoice = invoice

    def via(self, notifiable: Any) -> list[str]:
        return ["mail", "database"]

    def to_mail(self, notifiable: Any) -> Message:
        return Message(
            to=notifiable.email,
            subject="Invoice paid",
            body=f"Thanks! We received ${self.invoice.amount}.",
        )

    def to_database(self, notifiable: Any) -> dict:
        return {"invoice_id": self.invoice.id, "amount": self.invoice.amount}
```

`via()` decides the channels *per recipient* -- nothing stops it from returning something different depending on `notifiable` (e.g. only email users who opted in). Only implement the `to_*` methods the channels you chose actually need; `zeython make notification InvoicePaid` scaffolds this shape in `app/Notifications/`.

## Sending it

```python
from app.Notifications.invoice_paid_notification import InvoicePaidNotification

async def mark_paid(self, request):
    invoice = await Invoice.find(...)
    await notify(request, invoice.customer, InvoicePaidNotification(invoice))
```

Outside of a request -- a job, a scheduled task -- resolve a `NotificationManager` directly instead:

```python
from zeython.notifications import NotificationManager

manager = app.container.make(NotificationManager)
await manager.notify(invoice.customer, InvoicePaidNotification(invoice))
```

## Channels

| Channel     | Requires                                             | Notes                                                                                                                                                                                                                                                                                                                                                                                             |
| ----------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `mail`      | `Mailer` bound (`MailServiceProvider`)               | Sends `to_mail(notifiable)` through whichever `Mailer` is bound -- see [Mail](https://zeython.zaber.dev/docs/mail/index.md).                                                                                                                                                                                                                                                                      |
| `database`  | `NotificationServiceProvider(app, record_model=...)` | Writes one row: `notifiable_id`, `type` (the class name), `data` (`to_database(notifiable)`), `read_at`.                                                                                                                                                                                                                                                                                          |
| `broadcast` | `WebSocketHubServiceProvider` registered             | Pushes `{"type": ..., "notifiable_id": ..., "data": to_broadcast(notifiable)}` to every connected client via `WebSocketHub.broadcast()` -- see [WebSockets](https://zeython.zaber.dev/docs/websockets/index.md). Not scoped to just the recipient's own connection; filter on the client side by `notifiable_id`, or subscribe recipients to their own channel/room if your app has that concept. |

`to_broadcast()` defaults to whatever `to_database()` returns, so a notification using both doesn't have to write the payload twice.

Calling a channel that isn't set up (`database` with no `record_model`, `broadcast` with no hub registered) raises immediately, naming the fix. An unrecognized channel name from `via()` logs a warning instead of raising -- a typo in one channel shouldn't take down the others.

## What happens when a channel fails

Each channel in `via()` runs independently. One failing (a down SMTP server) is logged and reported (see [Error Monitoring](https://zeython.zaber.dev/docs/error-monitoring/index.md)), **not** raised -- it doesn't stop the others, the same reasoning [Events](https://zeython.zaber.dev/docs/events/#multiple-listeners-and-what-happens-when-one-fails) uses for listeners. A failed email shouldn't also silently swallow the in-app notification that would have told the user something happened.

## The record model (`database` channel)

Not framework-provided -- like `AuthServiceProvider`'s `user_model`, this is your own `Model` subclass, generated into a fresh project by default:

```python
# app/Models/notification.py
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from zeython import Model


class Notification(Model):
    __tablename__ = "notifications"

    notifiable_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(255))
    data: Mapped[dict] = mapped_column(JSON)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Query it with the ordinary `Model` API, or the two small helpers this module provides:

```python
from zeython.notifications import mark_as_read, unread_notifications

from app.Models.notification import Notification

unread = await unread_notifications(current_user, Notification)
await mark_as_read(unread[0])
```

Nothing here forces a mixin onto your `notifiable` model -- pass the same `record_model` you registered with `NotificationServiceProvider`, and any object with an `.id` can be a recipient.

## Notifications vs. background jobs

They compose. `notify()` runs every channel **inline**, in the current request -- fine for a fast `database` write, slower for a real outbound `mail` send. For a notification that might be slow, dispatch a [background job](https://zeython.zaber.dev/docs/queues/index.md) that calls `notify()` from inside `handle()`, rather than blocking the request on it directly.

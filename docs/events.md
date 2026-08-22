# Events

`zeython.events` gives you an `EventDispatcher` -- decoupled listeners
reacting to an application-defined event (`OrderPlaced`, `UserRegistered`,
...) without the code that raises it needing to know who's listening.

## Why this exists

A controller that creates a user often needs to do more than one thing in
response: send a welcome email, write an audit log entry, sync a CRM,
notify a Slack channel. Cramming all of that into the controller works at
first, then turns it into a dumping ground every unrelated feature has to
edit. An event lets the controller announce *what happened* once, and any
number of independent listeners decide what to do about it -- adding a new
reaction never means touching the controller again.

This is deliberately separate from [Model Events](model-events.md)'s
`Observer` classes: an Observer reacts to one model's own lifecycle
(`creating`, `updated`, `deleted`); an event here can be anything your
application defines, dispatched from anywhere -- a controller, a job, a
scheduled task, even a model hook itself.

## Defining and dispatching an event

An event is just a plain class -- a dataclass is the natural fit:

```python
# app/Events/order_placed.py
from dataclasses import dataclass

@dataclass
class OrderPlaced:
    order_id: int
    total_cents: int
```

Dispatch it with `emit()`:

```python
from zeython.events import emit

from app.Events.order_placed import OrderPlaced

async def store(self, request):
    order = await Order.create(...)
    await emit(request, OrderPlaced(order_id=order.id, total_cents=order.total_cents))
    return JSONResponse(order.to_dict(), status_code=201)
```

Outside of a request -- a job, a scheduled task, a model hook -- dispatch
directly against a resolved dispatcher instead:

```python
from zeython.events import EventDispatcher

dispatcher = app.container.make(EventDispatcher)
await dispatcher.dispatch(OrderPlaced(order_id=order.id, total_cents=order.total_cents))
```

## Registering listeners

A listener is a plain function (sync or async) whose first parameter
receives the event; any other parameters are resolved from the container,
the same way `Job.handle()`'s are:

```python
# app/Listeners/send_receipt_email.py
from zeython import Mailer, Message

from app.Events.order_placed import OrderPlaced

async def send_receipt_email(event: OrderPlaced, mailer: Mailer) -> None:
    await mailer.send(Message(to=..., subject="Your receipt", body=f"Order #{event.order_id}"))
```

Register listeners in a `ServiceProvider` subclassing `EventServiceProvider`
-- `super().boot()` first, since that's what actually binds the
`EventDispatcher` this then adds listeners to:

```python
# app/Providers/app_event_service_provider.py
from zeython import EventDispatcher, EventServiceProvider

from app.Events.order_placed import OrderPlaced
from app.Listeners.send_receipt_email import send_receipt_email
from app.Listeners.notify_fulfillment_webhook import notify_fulfillment_webhook

class AppEventServiceProvider(EventServiceProvider):
    def boot(self) -> None:
        super().boot()
        dispatcher = self.container.make(EventDispatcher)
        dispatcher.listen(OrderPlaced, send_receipt_email)
        dispatcher.listen(OrderPlaced, notify_fulfillment_webhook)
```

```python
# main.py
app.register(AppEventServiceProvider(app))
```

A generated project already has this wired up for `UserRegistered`,
dispatched from `AuthController.register` alongside the welcome-email job
-- see `app/Events/`, `app/Listeners/`, and
`app/Providers/app_event_service_provider.py`.

### The decorator form

For a quick one-off listener, `.on()` works as a decorator instead of a
separate `.listen()` call:

```python
@dispatcher.on(OrderPlaced)
async def log_order(event: OrderPlaced) -> None:
    logger.info("order placed: %s", event.order_id)
```

## Multiple listeners, and what happens when one fails

Every listener registered for an event's type runs, in registration order.
A listener's own exception is logged and reported (see
[Error Monitoring](error-monitoring.md) -- it's a no-op if Sentry isn't
configured), **not** raised: one broken listener (a webhook that's down, a
typo in an audit-log write) doesn't stop the others from running. You
wouldn't want a failed Slack notification to also silently swallow the
receipt email.

If a listener genuinely needs to block the request until it's done and
fail loudly if it can't, call it directly instead of going through the
dispatcher -- events are for reactions that can fail independently of the
thing that triggered them.

## Events vs. background jobs

They compose, they don't replace each other. `emit()` calls every listener
**inline**, in the current request -- fine for fast, in-process work (an
audit-log write, updating an in-memory cache). For anything slower (an
actual outbound email send, a real webhook call), dispatch a
[background job](queues.md) from inside the listener, or dispatch the job
directly instead of using an event at all if there's only ever going to be
one reaction. The starter scaffold's `UserRegistered` listener is the
cheap, synchronous case (a log line); the actual welcome email is a
separately-dispatched job, run by a worker, not a listener.

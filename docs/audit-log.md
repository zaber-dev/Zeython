# Audit Logging

`zeython.audit_log` gives you an automatic changelog of who created,
updated, or deleted which model records, and what changed -- attach one
`AuditObserver` per model you want tracked, and every write from then on
gets its own row in a table you own.

## Why this exists

"Who changed this customer's plan, and what did it used to be?" is a
question every app accumulating real users eventually needs to answer --
for a support ticket, a billing dispute, or a compliance audit (SOC 2,
GDPR). Bolting this on later usually means scattering manual logging
calls through every place a record can change, and missing a few. Built
on the existing [Model Observer](model-events.md#observers) system
instead: attach `AuditObserver` once per model, and every `save()`/`delete()`
call -- from a controller, a console command, a background job, anywhere
-- gets recorded, with no per-call-site code to remember.

## Setup

```python
# main.py
from zeython import Application, AuditLogServiceProvider, DatabaseServiceProvider

app = Application()
# Registered *first*, before DatabaseServiceProvider/AuthServiceProvider/
# ApiAuthServiceProvider -- see "Registration order" below.
app.register(AuditLogServiceProvider)
app.register(DatabaseServiceProvider)
```

A generated project already has this wired up -- see
`app/Models/audit_log.py` and `app/Providers/app_audit_service_provider.py`.

### Registration order

`AuditLogServiceProvider` only adds `AuditActorMiddleware`, which resolves
*who* made a change from whichever authentication scheme handled the
request. Resolving that needs a database session already open (to query
your user model) and, for cookie auth, `SessionMiddleware` to have already
parsed the session cookie -- both come from middleware that has to sit
*outside* this one. Since `add_middleware()` prepends (the most recently
registered middleware wraps outermost), that means registering
`AuditLogServiceProvider` **before** any other middleware-adding provider,
not after. Get the order backward and every audited entry silently ends up
with no actor recorded, even for an authenticated request -- the same
class of subtle ordering trap [maintenance mode's setup](maintenance-mode.md#setup)
warns about (there, for the opposite reason: it needs to be registered
*last* to end up outermost).

## Your own AuditLog model

`AuditObserver` writes to a `record_model` you provide -- the same pattern
[Notifications](notifications.md)' `database` channel uses -- so each
project owns its own migration for the table instead of the framework
mandating one:

```python
# app/Models/audit_log.py
from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from zeython import Model


class AuditLog(Model):
    __tablename__ = "audit_logs"

    auditable_type: Mapped[str] = mapped_column(String(255), index=True)
    auditable_id: Mapped[int] = mapped_column(Integer, index=True)
    event: Mapped[str] = mapped_column(String(50))
    changes: Mapped[dict] = mapped_column(JSON)
    actor_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

Already generated for you as part of `zeython new` -- run
`zeython db revision --autogenerate -m "add audit_logs"` once you're ready
to migrate it.

## Auditing a model

```python
# app/Providers/app_audit_service_provider.py
from zeython import AuditObserver, ServiceProvider

from app.Models.audit_log import AuditLog
from app.Models.post import Post


class AppAuditServiceProvider(ServiceProvider):
    def boot(self) -> None:
        Post.observe(AuditObserver(AuditLog))
```

From then on, every `Post.create()`, `.update()`, and `.delete()` writes a
row to `AuditLog`:

- **created** -- every non-hidden field, as `{"old": None, "new": <value>}`.
- **updated** -- only the fields that actually changed, as
  `{"old": <before>, "new": <after>}`; nothing written if nothing did.
- **deleted** -- every non-hidden field's last known value, as
  `{"old": <value>, "new": None}` -- captured *before* the row is gone, so
  a hard delete's trail still shows what was deleted, not just that
  something was.

Fields named in the audited model's own `__hidden__` (the same convention
[`to_dict()`](model-events.md) uses to keep password hashes etc. out of
serialized output) are never recorded, in either direction. Model-owned
bookkeeping columns (`id`, `created_at`, `updated_at`, `is_deleted`,
`deleted_at`) are excluded too -- `id` is already carried as
`auditable_id`, and the rest are either pure noise (`updated_at` changes
on every single update) or already implied by the event itself.

Never attach `AuditObserver` to `record_model` itself --
`AuditLog.observe(AuditObserver(AuditLog))` would make every audit
entry's own creation write another one, without end. `AuditObserver`
raises immediately if you do.

## Who did it

Every audited entry is attributed to the *actor* -- who made the change --
via `current_actor()`, a contextvar `AuditActorMiddleware` sets
automatically per request from whichever authentication scheme resolves a
user first: [`current_user()`](authentication.md) (session cookie), then
[`current_api_user()`](api-authentication.md) (bearer token). No wiring
needed beyond registering the provider in the right order (above).

Outside a request -- a background job, a console command, a scheduled
task -- there's no middleware to infer it from, so set it yourself before
making the change:

```python
from zeython import set_actor

class ShipOrderJob(Job):
    async def handle(self) -> None:
        set_actor(await User.find(self.performed_by_id))
        await self.order.update(status="shipped")
```

Pass `None` to explicitly record subsequent changes as anonymous/system,
overriding an actor the middleware already set -- for a change your own
code makes on the user's behalf that isn't really *their* action.

## Reading the trail

```python
from zeython import audit_trail

history = await audit_trail(AuditLog, post)
for entry in history:
    print(entry.event, entry.actor_type, entry.actor_id, entry.changes)
```

`audit_trail()` returns every entry for one record, oldest first. Query
`AuditLog` directly (`AuditLog.find_by(actor_id=user.id)`, `AuditLog.all()`
with your own filters) for anything broader -- "everything this user did,"
"everything that happened today."

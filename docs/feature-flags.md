# Feature Flags

`zeython.feature_flags` gives you named boolean toggles: static
(`.env`-driven) flags for a plain on/off switch, and deterministic
percentage rollouts for gradually shipping something to a fraction of
users -- no database or Redis required for either. Mirrors the
boolean/rollout building blocks of Laravel Pennant.

## Setup

```python
# main.py
from zeython import Application, FeatureServiceProvider

from app.Providers.app_feature_service_provider import AppFeatureServiceProvider

app = Application()
app.register(AppFeatureServiceProvider(app))
```

Flags are defined in your own subclass of `FeatureServiceProvider` --
`super().boot()` first, the same pattern
[`EventServiceProvider`](events.md#registering-listeners) uses:

```python
# app/Providers/app_feature_service_provider.py
from zeython import FeatureManager, FeatureServiceProvider


class AppFeatureServiceProvider(FeatureServiceProvider):
    def boot(self) -> None:
        super().boot()
        manager = self.container.make(FeatureManager)
        manager.boolean("new_checkout")
        manager.percentage("beta_dashboard", rollout=10)
```

A generated project already has this wired up -- a `beta_dashboard`
rollout checked from `AuthController.me`, see `app/Providers/app_feature_service_provider.py`.

## Checking a flag

```python
from zeython.feature_flags import feature

async def show(self, request):
    if await feature(request, "beta_dashboard", context=current_user):
        return JSONResponse(new_dashboard_payload())
    return JSONResponse(classic_dashboard_payload())
```

Outside of a request -- a job, a scheduled task -- resolve a
`FeatureManager` directly instead:

```python
from zeython.feature_flags import FeatureManager

manager = app.container.make(FeatureManager)
await manager.active("beta_dashboard", context=user)
```

`context` is whatever the flag's resolver needs -- typically the current
user, `None` for a flag that shouldn't vary per-request. Checking an
undefined flag name (a typo, a flag checked before its provider
registered it) resolves `False` and logs a warning rather than raising --
a flag check should always be safe to add.

## Static, `.env`-driven flags

```python
manager.boolean("new_checkout")            # default False
manager.boolean("new_checkout", default=True)
```

```bash
# .env
FEATURE_NEW_CHECKOUT=true
```

Resolves the same for every context -- there's no per-user variation.
Flip it in a deployment's environment (and restart) without touching
code. `zeython features` lists every defined flag and its current
resolution:

```bash
$ zeython features
  beta_dashboard                 off
  new_checkout                   ON
```

## Percentage rollouts

```python
manager.percentage("beta_dashboard", rollout=10)   # ~10% of contexts
manager.percentage("kill_switch", rollout=100, on=False)  # ~always off
```

Deterministic: the same `context` always lands on the same side, via a
stable hash of `(flag name, context)` -- no database write needed to keep
a user's answer from flickering between requests. Buckets by
`context.id` if present, else `str(context)`; pass a stable string
directly (a request ID, a tenant slug) for a flag with no natural object
to check against.

This is a rollout, not a persisted assignment -- widening `rollout` from
10 to 25 keeps everyone already in the 10% (the hash doesn't change) and
adds more; narrowing it back removes exactly the users the wider number
added. There's no support for manually pinning one user in or out beyond
that; use `define()` with a custom resolver backed by a real store if you
need durable per-user overrides an admin can toggle by hand.

## Your own resolver

For anything beyond a static toggle or a hash-based rollout -- reading a
row from your own database, calling a third-party flag service --
`define()` takes any callable:

```python
manager.define(
    "vip_only",
    lambda user: getattr(user, "is_vip", False),
)

# Or async, if the check itself needs to be:
async def resolver(user):
    row = await FeatureOverride.first_where(user_id=user.id, flag="vip_only")
    return row.enabled if row else False

manager.define("vip_only", resolver)
```

## Feature flags vs. multi-tenancy vs. authorization

Three different questions, easy to conflate:

- **Authorization** ([`Gate`/`authorize()`](authorization.md)) answers "is
  this action allowed for this user, ever" -- a permission check, usually
  permanent.
- **Multi-tenancy** ([`current_tenant_id()`](multi-tenancy.md)) answers
  "which tenant's data should this query see."
- **Feature flags** answer "is this *capability* switched on right now" --
  usually temporary (a flag graduates to always-on code, or gets deleted,
  once a rollout finishes), and orthogonal to whether the user is
  otherwise allowed to do something at all.

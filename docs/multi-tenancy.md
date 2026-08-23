# Multi-Tenancy

Row-level isolation for a shared database serving multiple tenants — one
`tenants` table's worth of customers in the same tables as everyone
else's, rather than a database (or schema) per tenant. A model opts in
just by declaring a `tenant_id` column; there's no mixin and nothing to
remember to add to each query.

A different question from [Feature Flags](feature-flags.md): tenancy
answers "which tenant's data should this query see," not "is this
capability switched on right now."

## Setup

```python
# main.py
from zeython import Application, TenancyServiceProvider

def resolve_tenant(request):
    # e.g. acme.example.com -> "acme"
    return request.url.hostname.split(".")[0]

app = Application()
app.register(TenancyServiceProvider(app, resolver=resolve_tenant))
```

`resolver` is a **required** argument — there is deliberately no default.
How a request maps to a tenant is entirely app-specific (a subdomain, a
header, the logged-in user's own `tenant_id`), and guessing wrong here is
a cross-tenant data leak, not a cosmetic mistake:

```python
resolver=lambda request: request.url.hostname.split(".")[0]      # subdomain
resolver=lambda request: request.headers.get("X-Tenant-ID")      # header
async def resolver(request):                                     # the logged-in user's tenant
    user = await current_user(request)
    return user.tenant_id if user else None
```

It may be sync or async, and should return `None` for a request that
doesn't belong to a tenant (a public marketing page, a health check) —
`Model` query methods apply no filter at all in that case, not "filter to
tenant `None`".

## Opting a model in

```python
# app/Models/post.py
from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column
from zeython import Model

class Post(Model):
    __tablename__ = "posts"

    tenant_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
```

That's the whole opt-in. From here:

- `Post.find(id)`, `Post.all()`, `Post.find_by(...)`, `Post.paginate(...)`
  all scope to the current request's resolved tenant automatically —
  including `find()` by ID, so a request can't read another tenant's row
  just by guessing (or enumerating) its ID.
- `Post.create(...)` (and `save()` on a freshly-constructed `Post()`)
  assigns `tenant_id` from the current tenant automatically, if you
  didn't already set it explicitly.
- A model with **no** `tenant_id` column is completely unaffected —
  registering `TenancyServiceProvider` changes nothing for it.

## Outside a request

A background job, a scheduled task, or a script has no request for
`TenancyServiceProvider`'s middleware to resolve a tenant from — use
`as_tenant` to scope a block of code explicitly:

```python
from zeython.tenancy import as_tenant

with as_tenant(tenant.id):
    posts = await Post.all()   # only this tenant's rows
```

With no `as_tenant` block and no request, `current_tenant_id()` is
`None` and queries are unscoped — the same "no filter, not a filter to
nothing" behavior as a request whose resolver returned `None`. This is
the deliberate default: a script that genuinely needs to operate across
every tenant (a nightly report, a migration) shouldn't have to fight the
framework to do it, and a script that forgot to scope itself is a bug in
the script, the same as forgetting a `WHERE` clause would be without this
feature at all.

## Reading it directly

```python
from zeython.tenancy import current_tenant_id

tenant_id = current_tenant_id()   # whatever the resolver returned, or None
```

## What this isn't

- **Not database- or schema-per-tenant.** Every tenant's rows live in the
  same tables. If you need hard physical isolation (a compliance
  requirement, wildly different tenant sizes), this isn't that — you'd
  be routing to a different `Database`/connection per tenant instead,
  which this feature doesn't help with.
- **No tenant management UI or provisioning.** Creating a tenant, inviting
  users to it, billing — all yours to build; this is purely the query-
  and-assignment isolation mechanism.
- **Reassigning `tenant_id` on an existing row isn't prevented.** Only a
  *new* row gets `tenant_id` auto-assigned; an explicit
  `post.update(tenant_id=other_tenant)` isn't blocked. If that matters
  for your app, add a check in the model's own `updating()` hook (see
  [Model Events](model-events.md)).

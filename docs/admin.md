# Admin Panel

A CRUD UI, generated from a model's own columns, for the models you
register -- list, create, edit, and delete pages with no hand-written
templates. This is a lightweight v1, not a Django-admin clone -- see
"What this isn't" below before reaching for it on something it doesn't fit.

## Setup

```python
# main.py
from zeython import AdminServiceProvider
from app.Models.post import Post
from app.Models.user import User

app.register(AdminServiceProvider(
    app,
    models=[Post, User],
    guard=lambda user: user.is_admin,
))
```

Visit `/admin`.

`guard` is a **required** argument, not optional -- there is deliberately
no default that lets any logged-in user in. Every admin route also
requires a logged-in user regardless of what `guard` says (see
[Authentication](authentication.md)); `guard` decides who, among logged-in
users, gets in. It can return (or `await` to) a bool:

```python
guard=lambda user: user.is_admin                      # a boolean column
guard=lambda user: user.role == "staff"                # a role column
guard=lambda user: Gate.role("admin")(user)             # reusing an existing Gate check
```

A user who's logged in but fails `guard` gets a 403, not a redirect to a
login page they'd already pass -- they're already authenticated, they're
just not allowed here.

## What gets shown

For each registered model:

- **List** (`/admin/{table_name}`) -- every column not in `__hidden__`,
  paginated 20 per page.
- **Create** (`/admin/{table_name}/new`) -- a form field per column,
  excluding `id`, `created_at`, `updated_at`, `is_deleted`, `deleted_at`
  (managed by `Model` itself, never user-editable) and anything in
  `__hidden__` (a password hash has no business in a generic admin form).
- **Edit** (`/admin/{table_name}/{id}/edit`) -- the same fields,
  pre-filled with the row's current values.
- **Delete** -- a button on the list view; soft-deletes via `instance.delete()`
  (the same default `save()`/`delete()` behavior documented in
  [Database & Migrations](database.md)).

A column's SQLAlchemy type picks its input: `Boolean` → checkbox,
`DateTime` → a `datetime-local` input, `Integer`/`Float` → a number
input, everything else → a plain text input.

## Validation

A model's `__rules__` (see [Validation](validation.md)) run on every
create/edit through `save()`, same as anywhere else in the framework --
a failing rule redirects back to the form with the error shown instead of
saving. A raw database error (e.g. a `NOT NULL` violation on a column
with no explicit rule) is caught too and shown the same way, rather than
a raw 500.

## How form submission actually works

`CsrfMiddleware` reads its token from a header
(`X-CSRF-Token`, see [CSRF Protection](csrf.md)), not a form field, and a
plain HTML `<form action="...">` submission can't set a custom header. The
admin UI's generated forms carry a small inline script that intercepts
`submit`, reads the CSRF cookie, and re-issues the request via `fetch`
with the header attached -- the same pattern
[Server-rendered forms](csrf.md#server-rendered-forms) documents for your
own forms, applied here automatically so you don't have to wire it up per
model. Create/edit/delete all go through this, so the browser's native
form submission (which can only ever be `GET`/`POST`, no `PUT`/`DELETE`)
never actually reaches the server directly.

## What this isn't

- **No relationship pickers.** A foreign key column (`author_id`) is a
  plain number input -- you type the related row's ID. There's no
  dropdown, search, or autocomplete over the related table.
- **No search or filtering.** The list view is a straight paginated dump
  of every row.
- **No bulk actions, no field-level permissions, no audit log.** One
  `guard` covers every model and every action uniformly.
- **Not a public-facing UI.** It's for internal, trusted-staff CRUD over
  your own models -- unstyled-but-usable HTML, not something you'd ship
  to end users. If you need any of the above, this is a reasonable
  starting point to fork from (it's under 400 lines in `zeython/admin.py`),
  not a plugin system to configure around.

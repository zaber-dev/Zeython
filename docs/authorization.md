# Authorization

`zeython.authorization` answers a different question than
[Authentication](authentication.md). `require_auth()` answers "is anyone
logged in" — `authorize()` answers "can *this* logged-in user do *this*
specific thing" (edit *this* post, not posts in general). Almost every
mutating endpoint in a real app needs the second question answered, and
there's nothing else in the framework that helps with it — without this,
that logic ends up as ad hoc `if post.author_id != user.id: raise ...`
scattered across controllers.

## Defining abilities

Abilities are named checks registered on a `Gate`, typically in a
`ServiceProvider.boot()` (not `register()` — it needs the `Gate` that
`AuthorizationServiceProvider` binds, and every provider's `register()`
runs before any `boot()`, so this is safe regardless of registration
order):

```python
from zeython import Gate, ServiceProvider

class PostPolicyServiceProvider(ServiceProvider):
    def boot(self) -> None:
        gate: Gate = self.container.make(Gate)
        gate.define("delete-post", lambda user, post: post.author_id == user.id)
```

A check receives the current user plus whatever arguments you pass to
`authorize()`; it can be sync or async, and return anything truthy/falsy.

## Checking abilities

```python
from zeython.authorization import authorize

async def destroy(self, request):
    post = await Post.find(int(request.path_params["id"]))
    await authorize(request, "delete-post", post)
    await post.delete()
```

`authorize()` requires a logged-in user first — an anonymous request gets
`UnauthorizedException` (401); only a logged-in user who *fails* the
ability check gets `ForbiddenException` (403). It returns the authenticated
user on success, so you can use it in place of a separate `require_auth()`
call.

Checking without raising — for conditionally showing/hiding something
rather than blocking a whole endpoint — use the `Gate` directly:

```python
gate: Gate = request.app.state.container.make(Gate)
can_delete = await gate.allows(user, "delete-post", post)
```

## Registering

```python
from zeython import AuthorizationServiceProvider

app.register(AuthServiceProvider(app, user_model=User))  # authorize() needs a logged-in user
app.register(AuthorizationServiceProvider)                # binds the Gate
app.register(PostPolicyServiceProvider(app))               # defines your abilities
```

`zeython new` wires all three, plus a real example: `GET /posts` is
public, but `DELETE /posts/{id}` (`PostController.destroy`) is
`authorize()`-gated with the "delete-post" ability defined in
`app/Providers/post_policy_service_provider.py`.

## An undefined ability is a bug, not a silent deny

`gate.allows(user, "some-typo", ...)` raises `KeyError` rather than
returning `False` if `"some-typo"` was never `define()`-d. A silently-false
check for an ability that doesn't exist would hide the mistake behind a
403 that looks like correct behavior; raising surfaces it immediately,
in tests and in development, instead of in a security review months later.

## Policies

A closure per ability works until a resource accumulates several of them
(`view-post`, `update-post`, `delete-post`, `create-post`...) and a provider's
`boot()` turns into a wall of `gate.define(...)` calls. A **Policy** groups
them: a plain class, one method per ability, registered once against the
model it authorizes:

```python
class PostPolicy:
    def update(self, user, post) -> bool:
        return post.author_id == user.id

    def delete(self, user, post) -> bool:
        return post.author_id == user.id or user.is_admin

    def create(self, user) -> bool:
        # no instance exists yet -- see below
        return user.is_verified
```

```python
class PostPolicyServiceProvider(ServiceProvider):
    def boot(self) -> None:
        gate: Gate = self.container.make(Gate)
        gate.policy(Post, PostPolicy)
```

`authorize()`/`gate.allows()` work exactly the same — an ability not
covered by `gate.define(...)` falls back to the policy registered for
`type(args[0])`:

```python
await authorize(request, "update", post)   # -> PostPolicy().update(user, post)
```

For an ability checked before an instance exists (`create`), pass the model
class itself instead of an instance — it's used to pick the policy but
isn't forwarded as an argument, matching the `create(self, user)` signature
above:

```python
await authorize(request, "create", Post)   # -> PostPolicy().create(user)
```

A policy method named `before` runs ahead of every other method on that
policy; returning non-`None` short-circuits the specific check —
the policy-scoped equivalent of `gate.before()` below:

```python
class PostPolicy:
    def before(self, user, ability):
        return True if user.is_admin else None  # admins bypass every PostPolicy check

    def update(self, user, post) -> bool:
        ...
```

`gate.define(...)` still takes precedence over a policy for the same
ability name — plain closures and policies compose, they're not either/or.

## A global bypass: `gate.before()`

For a rule that should short-circuit *every* ability, not just one policy's,
register a hook once instead of repeating it in every policy/closure:

```python
gate.before(lambda user, ability, *args: True if user.is_admin else None)
```

Runs before any `define()`/`policy()` lookup, for every `allows()` call.
Returning `None` (the common case — "this hook only cares about admins")
defers to the normal check; returning `True`/`False` decides it outright.

## Roles and permissions

For "does this user have role X" / "permission Y" checks — rather than
hand-rolling `user.role == "admin"` everywhere — mix `HasRoles` into your
user model. It's duck-typed against a conventional `Role`/`Permission`
many-to-many shape (a user has roles, a role has permissions), which is
just regular models and relationships — nothing new to import beyond what
[Relationships](relationships.md) already covers:

```python
from zeython import Authenticatable, HasRoles, Model
from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

user_roles = Table(
    "user_roles", Model.metadata,
    Column("user_id", ForeignKey("users.id"), primary_key=True),
    Column("role_id", ForeignKey("roles.id"), primary_key=True),
)
role_permissions = Table(
    "role_permissions", Model.metadata,
    Column("role_id", ForeignKey("roles.id"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id"), primary_key=True),
)


class User(Model, Authenticatable, HasRoles):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    roles: Mapped[list["Role"]] = relationship(secondary=user_roles, lazy="selectin")


class Role(Model):
    __tablename__ = "roles"
    name: Mapped[str] = mapped_column(String(50), unique=True)
    permissions: Mapped[list["Permission"]] = relationship(secondary=role_permissions, lazy="selectin")


class Permission(Model):
    __tablename__ = "permissions"
    name: Mapped[str] = mapped_column(String(100), unique=True)
```

`lazy="selectin"` matters here, on both relationships: `has_permission()`
needs `roles` *and* each role's `permissions` loaded, two levels deep, which
`find`/`all`'s `include=` can't do in one call (see
[Relationships](relationships.md#scope) — it only loads one level per
name). Configuring `selectin` as the relationship's own default loader
strategy sidesteps that: it applies automatically, cascading through nested
relationships that are themselves `lazy="selectin"`, without needing
`include=` at every call site. Without it, `user.has_role(...)` raises
`MissingGreenlet` the first time it touches an unloaded relationship outside
an active session — async SQLAlchemy has no synchronous fallback for a
lazy load the way sync SQLAlchemy does.

`HasRoles` then gives you `user.has_role("editor")`,
`user.has_any_role("editor", "admin")`, `user.has_all_roles(...)`, and
`user.has_permission("posts.delete")` (checked across all of the user's
roles' permissions) — plus `Gate.role(...)`/`Gate.permission(...)` sugar for
defining an ability gated on one:

```python
gate.define("manage-users", Gate.role("admin"))
gate.define("delete-post", Gate.permission("posts.delete"))
```

Assign roles/permissions at creation time (`Role.create(name="admin",
permissions=[...])`), not as a later assignment on an already-saved object.
The same `MissingGreenlet` risk applies once more: SQLAlchemy's default
`expire_on_commit` means a collection relationship on a row that's already
been committed needs a lazy load just to compute what a *new* assignment
would change, and — same as any other lazy load in an async session —
there's no synchronous fallback for that:

```python
role = await Role.create(name="admin")
role.permissions = [permission]   # MissingGreenlet -- role was already committed
await role.save()

role = await Role.create(name="admin", permissions=[permission])  # fine
```

Seed roles/permissions the same way as any other data — a `Seeder`
([Factories & Seeders](database-seeding.md)) is the natural place for a
fixed set like `admin`/`editor`/`viewer`.

## What this isn't

No auto-discovered policies (register each with `gate.policy(...)`), no
`can()`/`cannot()` sugar bolted onto every model instance, no schema the
framework owns for roles/permissions — `HasRoles` is a mixin over
relationships you define yourself, the same way every other model in a
Zeython app is. If an app's needs go beyond a `Gate` + `Policy`s + roles
(row-level multi-tenancy, attribute-based access control, an admin UI for
managing permissions), that's a deliberate scope boundary, not an
oversight — build it on top of the primitives here rather than expecting
the framework to grow into it.

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

## What this isn't

There's no `Policy` base class per model, no auto-discovery, no
`can()`/`cannot()` sugar bolted onto every model instance — one `Gate`,
one `authorize()` function, plain closures. If your app grows enough
abilities that a single provider's `boot()` gets unwieldy, split them
across multiple `ServiceProvider`s (one per resource, same as
`PostPolicyServiceProvider`) — nothing more is needed.

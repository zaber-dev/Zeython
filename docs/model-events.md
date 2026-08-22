# Model Events

Every `Model` has overridable lifecycle hooks — no-ops by default, and the
right place to react to (or shape) a save or delete without cluttering the
controller that triggered it.

## The hooks

`save()` (which `create()` and `update()` both go through) calls, in order:

```
saving() -> creating() or updating() -> [write to the database] -> created() or updated() -> saved()
```

`delete()` calls `deleting()` before removing/soft-deleting the row, then `deleted()` after:

```python
class User(Model):
    ...

    async def saving(self) -> None:
        # Runs before both create and update.
        self.email = self.email.strip().lower()

    async def creating(self) -> None:
        # Runs only on the first save.
        ...

    async def deleted(self) -> None:
        # Runs after delete() -- soft or hard.
        ...
```

Override only the hooks you need; the rest stay no-ops.

## Hooks run before validation

`creating()`/`updating()` run **before** `__rules__` is checked — this is
what makes them useful for deriving a field validation then depends on, not
just for reacting after the fact:

```python
class Post(Model):
    __rules__ = {"slug": [required()]}

    title: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), default="")

    async def creating(self) -> None:
        if not self.slug:
            self.slug = self.title.lower().replace(" ", "-")
```

`await Post.create(title="Hello World")` succeeds — `slug` is derived
before `__rules__` ever sees it. If the ordering were reversed, this would
raise `ValidationException` on an empty `slug` every time.

## Distinguishing create from update

`is_new` isn't exposed as a hook argument — `creating()`/`created()` firing
at all *is* that signal; `updating()`/`updated()` fire on every subsequent
save. If a hook genuinely needs both cases in one method, use `saving()`/
`saved()`, which fire on every save regardless.

## Observers

A model's own hooks are one implementation per class — fine for behavior
that belongs to the model itself (deriving a slug, normalizing an email).
For a cross-cutting concern that doesn't belong on the model, or that
several independent things want to react to (search-index sync, cache
invalidation, audit logging), register an `Observer` instead:

```python
from zeython import Observer

class PostSearchIndexObserver(Observer):
    async def created(self, model: Post) -> None:
        await search_index.add(model.id, model.title)

    async def updated(self, model: Post) -> None:
        await search_index.update(model.id, model.title)

    async def deleted(self, model: Post) -> None:
        await search_index.remove(model.id)

Post.observe(PostSearchIndexObserver)
```

`observe()` accepts a class (instantiated with no arguments) or an
already-constructed instance — typically called once, e.g. in a service
provider's `boot()`. An observer has the same eight hooks as a model
(`saving`/`saved`/`creating`/`created`/`updating`/`updated`/`deleting`/
`deleted`), each taking the model instance as its argument; override only
the ones you need. Several observers can watch the same model, and each
model class's observers are independent of every other model's. Observers
fire after the model's own same-named hook, in the order shown above.

## What this isn't

An observer doesn't replace a model's own hooks — it's for reactions that
don't belong on the model, not a place to move logic that does. If a hook
is really about the model's own data (deriving a field, normalizing input
before validation), keep it a method on the model, not an observer.

It's also not for application-defined events that aren't tied to a
specific model's lifecycle at all (`OrderPlaced`, a scheduled report
finishing) — see [Events](events.md) for those.

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

## What this isn't

There's no separate `Observer` class or event-listener registry — a hook is
just a method you override on the model itself, the same way Django's
`save()` override or a plain Python method works. That's a deliberate
scope limit: if you need several models to share the same reaction to
"created" (e.g., every model logs to an audit table), write a small mixin
class with the hook and have your models inherit from it — no framework
machinery required.

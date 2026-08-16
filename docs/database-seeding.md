# Database Factories & Seeders

A fresh `zeython db migrate` gives you empty tables. Getting from there to
something a developer can actually click around in -- an admin user, a
handful of demo posts -- or a fixed reference row production genuinely
needs, is what factories and seeders are for.

## Factories: building model instances

A factory defines default attributes for one model, so tests and seeders
don't need to spell out every column by hand:

```bash
zeython make factory Post
```

```python
# database/factories/post_factory.py
from zeython import Factory

from app.Models.post import Post


class PostFactory(Factory[Post]):
    model = Post

    def definition(self, sequence: int) -> dict:
        return {
            "title": f"Post {sequence}",
            "body": f"This is the body of post {sequence}.",
        }
```

```python
post = await PostFactory().create()               # built and saved
posts = await PostFactory().create_many(5)         # five saved rows
draft = PostFactory().make(title="Not saved yet")  # built, not persisted
```

`definition()` receives a `sequence` number that starts at 1 and increments
on every call against that factory instance -- use it to keep
unique-constrained columns (an email, a slug) actually unique across a
batch:

```python
def definition(self, sequence: int) -> dict:
    return {"email": f"user{sequence}@example.com"}
```

There's no bundled fake-data library. For simple cases, an f-string built
from `sequence` is often enough (as above); for realistic names, addresses,
or similar, add [Faker](https://faker.readthedocs.io/) yourself and call it
inside `definition()` -- it's a plain Python method, nothing framework-specific
to wire up.

### Overrides and relationships

Keyword arguments to `make()`/`create()` override `definition()`'s
defaults. This is also how a `belongs_to` relationship's foreign key
usually gets set -- a factory can't call another factory's `create()` from
inside `definition()` (`definition()` is synchronous; `create()` isn't), so
pass it explicitly instead:

```python
user = await UserFactory().create()
post = await PostFactory().create(author_id=user.id)
```

### `create()` needs an active session

`create()`/`create_many()` call `Model.create()` under the hood, so they
need the same active database session every other persistence method
does -- a request, or an explicit `async with database.session():` block
(which is exactly what `zeython db seed` opens for you; see below).

## Seeders: populating the database

```bash
zeython make seeder User
```

```python
# database/seeders/user_seeder.py
from zeython import Seeder

from database.factories.user_factory import UserFactory


class UserSeeder(Seeder):
    async def run(self) -> None:
        await UserFactory().create(email="admin@example.com")
        await UserFactory().create_many(9)
```

`self.app`/`self.container` are available inside `run()`, same as a
`Command`. Compose multiple seeders from one entry point with `self.call(...)`:

```python
# database/seeders/database_seeder.py
from zeython import Seeder

from database.seeders.post_seeder import PostSeeder
from database.seeders.user_seeder import UserSeeder


class DatabaseSeeder(Seeder):
    async def run(self) -> None:
        await self.call(UserSeeder, PostSeeder)
```

`DatabaseSeeder` is the conventional entry point -- a generated project
ships one, seeding a handful of demo users and posts via
`database/factories/`.

## Running seeders

```bash
zeython db seed                        # runs DatabaseSeeder
zeython db seed --class UserSeeder      # runs a specific seeder instead
```

`zeython db seed` opens one database session for the whole run (so every
`Model.create()`/factory `create()` call inside just works, no session
plumbing needed), runs the seeder, and commits. Tables must already exist --
run `zeython db migrate` first.

There's no `--force`/environment guard: nothing stops you from running a
seeder against a production database. Keep destructive or non-idempotent
seed data (a `TRUNCATE`, unconditionally inserting the same admin user)
out of a seeder you'd run more than once, the same way you would with a
migration.

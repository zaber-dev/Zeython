# Part 2: Models

TaskFlow needs two things: **projects** to group work, and **tasks**
inside them. Generate both:

```bash
zeython make model Project
zeython make model Task
```

This created `app/Models/project.py` and `app/Models/task.py`, each with
a single placeholder `name` column, and registered them in
`app/Models/__init__.py` automatically — a model has to actually be
imported somewhere for SQLAlchemy to know it exists, and this saves you
remembering to do that by hand every time. Open `app/Models/project.py`:

```python
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from zeython import Model


class Project(Model):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255))
```

That's a real Active Record model, not a wrapper around one — `Model`
is a genuine SQLAlchemy declarative base (see
[Database & Migrations](database.md) for the full API), so anything you
know from plain SQLAlchemy still applies. What `Model` adds on top: `id`,
`created_at`, `updated_at`, and soft-delete (`is_deleted`/`deleted_at`)
columns on every model automatically, plus an async Active Record API —
`Project.create(...)`, `Project.find(id)`, `Project.all()`,
`instance.update(...)`, `instance.delete()`.

## Add validation

A project needs a name — enforce it with a declarative rule instead of
an `if` statement in every place that creates one:

```python
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from zeython import Model, max_length, required


class Project(Model):
    __tablename__ = "projects"
    __rules__ = {
        "name": [required(), max_length(255)],
    }

    name: Mapped[str] = mapped_column(String(255))
```

`__rules__` runs automatically on every `save()` — both `create()` and
`update()` — and raises a `ValidationException` (a 422 with a field-by-field
error dict) on failure. See [Validation](validation.md) for the full list
of built-in rules and how to write your own.

Now `app/Models/task.py` — a task has a title and a done flag:

```python
from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from zeython import Model, max_length, required


class Task(Model):
    __tablename__ = "tasks"
    __rules__ = {
        "title": [required(), max_length(255)],
    }

    title: Mapped[str] = mapped_column(String(255))
    done: Mapped[bool] = mapped_column(Boolean, default=False)
```

(Task doesn't belong to a Project yet — that's the whole subject of
[Part 4](tutorial-4-relationships.md). For now they're two independent
models, which is deliberately simpler for learning the CRUD basics
first.)

## Migrate

Zeython's migrations are Alembic under the hood, with autogeneration
already wired to your models — you write the model, Alembic diffs it
against the database and writes the migration for you:

```bash
zeython db revision -m "add projects and tasks"
zeython db migrate
```

The first command writes a new file under `migrations/versions/` (open
it — it's plain, readable Alembic code, not a black box); the second
actually applies it. Confirm the tables exist by creating one directly
(reusing `cookies.txt`/`$CSRF` from [Part 1](tutorial-1-setup.md#try-the-auth-thats-already-there) --
every unsafe request needs that header, not just the auth ones):

```bash
curl -sS -b cookies.txt -H "X-CSRF-Token: $CSRF" -X POST http://127.0.0.1:8000/projects \
  -H 'Content-Type: application/json' \
  -d '{"name": "Website Redesign"}'
```

That'll 404 — there's no `/projects` route yet. Models don't expose
routes on their own; that's next.

Continue to [Part 3 — Controllers & Routes](tutorial-3-controllers.md).

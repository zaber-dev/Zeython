# Part 4: Relationships

A task with no project isn't very useful for a *multi-project* tracker.
Add the connection to `app/Models/task.py`:

```python
from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from zeython import Model, max_length, required

from app.Models.project import Project


class Task(Model):
    __tablename__ = "tasks"
    __rules__ = {
        "title": [required(), max_length(255)],
    }

    title: Mapped[str] = mapped_column(String(255))
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))

    project: Mapped[Project] = relationship(back_populates="tasks")
```

And the other side, in `app/Models/project.py`:

```python
from sqlalchemy.orm import Mapped, mapped_column, relationship
# ... existing imports ...

class Project(Model):
    # ... existing __tablename__/__rules__/name ...

    tasks: Mapped[list["Task"]] = relationship(back_populates="project")
```

(The string `"Task"` in the type hint — not the class itself — sidesteps
a circular import: `task.py` imports `Project`, so `project.py` can't
also import `Task` at module scope. SQLAlchemy resolves the string by
class name once both models are loaded.)

## Migrate

```bash
zeython db revision -m "add task.project_id"
```

If you followed [Part 3](tutorial-3-controllers.md)'s walkthrough exactly,
the task you created and then deleted there is still in the `tasks` table
— soft-delete marks it `is_deleted`, it doesn't remove the row — and it
has no `project_id`. Open the migration file Alembic just generated under
`migrations/versions/`; the new column comes out `nullable=False` with no
value for that existing row to take, which SQLite refuses outright. Give
it a default so the existing row backfills to project `1` (the one you
created first in Part 3):

```python
batch_op.add_column(sa.Column('project_id', sa.Integer(), nullable=False, server_default='1'))
```

(Skip this if your `tasks` table happens to be empty — a fresh scaffold
where you skipped straight to Part 4 won't hit it. Either way, apply it:)

```bash
zeython db migrate
```

## The one rule that matters here

**Never touch a relationship attribute you didn't explicitly load.**
Zeython's ORM is fully async, and an unloaded relationship has no
synchronous fallback the way sync SQLAlchemy's lazy loading does —
touching one raises `MissingGreenlet`, not a helpful lazy fetch. Load
relationships you're about to use with `include=(...)`:

```python
task = await Task.find(1, include=("project",))
task.project.name        # safe -- already loaded
task.to_dict(include=("project",))   # {"id": 1, "title": "...", "project": {"id": 1, "name": "..."}, ...}
```

Update `TaskController` to always eager-load the project, and to accept
`project_id` when creating a task:

```python
async def index(self, request):
    tasks = await Task.all(include=("project",))
    return JSONResponse([task.to_dict(include=("project",)) for task in tasks])

async def show(self, request):
    task = await Task.find(int(request.path_params["id"]), include=("project",))
    if task is None:
        raise NotFoundException("Task not found")
    return JSONResponse(task.to_dict(include=("project",)))

async def store(self, request):
    data = await request.json()
    task = await Task.create(title=data.get("title"), project_id=data.get("project_id"))
    task = await Task.find(task.id, include=("project",))
    return JSONResponse(task.to_dict(include=("project",)), status_code=201)
```

(`store` re-fetches with `include=` after creating, rather than trying
to load the relationship onto the just-saved instance — simpler than
juggling two different code paths for "freshly created" vs. "loaded from
the database," and one extra indexed lookup is cheap.)

Try it:

```bash
curl -sS -X POST http://127.0.0.1:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"title": "Design the new homepage", "project_id": 1}'
```

```json
{"title":"Design the new homepage","done":false,"project_id":1,"id":2,"created_at":"...","updated_at":"...","is_deleted":false,"deleted_at":null,"project":{"name":"Website Redesign","id":1,"created_at":"...","updated_at":"...","is_deleted":false,"deleted_at":null}}
```

One request, both objects, no N+1 query for every task in the list. See
[Relationships](relationships.md) for the deeper dive — many-to-many,
loading a chain of nested relationships, and the dev-only warning that
catches a forgotten `include=` before it ships.

Continue to
[Part 5 — Authentication & Authorization](tutorial-5-auth.md).

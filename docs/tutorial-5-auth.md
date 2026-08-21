# Part 5: Authentication & Authorization

Right now anyone can create or delete any task. Fix that: creating a
task requires being logged in, and only the person who created a task
can delete it. Two different questions — *"is anyone logged in"*
(authentication) and *"can this specific logged-in user do this specific
thing"* (authorization) — and Zeython answers them with two different
tools.

## Track who created a task

Add an `author` to `app/Models/task.py`, linking to the `User` model
that's been there since [Part 1](tutorial-1-setup.md):

```python
from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from zeython import Model, max_length, required

from app.Models.project import Project
from app.Models.user import User


class Task(Model):
    __tablename__ = "tasks"
    __rules__ = {
        "title": [required(), max_length(255)],
    }

    title: Mapped[str] = mapped_column(String(255))
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    project: Mapped[Project] = relationship(back_populates="tasks")
    author: Mapped[User] = relationship()
```

```bash
zeython db revision -m "add task.author_id"
```

Same real-world migration wrinkle as [Part 4](tutorial-4-relationships.md#migrate):
if your `tasks` table already has rows, the generated `author_id` column
comes out `nullable=False` with nothing to backfill existing rows with.
Give it a default (Ada is user `1`):

```python
batch_op.add_column(sa.Column('author_id', sa.Integer(), nullable=False, server_default='1'))
```

```bash
zeython db migrate
```

## Require login to create a task

`require_auth(request)` returns the logged-in user, or raises
`UnauthorizedException` (a 401) if nobody's logged in — call it at the
top of `store` in `app/Controllers/task_controller.py`:

```python
from zeython.auth import require_auth

# ...

async def store(self, request):
    user = await require_auth(request)
    data = await request.json()
    task = await Task.create(title=data.get("title"), project_id=data.get("project_id"), author_id=user.id)
    task = await Task.find(task.id, include=("project",))
    return JSONResponse(task.to_dict(include=("project",)), status_code=201)
```

## Only the author may delete their own task

`require_auth` alone isn't enough here — *any* logged-in user passes
that check, and you specifically want *this task's own creator*. That's
what [`Gate`](authorization.md) is for: named abilities, checked against
a specific resource. Generate a policy:

```bash
zeython make policy Task
```

This created `app/Policies/task_policy.py` with `view`/`create`/`update`/`delete`
stubs. Fill in `delete`:

```python
class TaskPolicy:
    def delete(self, user, task) -> bool:
        return task.author_id == user.id
```

Register it — service providers are where wiring like this lives (see
[Part 1](tutorial-1-setup.md) if that's still a fuzzy concept). Create
`app/Providers/task_policy_service_provider.py`:

```python
from zeython import Gate, ServiceProvider

from app.Models.task import Task
from app.Policies.task_policy import TaskPolicy


class TaskPolicyServiceProvider(ServiceProvider):
    def boot(self) -> None:
        gate: Gate = self.container.make(Gate)
        gate.policy(Task, TaskPolicy)
```

Add it to `main.py`, alongside the `PostPolicyServiceProvider` that's
already there:

```python
from app.Providers.task_policy_service_provider import TaskPolicyServiceProvider

# ...
app.register(TaskPolicyServiceProvider(app))
```

Now enforce it in `destroy`:

```python
from zeython.authorization import authorize

# ...

async def destroy(self, request):
    task = await Task.find(int(request.path_params["id"]))
    if task is None:
        raise NotFoundException("Task not found")
    await authorize(request, "delete", task)
    await task.delete()
    return Response(status_code=204)
```

`authorize()` calls `require_auth` internally (a 401 if nobody's logged
in at all), then checks the policy (a 403 if they're logged in but not
this task's author). See [Authorization](authorization.md) for
`gate.before()` (a global "admins bypass everything" hook) and the rest
of the `Gate`/Policy API.

## Try it, including the part that should fail

`POST`/`PUT`/`DELETE` to a session-authenticated route need a CSRF
header — see [CSRF Protection](csrf.md) for why (the short version:
without it, any other website could trigger a `POST` to your app using
your visitor's cookie). Extract the token from the cookie jar you've
been building since Part 1 and pass it back as a header:

```bash
CSRF=$(grep csrf_token cookies.txt | awk '{print $NF}')

curl -sS -b cookies.txt -H "X-CSRF-Token: $CSRF" -X POST http://127.0.0.1:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"title": "Ship the redesign", "project_id": 1}'
```

That succeeds — you're logged in as Ada. Now register a second user and
try to delete Ada's task as them:

```bash
curl -sS -c cookies2.txt -X POST http://127.0.0.1:8000/register \
  -H 'Content-Type: application/json' \
  -d '{"name": "Bob", "email": "bob@example.com", "password": "hunter2222"}'

CSRF2=$(grep csrf_token cookies2.txt | awk '{print $NF}')

curl -sS -b cookies2.txt -H "X-CSRF-Token: $CSRF2" -X DELETE http://127.0.0.1:8000/tasks/2 \
  -o /dev/null -w '%{http_code}\n'
```

`403` — Bob is logged in (so it's not a 401), but he's not this task's
author, so the policy says no. Delete it as Ada instead and it's a clean
`204`.

Continue to [Part 6 — Testing](tutorial-6-testing.md), where you'll
write this exact scenario as a real, repeatable test instead of a
sequence of `curl` commands.

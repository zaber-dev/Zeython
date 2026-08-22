# Part 3: Controllers & Routes

Generate a controller for each model:

```bash
zeython make controller Project
zeython make controller Task
```

This created `app/Controllers/project_controller.py` and `app/Controllers/task_controller.py`, each a `Controller` subclass with a placeholder `index` method. Replace `app/Controllers/project_controller.py`:

```python
from starlette.responses import JSONResponse, Response

from zeython import Controller, NotFoundException

from app.Models.project import Project


class ProjectController(Controller):
    async def index(self, request):
        projects = await Project.all()
        return JSONResponse([project.to_dict() for project in projects])

    async def show(self, request):
        project = await Project.find(int(request.path_params["id"]))
        if project is None:
            raise NotFoundException("Project not found")
        return JSONResponse(project.to_dict())

    async def store(self, request):
        data = await request.json()
        project = await Project.create(name=data.get("name"))
        return JSONResponse(project.to_dict(), status_code=201)

    async def update(self, request):
        project = await Project.find(int(request.path_params["id"]))
        if project is None:
            raise NotFoundException("Project not found")
        data = await request.json()
        await project.update(**data)
        return JSONResponse(project.to_dict())

    async def destroy(self, request):
        project = await Project.find(int(request.path_params["id"]))
        if project is None:
            raise NotFoundException("Project not found")
        await project.delete()
        return Response(status_code=204)
```

Nothing here is Zeython-specific magic — it's plain async Python calling the Active Record API from [Part 2](https://zeython.zaber.dev/docs/tutorial-2-models/index.md). `NotFoundException` (and its siblings — `ValidationException`, `UnauthorizedException`, `ForbiddenException`) are the framework's way of turning "this went wrong" into the right HTTP status and JSON shape without you writing that translation by hand every time; raise one, the framework handles the response.

Do the same for `app/Controllers/task_controller.py`, swapping `Project` for `Task` and `name` for `title` (and pass `done` through on create if you want to set it explicitly — it defaults to `False` from the model either way):

```python
from starlette.responses import JSONResponse, Response

from zeython import Controller, NotFoundException

from app.Models.task import Task


class TaskController(Controller):
    async def index(self, request):
        tasks = await Task.all()
        return JSONResponse([task.to_dict() for task in tasks])

    async def show(self, request):
        task = await Task.find(int(request.path_params["id"]))
        if task is None:
            raise NotFoundException("Task not found")
        return JSONResponse(task.to_dict())

    async def store(self, request):
        data = await request.json()
        task = await Task.create(title=data.get("title"))
        return JSONResponse(task.to_dict(), status_code=201)

    async def update(self, request):
        task = await Task.find(int(request.path_params["id"]))
        if task is None:
            raise NotFoundException("Task not found")
        data = await request.json()
        await task.update(**data)
        return JSONResponse(task.to_dict())

    async def destroy(self, request):
        task = await Task.find(int(request.path_params["id"]))
        if task is None:
            raise NotFoundException("Task not found")
        await task.delete()
        return Response(status_code=204)
```

## Wire up the routes

Open `routes/web.py`, import both controllers, and register a full REST resource for each:

```python
from app.Controllers.project_controller import ProjectController
from app.Controllers.task_controller import TaskController

app.router.resource("/projects", ProjectController)
app.router.resource("/tasks", TaskController)
```

`resource()` maps one controller onto the standard five CRUD routes in one line:

| Method        | Path             | Controller method |
| ------------- | ---------------- | ----------------- |
| `GET`         | `/projects`      | `index`           |
| `POST`        | `/projects`      | `store`           |
| `GET`         | `/projects/{id}` | `show`            |
| `PUT`/`PATCH` | `/projects/{id}` | `update`          |
| `DELETE`      | `/projects/{id}` | `destroy`         |

Pass `only=("index", "show")` if you only want a subset — the generated `UserController`/`PostController` in `routes/web.py` already do this for routes that shouldn't exist yet (see the finished file).

## Try it

`zeython serve` picked up the changes automatically. Create a project, then a task:

```bash
curl -sS -X POST http://127.0.0.1:8000/projects \
  -H 'Content-Type: application/json' \
  -d '{"name": "Website Redesign"}'
```

```json
{"name":"Website Redesign","id":1,"created_at":"...","updated_at":"...","is_deleted":false,"deleted_at":null}
```

```bash
curl -sS -X POST http://127.0.0.1:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"title": "Design the new homepage"}'

curl -sS http://127.0.0.1:8000/tasks
curl -sS http://127.0.0.1:8000/tasks/1

curl -sS -X PUT http://127.0.0.1:8000/tasks/1 \
  -H 'Content-Type: application/json' \
  -d '{"done": true}'

curl -sS -X DELETE http://127.0.0.1:8000/tasks/1 -o /dev/null -w '%{http_code}\n'
```

The last command prints `204` — a successful delete with no body.

You now have full CRUD for two models. What's missing: a task has no idea which project it belongs to. Continue to [Part 4 — Relationships](https://zeython.zaber.dev/docs/tutorial-4-relationships/index.md).

# Views

Zeython renders server-side HTML with Jinja2, by convention reading templates
from `resources/views/`.

```python
# app/Controllers/page_controller.py
from zeython import Controller
from zeython.views import render

class PageController(Controller):
    async def show(self, request):
        return render(request, "pages/show.html", {"title": "Hello"})
```

```html
<!-- resources/views/pages/show.html -->
<!doctype html>
<html>
  <head><title>{{ title }}</title></head>
  <body><h1>{{ title }}</h1></body>
</html>
```

## Wiring it up

`render()` looks up the application's `Views` instance from the container, so
register `ViewServiceProvider` alongside your other providers:

```python
# main.py
from zeython import Application, DatabaseServiceProvider, RouteServiceProvider, ViewServiceProvider

app = Application()
app.register(DatabaseServiceProvider)
app.register(ViewServiceProvider)
app.register(RouteServiceProvider(app, modules=("routes.web",)))
```

## Configuration

By default templates are read from `<project root>/resources/views`. Override
with `VIEWS_PATH` in `.env`:

```env
VIEWS_PATH=templates
```

## Using the `Views` object directly

`render()` is sugar over the container-bound `Views` instance; you can also
resolve and use it directly if you need more control (custom filters, globals):

```python
from zeython import Views

views = app.container.make(Views)
views.environment.filters["shout"] = lambda s: s.upper()
```

# Architecture

## The pieces

| Component | Module | Role |
|---|---|---|
| `Application` | `zeython.application` | The ASGI entry point. Owns the container, config, and router; boots service providers; builds the underlying Starlette app lazily on first use. |
| `Container` | `zeython.container` | A type-hint-driven dependency injection container: `bind`, `singleton`, `instance`, `make`, and `call` (autowired function invocation). |
| `ServiceProvider` | `zeython.providers` | The seam where cross-cutting concerns register bindings (`register()`) and wire themselves up (`boot()`). |
| `Router` | `zeython.routing` | Decorator-based routing (`@app.get(...)`), route groups (`include`), and RESTful `resource()` registration — compiles to Starlette `Route`/`Mount` objects. |
| `Model` | `zeython.db.Model` | An async Active-Record base class: `create`, `find`, `all`, `find_by`, `save`, `update`, `delete` (soft by default), `to_dict`, plus declarative validation via `__rules__` (see [Validation](validation.md)). |
| `Config` | `zeython.config` | Layered `.env` + process-environment configuration with dot-path access (`config.get("database.url")`). |
| `Views` | `zeython.views` | Jinja2 rendering by convention from `resources/views/`, bound via `ViewServiceProvider` (see [Views](views.md)). |
| `CorsServiceProvider` | `zeython.providers` | Opt-in, `.env`-configured CORS support wrapping Starlette's `CORSMiddleware`. |
| `AuthServiceProvider` | `zeython.auth` | Session-based auth: signed-cookie sessions, password hashing, `login`/`logout`/`current_user`/`require_auth` (see [Authentication](authentication.md)). |
| `Storage` | `zeython.storage` | Backend-agnostic file storage (`LocalStorage` by default, `S3Storage` opt-in) with `store_upload()` for safe, validated uploads (see [File Storage](storage.md)). |
| `RateLimiter` | `zeython.rate_limit` | In-memory sliding-window rate limiting: `throttle()` per-route guard, opt-in blanket middleware, applied to auth by default (see [Rate Limiting](rate-limiting.md)). |

## Boot lifecycle

```python
from zeython import Application, DatabaseServiceProvider, RouteServiceProvider

app = Application()
app.register(DatabaseServiceProvider)
app.register(RouteServiceProvider(app, modules=("routes.web",)))
```

1. `Application()` loads `Config` from `.env`, and creates a `Container` and `Router`.
2. `app.register(provider)` calls the provider's `register()` immediately — this is
   where bindings go into the container. `RouteServiceProvider` imports your route
   modules here, which is how `@app.get("/")` decorators in `routes/web.py` end up
   registered.
3. On the **first** request (or the first `app.asgi` access), `Application` calls
   `boot()` on every registered provider, in registration order, then builds the
   underlying Starlette app from the final route list.

Splitting `register()` from `boot()` matters: a provider's `boot()` can safely
assume every other provider's bindings already exist, regardless of registration
order. `DatabaseServiceProvider`, for example, binds the `Database` object in
`register()` but only attaches the request-scoped session middleware in `boot()`.

## Request-scoped database sessions

Unlike opening a new session per query, Zeython opens exactly one
`AsyncSession` per HTTP request (via `DatabaseSessionMiddleware`), stores it in a
`contextvars.ContextVar`, and commits/rolls back automatically when the request
finishes. `Model` methods pull that session via `current_session()` — you never
pass a session object through your call stack:

```python
class User(Model):
    __tablename__ = "users"
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True)

async def show(self, request):
    user = await User.find(int(request.path_params["id"]))
```

Outside of a request (a script, a test, a REPL), open a session explicitly:

```python
async with database.session():
    user = await User.create(name="Ada", email="ada@example.com")
```

## Routing and controllers

```python
from zeython import Controller

class UserController(Controller):
    async def index(self, request): ...
    async def show(self, request): ...
    async def store(self, request): ...

app.router.resource("/users", UserController, only=("index", "show", "store"))
```

`resource()` maps `index`/`store`/`show`/`update`/`destroy` to the conventional
REST verbs and paths, the same mapping Laravel and Rails use. Function-based routes
via `@app.get("/path")` work exactly like Flask/FastAPI for everything else.

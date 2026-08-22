# Core

The application bootstrap, DI container, config, routing, service providers, view rendering, and the framework's exception/validation primitives.

## application

The Zeython application: an ASGI app assembled from service providers.

### Application

```python
Application(
    config: Config | None = None,
    *,
    base_path: str | Path | None = None,
)
```

The central object: owns the container, config, router, and providers.

`Application` is itself a valid ASGI callable, so `uvicorn main:app` works directly once you construct one and register at least a router.

Source code in `src/zeython/application.py`

```python
def __init__(self, config: Config | None = None, *, base_path: str | Path | None = None) -> None:
    self.base_path = Path(base_path) if base_path is not None else Path.cwd()
    self.config = config or Config.load(self.base_path)
    _configure_default_logging(self.config)
    self.container = Container()
    self.container.instance(Config, self.config)
    self.container.instance(Container, self.container)

    self.router = Router()
    self.container.instance(Router, self.router)

    self._providers: list[ServiceProvider] = []
    self._middleware: list[Middleware] = []
    self._booted = False
    self._asgi: Starlette | None = None
```

#### providers

```python
providers: list[ServiceProvider]
```

Service providers registered so far, in registration order.

#### run

```python
run(
    *, host: str | None = None, port: int | None = None
) -> None
```

Run with uvicorn. For auto-reload during development, use the `zeython serve` CLI instead.

Source code in `src/zeython/application.py`

```python
def run(self, *, host: str | None = None, port: int | None = None) -> None:
    """Run with uvicorn. For auto-reload during development, use the `zeython serve` CLI instead."""
    import uvicorn

    uvicorn.run(self, host=host or self.config.host, port=port or self.config.port)
```

## container

A minimal, type-hint-driven dependency injection container.

Zeython's :class:`Container` resolves dependencies by inspecting constructor and function type annotations, in the spirit of Laravel's service container. Bindings can be a plain instance, a factory callable, or a class to autowire directly.

### BindingResolutionError

Bases: `Exception`

Raised when the container cannot resolve a requested binding.

### Container

```python
Container()
```

A small service container supporting binding, singletons, and autowiring.

Source code in `src/zeython/container.py`

```python
def __init__(self) -> None:
    self._bindings: dict[Abstract, _Binding] = {}
    self._instances: dict[Abstract, Any] = {}
```

#### bind

```python
bind(
    abstract: Abstract,
    factory: Factory | None = None,
    *,
    shared: bool = False,
) -> None
```

Register a binding. If `factory` is omitted, `abstract` must be a concrete class.

Source code in `src/zeython/container.py`

```python
def bind(self, abstract: Abstract, factory: Factory | None = None, *, shared: bool = False) -> None:
    """Register a binding. If ``factory`` is omitted, ``abstract`` must be a concrete class."""
    resolved_factory = factory or abstract
    if not callable(resolved_factory):
        raise TypeError(f"Binding for {abstract!r} must provide a callable factory")
    self._bindings[abstract] = _Binding(resolved_factory, shared)
    self._instances.pop(abstract, None)
```

#### singleton

```python
singleton(
    abstract: Abstract, factory: Factory | None = None
) -> None
```

Register a binding that is instantiated once and reused.

Source code in `src/zeython/container.py`

```python
def singleton(self, abstract: Abstract, factory: Factory | None = None) -> None:
    """Register a binding that is instantiated once and reused."""
    self.bind(abstract, factory, shared=True)
```

#### instance

```python
instance(abstract: Abstract, value: Any) -> Any
```

Register an already-constructed instance under `abstract`.

Source code in `src/zeython/container.py`

```python
def instance(self, abstract: Abstract, value: Any) -> Any:
    """Register an already-constructed instance under ``abstract``."""
    self._instances[abstract] = value
    return value
```

#### make

```python
make(abstract: Abstract, **overrides: Any) -> Any
```

Resolve `abstract` to a concrete instance, autowiring its dependencies.

Source code in `src/zeython/container.py`

```python
def make(self, abstract: Abstract, **overrides: Any) -> Any:
    """Resolve ``abstract`` to a concrete instance, autowiring its dependencies."""
    if abstract in self._instances:
        return self._instances[abstract]

    binding = self._bindings.get(abstract)
    factory = binding.factory if binding else abstract

    if not callable(factory):
        raise BindingResolutionError(
            f"Cannot resolve unbound abstract type {abstract!r}"
        )

    instance = self.call(factory, **overrides)

    if binding is not None and binding.shared:
        self._instances[abstract] = instance

    return instance
```

#### call

```python
call(fn: Callable[..., T], **overrides: Any) -> T
```

Call `fn`, resolving any missing arguments from the container.

Source code in `src/zeython/container.py`

```python
def call(self, fn: Callable[..., T], **overrides: Any) -> T:
    """Call ``fn``, resolving any missing arguments from the container."""
    signature = inspect.signature(fn)
    kwargs: dict[str, Any] = {}

    for name, param in signature.parameters.items():
        if name in overrides:
            kwargs[name] = overrides[name]
            continue

        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        annotation = param.annotation

        if annotation is inspect.Parameter.empty:
            if param.default is inspect.Parameter.empty:
                raise BindingResolutionError(
                    f"Cannot resolve parameter '{name}' of {fn!r}: no type hint and no default"
                )
            continue

        if self.has(annotation):
            kwargs[name] = self.make(annotation)
        elif inspect.isclass(annotation) and not _is_builtin_scalar(annotation):
            try:
                kwargs[name] = self.make(annotation)
            except BindingResolutionError:
                if param.default is inspect.Parameter.empty:
                    raise
        elif param.default is inspect.Parameter.empty:
            raise BindingResolutionError(
                f"Cannot resolve parameter '{name}' of {fn!r}: "
                f"no binding registered for {annotation!r}"
            )

    return fn(**kwargs)
```

#### flush

```python
flush() -> None
```

Remove all bindings and cached instances.

Source code in `src/zeython/container.py`

```python
def flush(self) -> None:
    """Remove all bindings and cached instances."""
    self._bindings.clear()
    self._instances.clear()
```

## config

Environment-driven configuration for Zeython applications.

### Config

```python
Config(values: dict[str, Any], base_path: Path)
```

Layered configuration backed by the environment and `.env` files.

Values resolve in this order (highest priority first): real process environment variables, then the loaded `.env` file, then explicit defaults passed to :meth:`get`.

Source code in `src/zeython/config.py`

```python
def __init__(self, values: dict[str, Any], base_path: Path) -> None:
    self._values = values
    self.base_path = base_path
```

#### get

```python
get(key: str, default: Any = None) -> Any
```

Dot-path lookup, e.g. `config.get("database.url")` reads `DATABASE_URL`.

Source code in `src/zeython/config.py`

```python
def get(self, key: str, default: Any = None) -> Any:
    """Dot-path lookup, e.g. ``config.get("database.url")`` reads ``DATABASE_URL``."""
    env_key = key.replace(".", "_").upper()
    return self._values.get(env_key, default)
```

## providers

Service providers: the seam where cross-cutting concerns hook into boot.

### ServiceProvider

```python
ServiceProvider(app: Application)
```

Base class for registering and booting application services.

`register()` runs for every provider before any provider's `boot()` runs, so bindings you depend on in `boot()` are guaranteed to exist regardless of registration order.

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

#### register

```python
register() -> None
```

Bind services into the container. Override in subclasses.

Source code in `src/zeython/providers.py`

```python
def register(self) -> None:
    """Bind services into the container. Override in subclasses."""
```

#### boot

```python
boot() -> None
```

Run once all providers have registered. Override in subclasses.

Source code in `src/zeython/providers.py`

```python
def boot(self) -> None:
    """Run once all providers have registered. Override in subclasses."""
```

### DatabaseServiceProvider

```python
DatabaseServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Wires up the async :class:`~zeython.db.Database` and its request-scoped session.

`DATABASE_POOL_SIZE`/`DATABASE_MAX_OVERFLOW` are passed straight through to SQLAlchemy's connection pool when set -- unset by default, so nothing changes for an in-memory SQLite URL (`:memory:`), whose default pool doesn't accept them at all. See docs/database.md#connection-pooling.

`DATABASE_READ_URL`, if set, binds a read replica -- `database.read_replica()` opens a session against it instead of the primary. See docs/database.md#read-replicas.

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

### RouteServiceProvider

```python
RouteServiceProvider(
    app: Application, modules: tuple[str, ...] = ()
)
```

Bases: `ServiceProvider`

Imports route modules for their side effect of registering routes on the app.

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application, modules: tuple[str, ...] = ()) -> None:
    super().__init__(app)
    self.modules = modules
```

### ViewServiceProvider

```python
ViewServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Binds a :class:`~zeython.views.Views` instance for server-rendered HTML.

Looks for templates in `resources/views` under the app's base path by default; override with `VIEWS_PATH` in `.env` or the `views.path` config key.

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

### CorsServiceProvider

```python
CorsServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Opt-in CORS support, configured via `.env`.

- `CORS_ORIGINS` — comma-separated list of allowed origins (default: none)
- `CORS_ALLOW_CREDENTIALS` — default `false`
- `CORS_ALLOW_METHODS` — comma-separated, default `*`
- `CORS_ALLOW_HEADERS` — comma-separated, default `*`

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

## routing

Ergonomic routing built on top of Starlette's proven route matching.

### Controller

Marker base class for class-based controllers used with :meth:`Router.resource`.

### Router

```python
Router(prefix: str = '')
```

Collects routes and exposes Laravel/FastAPI-style decorator sugar.

A `Router` compiles down to a plain list of Starlette `BaseRoute` objects, so nesting via :meth:`include` is just a `Mount` and gets the same battle-tested path matching as everything else built on Starlette.

Source code in `src/zeython/routing.py`

```python
def __init__(self, prefix: str = "") -> None:
    self.prefix = prefix.rstrip("/")
    self.routes: list[BaseRoute] = []
```

#### websocket

```python
websocket(
    path: str, *, name: str | None = None
) -> Callable[[Endpoint], Endpoint]
```

Register a WebSocket handler: `async def handler(websocket: WebSocket) -> None`.

See :mod:`zeython.websockets` and docs/websockets.md.

Source code in `src/zeython/routing.py`

```python
def websocket(self, path: str, *, name: str | None = None) -> Callable[[Endpoint], Endpoint]:
    """Register a WebSocket handler: ``async def handler(websocket: WebSocket) -> None``.

    See :mod:`zeython.websockets` and docs/websockets.md.
    """

    def decorator(endpoint: Endpoint) -> Endpoint:
        self.routes.append(WebSocketRoute(self._full_path(path), endpoint, name=name or endpoint.__name__))
        return endpoint

    return decorator
```

#### include

```python
include(router: Router, *, prefix: str = '') -> None
```

Mount another router's routes under an optional additional prefix.

Source code in `src/zeython/routing.py`

```python
def include(self, router: Router, *, prefix: str = "") -> None:
    """Mount another router's routes under an optional additional prefix."""
    self.routes.append(Mount(prefix or "/", routes=router.routes))
```

#### mount

```python
mount(
    path: str, app: Any, *, name: str | None = None
) -> None
```

Mount an arbitrary ASGI app (e.g. `starlette.staticfiles.StaticFiles`) at a path prefix.

Source code in `src/zeython/routing.py`

```python
def mount(self, path: str, app: Any, *, name: str | None = None) -> None:
    """Mount an arbitrary ASGI app (e.g. ``starlette.staticfiles.StaticFiles``) at a path prefix."""
    self.routes.append(Mount(path, app=app, name=name))
```

#### resource

```python
resource(
    path: str,
    controller_cls: type[Controller],
    *,
    only: Iterable[str] | None = None,
) -> None
```

Register RESTful CRUD routes bound to a controller's methods.

Maps: index->GET path, store->POST path, show->GET path/{id}, update->PUT/PATCH path/{id}, destroy->DELETE path/{id}.

Source code in `src/zeython/routing.py`

```python
def resource(self, path: str, controller_cls: type[Controller], *, only: Iterable[str] | None = None) -> None:
    """Register RESTful CRUD routes bound to a controller's methods.

    Maps: index->GET path, store->POST path, show->GET path/{id},
    update->PUT/PATCH path/{id}, destroy->DELETE path/{id}.
    """
    controller = controller_cls()
    action_map: dict[str, tuple[str, str]] = {
        "index": ("GET", ""),
        "store": ("POST", ""),
        "show": ("GET", "/{id}"),
        "update": ("PUT", "/{id}"),
        "destroy": ("DELETE", "/{id}"),
    }
    allowed = set(only) if only is not None else set(action_map)

    for action, (method, suffix) in action_map.items():
        if action not in allowed or not hasattr(controller, action):
            continue
        handler = getattr(controller, action)
        route_path = self._full_path(f"{path.rstrip('/')}{suffix}")
        self.routes.append(
            Route(route_path, handler, methods=[method], name=f"{path.strip('/')}.{action}")
        )
```

## views

Server-rendered HTML views, by convention read from `resources/views/`.

### Views

```python
Views(directory: str | Path)
```

Thin wrapper around Starlette's Jinja2 integration.

Bound into the container by :class:`~zeython.providers.ViewServiceProvider` under the `resources/views` directory by default. Use the module-level :func:`render` helper from inside a controller/handler for Flask-style ergonomics.

Source code in `src/zeython/views.py`

```python
def __init__(self, directory: str | Path) -> None:
    self.directory = Path(directory)
    self._templates = Jinja2Templates(directory=str(self.directory))
```

### render

```python
render(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    *,
    status_code: int = 200,
) -> HTMLResponse
```

Render `name` using the application's registered :class:`Views` instance.

Usage inside a controller::

```text
from zeython.views import render

async def show(self, request):
    return render(request, "posts/show.html", {"post": post})
```

Source code in `src/zeython/views.py`

```python
def render(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    *,
    status_code: int = 200,
) -> HTMLResponse:
    """Render ``name`` using the application's registered :class:`Views` instance.

    Usage inside a controller::

        from zeython.views import render

        async def show(self, request):
            return render(request, "posts/show.html", {"post": post})
    """
    from zeython.container import Container

    container: Container = request.app.state.container
    views = container.make(Views)
    return views.render(request, name, context, status_code=status_code)
```

## exceptions

HTTP-aware exception hierarchy with a default JSON error handler.

### HTTPException

```python
HTTPException(
    detail: str | None = None,
    *,
    headers: dict[str, str] | None = None,
)
```

Bases: `Exception`

Base class for exceptions that should be rendered as HTTP responses.

Source code in `src/zeython/exceptions.py`

```python
def __init__(self, detail: str | None = None, *, headers: dict[str, str] | None = None) -> None:
    self.detail = detail or self.default_detail
    self.headers = headers or {}
    super().__init__(self.detail)
```

## validation

Declarative validation rules for :class:`zeython.db.Model` fields.

### Rule

```python
Rule(check: Check, message: str)
```

A single named validation rule with a default error message.

Source code in `src/zeython/validation.py`

```python
def __init__(self, check: Check, message: str) -> None:
    self.check = check
    self.message = message
```

### validate

```python
validate(
    data: dict[str, Any], rules: dict[str, list[Rule]]
) -> dict[str, list[str]]
```

Run declarative rules against a plain dict -- the same rule sets you'd write for :attr:`zeython.db.Model.__rules__`, applied to a request payload, query params, or any other dict that isn't (or isn't yet) a model instance. Does not raise; raise `ValidationException(errors)` yourself if that's what you want when `errors` is non-empty.

`Model.validate()` is this function applied to a model instance's own field values -- kept in sync with it deliberately, so a rule set means the same thing whether it's checked against a model or a plain dict.

Source code in `src/zeython/validation.py`

```python
def validate(data: dict[str, Any], rules: dict[str, list[Rule]]) -> dict[str, list[str]]:
    """Run declarative rules against a plain dict -- the same rule sets you'd
    write for :attr:`zeython.db.Model.__rules__`, applied to a request
    payload, query params, or any other dict that isn't (or isn't yet) a
    model instance. Does not raise; raise ``ValidationException(errors)``
    yourself if that's what you want when ``errors`` is non-empty.

    ``Model.validate()`` is this function applied to a model instance's own
    field values -- kept in sync with it deliberately, so a rule set means
    the same thing whether it's checked against a model or a plain dict.
    """
    errors: dict[str, list[str]] = {}
    for field, field_rules in rules.items():
        value = data.get(field)
        for rule in field_rules:
            if not rule(value):
                errors.setdefault(field, []).append(rule.message)
    return errors
```

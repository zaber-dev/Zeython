# Core

The application bootstrap, DI container, config, routing, service providers, the application-level event dispatcher, feature flags, view rendering, and the framework's exception/validation primitives.

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
    self._booted_provider_count = 0
    self._asgi: Starlette | None = None
```

#### providers

```python
providers: list[ServiceProvider]
```

Service providers registered so far, in registration order.

#### add_middleware

```python
add_middleware(
    middleware_class: Callable[..., Any], **options: Any
) -> None
```

Add a middleware layer, wrapping the app outside every layer added so far.

Prepends, matching Starlette's own `Starlette.add_middleware()` convention: the *most recently* added middleware ends up *outermost* -- the one that sees a request first and a response last -- since Starlette's `build_middleware_stack()` wraps its `middleware=[...]` list from the end backward. Getting this backward silently defeats anything that depends on running before everything else (e.g. :class:`~zeython.maintenance.MaintenanceModeMiddleware`, which is documented as needing to intercept a request before even a database session is opened).

Source code in `src/zeython/application.py`

```python
def add_middleware(self, middleware_class: Callable[..., Any], **options: Any) -> None:
    """Add a middleware layer, wrapping the app outside every layer added so far.

    Prepends, matching Starlette's own ``Starlette.add_middleware()``
    convention: the *most recently* added middleware ends up
    *outermost* -- the one that sees a request first and a response
    last -- since Starlette's ``build_middleware_stack()`` wraps its
    ``middleware=[...]`` list from the end backward. Getting this
    backward silently defeats anything that depends on running before
    everything else (e.g. :class:`~zeython.maintenance.MaintenanceModeMiddleware`,
    which is documented as needing to intercept a request before even a
    database session is opened).
    """
    self._middleware.insert(0, Middleware(middleware_class, **options))
```

#### boot

```python
boot() -> Application
```

Boot every registered provider, in registration order.

Resumable, not just idempotent: if a provider's `boot()` raises (e.g. a transient "database not reachable yet" at the very first request), providers before it in registration order are not re-booted on the next call -- only the one that failed and any after it. Without this, a naive "retry every provider" replay would call an already-succeeded provider's `boot()` a second time, and for a provider like `DatabaseServiceProvider` that calls `add_middleware()` in `boot()`, that means a second, duplicate middleware layer added for the remaining life of the process.

Source code in `src/zeython/application.py`

```python
def boot(self) -> Application:
    """Boot every registered provider, in registration order.

    Resumable, not just idempotent: if a provider's ``boot()`` raises
    (e.g. a transient "database not reachable yet" at the very first
    request), providers before it in registration order are not
    re-booted on the next call -- only the one that failed and any
    after it. Without this, a naive "retry every provider" replay
    would call an already-succeeded provider's ``boot()`` a second
    time, and for a provider like ``DatabaseServiceProvider`` that
    calls ``add_middleware()`` in ``boot()``, that means a second,
    duplicate middleware layer added for the remaining life of the
    process.
    """
    if self._booted:
        return self
    for provider in self._providers[self._booted_provider_count :]:
        provider.boot()
        self._booted_provider_count += 1
    self._booted = True
    return self
```

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
    # eval_str=True resolves PEP 563 postponed annotations (`from
    # __future__ import annotations`, used throughout zeython's own
    # source) back into real objects. Without it, every annotation
    # inspected below is the literal *string* "SomeClass" rather than
    # the class itself -- self.has()/inspect.isclass() then silently
    # fail on every parameter, either raising a misleading "no binding
    # registered" for a required dependency that *is* bound (just not
    # under a string key), or silently skipping an optional one
    # (falling back to its default instead of an autowired instance).
    # No-op for a function whose annotations were never stringified.
    try:
        signature = inspect.signature(fn, eval_str=True)
    except NameError as exc:
        raise BindingResolutionError(
            f"Cannot resolve type hints for {fn!r}: {exc}. A forward-referenced "
            "annotation must be resolvable from the function's own module globals."
        ) from exc
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

## events

Application-level events: decoupled listeners reacting to a domain event (`OrderPlaced`, `UserRegistered`, ...) without the code that raises it needing to know who's listening.

Deliberately separate from :class:`zeython.db.Observer` -- an Observer reacts to one model's own lifecycle (`creating`, `updated`, ...); an event here can be anything your application defines, dispatched from anywhere (a controller, a job, a scheduled task), with any number of independent listeners reacting to it without editing the code that dispatches it. A common pattern is dispatching an event *from* a model hook (`created()`) once the write itself is the model's own concern but what happens next (send a receipt, notify a webhook, update a search index) isn't.

### EventDispatcher

```python
EventDispatcher(*, container: Container | None = None)
```

Maps an event type to the listeners registered for it.

Source code in `src/zeython/events.py`

```python
def __init__(self, *, container: Container | None = None) -> None:
    self._listeners: dict[type, list[Listener]] = defaultdict(list)
    self._container = container
```

#### listen

```python
listen(event_type: type[E], listener: Listener) -> None
```

Register `listener` to run whenever an instance of `event_type` is dispatched.

Source code in `src/zeython/events.py`

```python
def listen(self, event_type: type[E], listener: Listener) -> None:
    """Register ``listener`` to run whenever an instance of ``event_type`` is dispatched."""
    self._listeners[event_type].append(listener)
```

#### on

```python
on(event_type: type[E]) -> Callable[[Listener], Listener]
```

Decorator form of :meth:`listen`::

@dispatcher.on(OrderPlaced) async def send_receipt(event: OrderPlaced) -> None: ...

Source code in `src/zeython/events.py`

```python
def on(self, event_type: type[E]) -> Callable[[Listener], Listener]:
    """Decorator form of :meth:`listen`::

        @dispatcher.on(OrderPlaced)
        async def send_receipt(event: OrderPlaced) -> None:
            ...
    """

    def decorator(listener: Listener) -> Listener:
        self.listen(event_type, listener)
        return listener

    return decorator
```

#### listeners_for

```python
listeners_for(event_type: type) -> list[Listener]
```

The listeners currently registered for `event_type`, in registration order.

Source code in `src/zeython/events.py`

```python
def listeners_for(self, event_type: type) -> list[Listener]:
    """The listeners currently registered for ``event_type``, in registration order."""
    return list(self._listeners.get(event_type, ()))
```

#### dispatch

```python
dispatch(event: object) -> None
```

Call every listener registered for `type(event)`, in registration order.

A listener's own exception is logged and reported (see :mod:`zeython.error_monitoring`), not raised -- one broken listener (a bad webhook call, a typo in an audit-log write) shouldn't stop the others from running, the same way a failed Slack notification shouldn't also silently swallow the receipt email.

Source code in `src/zeython/events.py`

```python
async def dispatch(self, event: object) -> None:
    """Call every listener registered for ``type(event)``, in registration order.

    A listener's own exception is logged and reported (see
    :mod:`zeython.error_monitoring`), not raised -- one broken listener
    (a bad webhook call, a typo in an audit-log write) shouldn't stop
    the others from running, the same way a failed Slack notification
    shouldn't also silently swallow the receipt email.
    """
    for listener in self._listeners.get(type(event), ()):
        try:
            await self._invoke(listener, event)
        except Exception as exc:
            report_exception(exc, listener=getattr(listener, "__qualname__", repr(listener)))
            logger.exception("Event listener %r raised while handling %r", listener, event)
```

### EventServiceProvider

```python
EventServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Binds an :class:`EventDispatcher` into the container.

Register your own listeners by subclassing and overriding `boot()` (calling `super().boot()` first, so the dispatcher exists) -- registration happens once, at startup, the same way route modules and other providers wire themselves up::

```text
class AppEventServiceProvider(EventServiceProvider):
    def boot(self) -> None:
        super().boot()
        dispatcher = self.container.make(EventDispatcher)
        dispatcher.listen(OrderPlaced, send_receipt_email)
        dispatcher.listen(OrderPlaced, notify_fulfillment_webhook)
```

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

### emit

```python
emit(request: Request, event: object) -> None
```

Dispatch `event` to every listener registered for its type.

Uses whichever :class:`EventDispatcher` is bound in the container (see :class:`EventServiceProvider`). Outside of a request -- a job, a scheduled task, a model hook -- dispatch directly against a resolved dispatcher instead::

```text
await app.container.make(EventDispatcher).dispatch(event)
```

Source code in `src/zeython/events.py`

```python
async def emit(request: Request, event: object) -> None:
    """Dispatch ``event`` to every listener registered for its type.

    Uses whichever :class:`EventDispatcher` is bound in the container (see
    :class:`EventServiceProvider`). Outside of a request -- a job, a
    scheduled task, a model hook -- dispatch directly against a resolved
    dispatcher instead::

        await app.container.make(EventDispatcher).dispatch(event)
    """
    dispatcher: EventDispatcher = request.app.state.container.make(EventDispatcher)
    await dispatcher.dispatch(event)
```

## feature_flags

Feature flags: name a capability, decide who gets it, check it from anywhere. Static (`.env`-driven) toggles and deterministic percentage rollouts -- no database or Redis required. Mirrors the boolean/rollout building blocks of Laravel Pennant, without persisted per-user storage; :meth:`FeatureManager.define` takes a custom resolver if you need a flag backed by a real store (a table, a third-party flag service) instead.

### FeatureManager

```python
FeatureManager(*, config: Config | None = None)
```

Holds every defined feature flag and resolves them per-context.

Bound in the container by :class:`FeatureServiceProvider` -- define flags in your own subclass of it (the same pattern :class:`~zeython.events.EventServiceProvider` uses)::

```text
class AppFeatureServiceProvider(FeatureServiceProvider):
    def boot(self) -> None:
        super().boot()
        manager = self.container.make(FeatureManager)
        manager.boolean("new_checkout")
        manager.percentage("beta_dashboard", rollout=10)
```

Source code in `src/zeython/feature_flags.py`

```python
def __init__(self, *, config: Config | None = None) -> None:
    self._config = config
    self._resolvers: dict[str, Resolver] = {}
```

#### define

```python
define(name: str, resolver: Resolver) -> None
```

Register a flag with a custom resolver. `resolver(context)` returns (or awaits to) a bool -- `context` is whatever the caller of :meth:`active`/:func:`feature` passed, typically the current user, `None` for a flag that doesn't vary per-request.

Source code in `src/zeython/feature_flags.py`

```python
def define(self, name: str, resolver: Resolver) -> None:
    """Register a flag with a custom resolver. ``resolver(context)``
    returns (or awaits to) a bool -- ``context`` is whatever the
    caller of :meth:`active`/:func:`feature` passed, typically the
    current user, ``None`` for a flag that doesn't vary per-request."""
    self._resolvers[name] = resolver
```

#### boolean

```python
boolean(name: str, *, default: bool = False) -> None
```

A static on/off flag, controlled via `.env` (`FEATURE_<NAME>`) without touching code -- flip it in a deployment's environment and restart, no redeploy of code needed.

Resolves `default` for every context alike -- there's no per-user variation here; use :meth:`percentage` or :meth:`define` for that.

Source code in `src/zeython/feature_flags.py`

```python
def boolean(self, name: str, *, default: bool = False) -> None:
    """A static on/off flag, controlled via ``.env``
    (``FEATURE_<NAME>``) without touching code -- flip it in a
    deployment's environment and restart, no redeploy of code needed.

    Resolves ``default`` for every context alike -- there's no
    per-user variation here; use :meth:`percentage` or :meth:`define`
    for that.
    """
    config = self._config

    def resolver(context: Any) -> bool:
        if config is None:
            return default
        return bool(config.get(f"feature.{name}", default))

    self.define(name, resolver)
```

#### percentage

```python
percentage(
    name: str, *, rollout: float, on: bool = True
) -> None
```

A deterministic rollout: the same `context` always lands on the same side of the flag, so a percentage-rolled-out feature doesn't flicker on and off for the same user across requests -- no database write needed to get that stability, just a stable hash of `(name, context)`.

Buckets by `context.id` if present, else `str(context)` -- pass whatever stable identifier makes sense for a flag with no natural object to check against (a request ID, a tenant slug).

Source code in `src/zeython/feature_flags.py`

```python
def percentage(self, name: str, *, rollout: float, on: bool = True) -> None:
    """A deterministic rollout: the same ``context`` always lands on
    the same side of the flag, so a percentage-rolled-out feature
    doesn't flicker on and off for the same user across requests --
    no database write needed to get that stability, just a stable
    hash of ``(name, context)``.

    Buckets by ``context.id`` if present, else ``str(context)`` --
    pass whatever stable identifier makes sense for a flag with no
    natural object to check against (a request ID, a tenant slug).
    """
    if not 0 <= rollout <= 100:
        raise ValueError(f"rollout must be between 0 and 100, got {rollout}")

    def resolver(context: Any) -> bool:
        key = str(getattr(context, "id", context))
        digest = hashlib.sha256(f"{name}:{key}".encode()).hexdigest()
        bucket = int(digest[:8], 16) % 100
        return on if bucket < rollout else not on

    self.define(name, resolver)
```

#### names

```python
names() -> list[str]
```

Every flag name currently defined, for introspection (`zeython features`).

Source code in `src/zeython/feature_flags.py`

```python
def names(self) -> list[str]:
    """Every flag name currently defined, for introspection (`zeython features`)."""
    return sorted(self._resolvers)
```

#### active

```python
active(name: str, context: Any = None) -> bool
```

Whether `name` is active for `context`.

An undefined flag resolves `False` and logs a warning -- most likely a typo, or a flag checked before its own `FeatureServiceProvider` subclass registered it. Never raises, so a flag check is always safe to sprinkle into a request path.

Source code in `src/zeython/feature_flags.py`

```python
async def active(self, name: str, context: Any = None) -> bool:
    """Whether ``name`` is active for ``context``.

    An undefined flag resolves ``False`` and logs a warning -- most
    likely a typo, or a flag checked before its own
    ``FeatureServiceProvider`` subclass registered it. Never raises,
    so a flag check is always safe to sprinkle into a request path.
    """
    resolver = self._resolvers.get(name)
    if resolver is None:
        logger.warning("Unknown feature flag %r checked -- resolves to False.", name)
        return False
    result = resolver(context)
    if inspect.isawaitable(result):
        result = await result
    return bool(result)
```

### FeatureServiceProvider

```python
FeatureServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Binds a :class:`FeatureManager` into the container.

Register no flags on its own -- subclass it and override `boot()` (calling `super().boot()` first, so the manager exists) to define your own, the same pattern :class:`~zeython.events.EventServiceProvider` uses. See docs/feature-flags.md.

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

### feature

```python
feature(
    request: Request, name: str, context: Any = None
) -> bool
```

Whether `name` is active, using whichever :class:`FeatureManager` is bound in the container (see :class:`FeatureServiceProvider`). Outside of a request -- a job, a scheduled task -- resolve directly instead::

```text
manager = app.container.make(FeatureManager)
await manager.active("new_checkout", context=user)
```

Source code in `src/zeython/feature_flags.py`

```python
async def feature(request: Request, name: str, context: Any = None) -> bool:
    """Whether ``name`` is active, using whichever :class:`FeatureManager`
    is bound in the container (see :class:`FeatureServiceProvider`).
    Outside of a request -- a job, a scheduled task -- resolve directly
    instead::

        manager = app.container.make(FeatureManager)
        await manager.active("new_checkout", context=user)
    """
    manager: FeatureManager = request.app.state.container.make(FeatureManager)
    return await manager.active(name, context)
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
    action_map: dict[str, tuple[tuple[str, ...], str]] = {
        "index": (("GET",), ""),
        "store": (("POST",), ""),
        "show": (("GET",), "/{id}"),
        "update": (("PUT", "PATCH"), "/{id}"),
        "destroy": (("DELETE",), "/{id}"),
    }
    allowed = set(only) if only is not None else set(action_map)

    for action, (methods, suffix) in action_map.items():
        if action not in allowed or not hasattr(controller, action):
            continue
        handler = getattr(controller, action)
        route_path = self._full_path(f"{path.rstrip('/')}{suffix}")
        self.routes.append(
            Route(route_path, handler, methods=list(methods), name=f"{path.strip('/')}.{action}")
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

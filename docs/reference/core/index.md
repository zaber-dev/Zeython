# Core

The application bootstrap, DI container, config, routing, service providers, the application-level event dispatcher, feature flags, view rendering, the framework's exception/validation primitives, and its own testing utilities.

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

Fully synchronous by design (bindings resolve at boot, well before an event loop is necessarily running) -- an async factory is rejected with a clear error rather than silently returning an unawaited, never-usable coroutine that a shared/singleton binding would then cache and hand out forever. A circular dependency (`A` needing `B` needing `A`) is likewise rejected with a clear error instead of recursing until Python's own `RecursionError`.

Source code in `src/zeython/container.py`

```python
def __init__(self) -> None:
    self._bindings: dict[Abstract, _Binding] = {}
    self._instances: dict[Abstract, Any] = {}
    self._resolving: list[Abstract] = []
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

    if abstract in self._resolving:
        chain = " -> ".join(str(a) for a in (*self._resolving, abstract))
        raise BindingResolutionError(f"Circular dependency detected: {chain}")

    binding = self._bindings.get(abstract)
    factory = binding.factory if binding else abstract

    if not callable(factory):
        raise BindingResolutionError(
            f"Cannot resolve unbound abstract type {abstract!r}"
        )

    # Unlike call() (also used to autowire an async handler's
    # arguments -- e.g. Queue._invoke's `await container.call(job.handle)`
    # -- where returning a coroutine for the caller to await is
    # completely normal), make() promises a ready-to-use instance
    # *right now*. An async factory can't deliver that: it would
    # silently hand back a never-awaited coroutine instead, and for a
    # shared/singleton binding, cache that same dead coroutine and
    # return it from every future make() call.
    if inspect.iscoroutinefunction(factory):
        raise BindingResolutionError(
            f"{factory!r} is an async factory bound for {abstract!r} -- make() needs a "
            "ready instance synchronously and can't await it. Bind a synchronous factory, "
            "or construct the instance yourself in an async context and register it with "
            "container.instance(...)."
        )

    self._resolving.append(abstract)
    try:
        instance = self.call(factory, **overrides)
    finally:
        self._resolving.pop()

    if inspect.isawaitable(instance):
        raise BindingResolutionError(
            f"The factory bound for {abstract!r} returned an awaitable instead of a real "
            "instance -- make() needs a ready instance synchronously and can't await it. "
            "Bind a synchronous factory, or construct the instance yourself in an async "
            "context and register it with container.instance(...)."
        )

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

#### debug

```python
debug: bool
```

`APP_DEBUG` -- `False` unless explicitly set to true.

Deliberately *not* inferred from :attr:`environment` (e.g. `environment != "production"`): that would make debug mode -- full tracebacks, executed SQL, and (for a browser request) an HTML page with source snippets, all in the response body -- the default the moment `APP_ENV` is merely left unset, which is exactly the kind of thing that's easy to forget on a real deployment (`DATABASE_URL`/`APP_SECRET_KEY` tend to get remembered; `APP_ENV` doesn't always). Debug output now requires an affirmative `APP_DEBUG=true` -- which is exactly what `zeython new`'s generated `.env.example` already sets for local development, so this doesn't change the default local dev experience at all.

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
Router(prefix: str = '', *, api_version: str | None = None)
```

Collects routes and exposes Laravel/FastAPI-style decorator sugar.

A `Router` compiles down to a plain list of Starlette `BaseRoute` objects, so nesting via :meth:`include` is just a `Mount` and gets the same battle-tested path matching as everything else built on Starlette.

Source code in `src/zeython/routing.py`

```python
def __init__(self, prefix: str = "", *, api_version: str | None = None) -> None:
    self.prefix = prefix.rstrip("/")
    self.routes: list[BaseRoute] = []
    self._api_version = api_version
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
        self.routes.append(
            WebSocketRoute(self._full_path(path), self._versioned(endpoint), name=name or endpoint.__name__)
        )
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

#### version

```python
version(
    version: str, *, prefix: str | None = None
) -> Iterator[Router]
```

Group routes under a version prefix, with :func:`current_api_version` set during each call.

Yields a sub-:class:`Router` to register routes on; it's mounted onto this router only once the `with` block finishes, so build it up fully inside the block::

```text
with app.router.version("v1") as v1:
    v1.resource("/posts", PostControllerV1)
```

Defaults `prefix` to `/{version}` (so `"v1"` mounts at `/v1`); pass `prefix=""` to version routes without changing their path.

Source code in `src/zeython/routing.py`

```python
@contextmanager
def version(self, version: str, *, prefix: str | None = None) -> Iterator[Router]:
    """Group routes under a version prefix, with :func:`current_api_version` set during each call.

    Yields a sub-:class:`Router` to register routes on; it's mounted
    onto this router only once the ``with`` block finishes, so build it
    up fully inside the block::

        with app.router.version("v1") as v1:
            v1.resource("/posts", PostControllerV1)

    Defaults ``prefix`` to ``/{version}`` (so ``"v1"`` mounts at
    ``/v1``); pass ``prefix=""`` to version routes without changing
    their path.
    """
    sub_prefix = self.prefix + (prefix if prefix is not None else f"/{version}")
    sub = Router(sub_prefix, api_version=version)
    yield sub
    # Not routed through include()/Mount: the sub-router already bakes
    # its full prefix into every route it registers, so mounting it
    # under another prefix would double it up -- and mounting several
    # versions each at "/" would have every one of them match (and
    # claim) every request, since a Mount's own prefix strips to "" at
    # "/". Flattening its already-fully-pathed routes in directly
    # avoids both problems.
    self.routes.extend(sub.routes)
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

Maps: index->GET path, store->POST path, show->GET path/{id:int}, update->PUT/PATCH path/{id:int}, destroy->DELETE path/{id:int}.

`{id:int}`, not a plain `{id}` -- every :class:`~zeython.db.Model`'s primary key is an integer, so a request for e.g. `/posts/abc` fails route *matching* itself (a clean 404, same as an unknown route) instead of reaching the handler and blowing up on `int(request.path_params["id"])`, the conversion every generated `show`/`update`/`destroy` action does next.

Source code in `src/zeython/routing.py`

```python
def resource(self, path: str, controller_cls: type[Controller], *, only: Iterable[str] | None = None) -> None:
    """Register RESTful CRUD routes bound to a controller's methods.

    Maps: index->GET path, store->POST path, show->GET path/{id:int},
    update->PUT/PATCH path/{id:int}, destroy->DELETE path/{id:int}.

    ``{id:int}``, not a plain ``{id}`` -- every :class:`~zeython.db.Model`'s
    primary key is an integer, so a request for e.g. ``/posts/abc``
    fails route *matching* itself (a clean 404, same as an unknown
    route) instead of reaching the handler and blowing up on
    ``int(request.path_params["id"])``, the conversion every generated
    ``show``/``update``/``destroy`` action does next.
    """
    controller = controller_cls()
    action_map: dict[str, tuple[tuple[str, ...], str]] = {
        "index": (("GET",), ""),
        "store": (("POST",), ""),
        "show": (("GET",), "/{id:int}"),
        "update": (("PUT", "PATCH"), "/{id:int}"),
        "destroy": (("DELETE",), "/{id:int}"),
    }
    allowed = set(only) if only is not None else set(action_map)

    for action, (methods, suffix) in action_map.items():
        if action not in allowed or not hasattr(controller, action):
            continue
        handler = getattr(controller, action)
        route_path = self._full_path(f"{path.rstrip('/')}{suffix}")
        self.routes.append(
            Route(
                route_path,
                self._versioned(handler),
                methods=list(methods),
                name=f"{path.strip('/')}.{action}",
            )
        )
```

### current_api_version

```python
current_api_version() -> str | None
```

The version label (e.g. `"v1"`) the current request was routed under.

`None` outside a request, or inside one routed through a plain (non-versioned) :class:`Router`. Set for the duration of an endpoint call registered via :meth:`Router.version`.

Source code in `src/zeython/routing.py`

```python
def current_api_version() -> str | None:
    """The version label (e.g. ``"v1"``) the current request was routed under.

    ``None`` outside a request, or inside one routed through a plain
    (non-versioned) :class:`Router`. Set for the duration of an endpoint
    call registered via :meth:`Router.version`.
    """
    return _current_api_version.get()
```

### deprecated

```python
deprecated(
    *, sunset: str | None = None
) -> Callable[[Endpoint], Endpoint]
```

Mark an endpoint deprecated, signaling it with standard HTTP headers.

Sets `Deprecation: true` (per the IETF draft) on every response, and `Sunset: <sunset>` (an RFC 8594 HTTP-date, per RFC 7231 section 7.1.1.1) when a removal date is known::

```text
@app.router.get("/v1/reports")
@deprecated(sunset="Wed, 01 Jan 2027 00:00:00 GMT")
async def old_reports(request: Request) -> Response: ...
```

Source code in `src/zeython/routing.py`

```python
def deprecated(*, sunset: str | None = None) -> Callable[[Endpoint], Endpoint]:
    """Mark an endpoint deprecated, signaling it with standard HTTP headers.

    Sets ``Deprecation: true`` (per the IETF draft) on every response, and
    ``Sunset: <sunset>`` (an RFC 8594 HTTP-date, per RFC 7231 section 7.1.1.1)
    when a removal date is known::

        @app.router.get("/v1/reports")
        @deprecated(sunset="Wed, 01 Jan 2027 00:00:00 GMT")
        async def old_reports(request: Request) -> Response: ...
    """

    def decorator(endpoint: Endpoint) -> Endpoint:
        @functools.wraps(endpoint)
        async def wrapper(*args: Any, **kwargs: Any) -> Response:
            response: Response = await endpoint(*args, **kwargs)
            response.headers["Deprecation"] = "true"
            if sunset is not None:
                response.headers["Sunset"] = sunset
            return response

        return wrapper

    return decorator
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

Only works as intended when `raise`\\ d from *inside routing* -- a route handler, or code it calls. Starlette's own `ExceptionMiddleware` (which owns the per-class handlers :func:`default_exception_handlers` registers for this hierarchy) sits *inside* every `add_middleware()` layer, wrapping only the router. Raising an `HTTPException` directly from a custom pure-ASGI middleware's `__call__` -- rather than a route handler -- skips that layer entirely: the exception propagates to `ServerErrorMiddleware` instead (outside everything), which has no per-class handler for it, so it's treated as a genuine unhandled error -- the intended status code and `headers=` are lost, and the caller gets a generic 500 instead. Call the handler directly and return/send its response instead of raising -- :class:`~zeython.csrf.CsrfMiddleware` does exactly this (see its `__call__`) specifically to avoid this trap.

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

## testing

Test helpers for Zeython applications.

### client

```python
client(
    app: Application, *, base_url: str = "http://testserver"
) -> AsyncIterator[httpx.AsyncClient]
```

An `httpx.AsyncClient` wired directly to the app's ASGI callable, no sockets involved.

Named `client` rather than `test_client` so pytest's `test_*` collection doesn't mistake this helper for a test function when imported into a test module.

Automatically attaches the CSRF header (see :mod:`zeython.csrf`) from whatever `csrf_token` cookie this client is already holding -- the same thing a real browser-based app does by reading the cookie in JS, so a test doesn't need to plumb the token through by hand. This still means the *first* unsafe request in a test needs a prior safe one (a `GET`) to actually receive that cookie -- there's nothing to attach before that.

Usage::

```text
async with client(app) as http:
    await http.get("/")  # picks up the csrf_token cookie
    response = await http.post("/posts", json={"title": "t"})
    assert response.status_code == 201
```

Source code in `src/zeython/testing.py`

```python
@asynccontextmanager
async def client(app: Application, *, base_url: str = "http://testserver") -> AsyncIterator[httpx.AsyncClient]:
    """An ``httpx.AsyncClient`` wired directly to the app's ASGI callable, no sockets involved.

    Named ``client`` rather than ``test_client`` so pytest's ``test_*`` collection
    doesn't mistake this helper for a test function when imported into a test module.

    Automatically attaches the CSRF header (see :mod:`zeython.csrf`) from
    whatever ``csrf_token`` cookie this client is already holding -- the
    same thing a real browser-based app does by reading the cookie in JS,
    so a test doesn't need to plumb the token through by hand. This still
    means the *first* unsafe request in a test needs a prior safe one (a
    ``GET``) to actually receive that cookie -- there's nothing to attach
    before that.

    Usage::

        async with client(app) as http:
            await http.get("/")  # picks up the csrf_token cookie
            response = await http.post("/posts", json={"title": "t"})
            assert response.status_code == 201
    """

    async def _attach_csrf_header(request: httpx.Request) -> None:
        token = http_client.cookies.get(DEFAULT_COOKIE_NAME)
        if token is not None:
            request.headers.setdefault(DEFAULT_HEADER_NAME, token)

    transport = httpx.ASGITransport(app=app.asgi)
    http_client = httpx.AsyncClient(
        transport=transport, base_url=base_url, event_hooks={"request": [_attach_csrf_header]}
    )
    async with http_client:
        yield http_client
```

### login_as

```python
login_as(
    http_client: AsyncClient, app: Application, user: Any
) -> None
```

Log `http_client` in as `user` directly, without a real `POST /login` -- for a test that needs an authenticated request but isn't specifically testing the login flow itself::

```text
async with client(app) as http:
    login_as(http, app, user)
    response = await http.get("/me")
    assert response.status_code == 200
```

Builds the exact signed session cookie Starlette's own `SessionMiddleware` would set after a real `login(request, user)` call (see :mod:`zeython.auth`) -- same secret key, same cookie name (`SESSION_COOKIE_NAME`, default `zeython_session`) -- and sets it directly on the client, so :func:`~zeython.auth.require_auth` and :func:`~zeython.auth.current_user` see a real logged-in session on the very next request. Requires `AuthServiceProvider` to be registered (same requirement `login()` itself has).

Source code in `src/zeython/testing.py`

```python
def login_as(http_client: httpx.AsyncClient, app: Application, user: Any) -> None:
    """Log ``http_client`` in as ``user`` directly, without a real
    ``POST /login`` -- for a test that needs an authenticated request but
    isn't specifically testing the login flow itself::

        async with client(app) as http:
            login_as(http, app, user)
            response = await http.get("/me")
            assert response.status_code == 200

    Builds the exact signed session cookie Starlette's own
    ``SessionMiddleware`` would set after a real ``login(request, user)``
    call (see :mod:`zeython.auth`) -- same secret key, same cookie name
    (``SESSION_COOKIE_NAME``, default ``zeython_session``) -- and sets it
    directly on the client, so :func:`~zeython.auth.require_auth` and
    :func:`~zeython.auth.current_user` see a real logged-in session on the
    very next request. Requires ``AuthServiceProvider`` to be registered
    (same requirement ``login()`` itself has).
    """
    from zeython.auth import _SESSION_KEY

    cookie_name = app.config.get("session.cookie_name", "zeython_session")
    signer = itsdangerous.TimestampSigner(str(app.config.secret_key))
    payload = base64.b64encode(json.dumps({_SESSION_KEY: user.id}).encode("utf-8"))
    signed = signer.sign(payload)
    http_client.cookies.set(cookie_name, signed.decode("utf-8"))
```

### transactional_session

```python
transactional_session(
    database: Database,
) -> AsyncIterator[AsyncSession]
```

Opens one session for an entire test and rolls it back unconditionally on exit, regardless of whether the block raised -- for a test that writes real data through the Active Record API and wants it visible to queries made anywhere in the same test, without that data persisting past it.

Most valuable against a real Postgres/MySQL test database, where recreating the schema per test (the usual alternative) is slow. Against SQLite's own `:memory:` URL -- what the framework's own test suite and `zeython new`'s default scaffold both use -- a fresh :class:`~zeython.db.Database` per test already gets the same isolation for free, so this mostly matters once a project's tests run against its real production database engine::

```text
@pytest_asyncio.fixture
async def db_session(database: Database):
    async with transactional_session(database):
        yield
```

Requires the caller to hold a reference to the app's :class:`~zeython.db.Database` directly (e.g. via `app.container.make(Database)`) -- unlike :meth:`Database.session`, this doesn't commit, so nesting it inside a request handled by `DatabaseSessionMiddleware` would conflict with that middleware's own session for the same context; use it to wrap a whole test instead.

Source code in `src/zeython/testing.py`

```python
@asynccontextmanager
async def transactional_session(database: Database) -> AsyncIterator[AsyncSession]:
    """Opens one session for an entire test and rolls it back
    unconditionally on exit, regardless of whether the block raised --
    for a test that writes real data through the Active Record API and
    wants it visible to queries made anywhere in the same test, without
    that data persisting past it.

    Most valuable against a real Postgres/MySQL test database, where
    recreating the schema per test (the usual alternative) is slow.
    Against SQLite's own ``:memory:`` URL -- what the framework's own test
    suite and `zeython new`'s default scaffold both use -- a fresh
    :class:`~zeython.db.Database` per test already gets the same
    isolation for free, so this mostly matters once a project's tests run
    against its real production database engine::

        @pytest_asyncio.fixture
        async def db_session(database: Database):
            async with transactional_session(database):
                yield

    Requires the caller to hold a reference to the app's
    :class:`~zeython.db.Database` directly (e.g. via
    ``app.container.make(Database)``) -- unlike :meth:`Database.session`,
    this doesn't commit, so nesting it inside a request handled by
    ``DatabaseSessionMiddleware`` would conflict with that middleware's
    own session for the same context; use it to wrap a whole test instead.
    """
    session = database.session_factory()
    token = _current_session.set(session)
    try:
        yield session
    finally:
        await session.rollback()
        await session.close()
        _current_session.reset(token)
```

### websocket_client

```python
websocket_client(app: Application) -> TestClient
```

A `starlette.testclient.TestClient` wired to the app's ASGI callable, for testing WebSocket routes.

Unlike :func:`client`, this is synchronous -- httpx has no WebSocket support, and Starlette's own `TestClient` is what actually drives a WebSocket handshake against an ASGI app in tests, no real socket involved either way.

Usage::

```text
with websocket_client(app).websocket_connect("/ws/chat") as ws:
    ws.send_text("hi")
    assert ws.receive_text() == "hi"
```

Source code in `src/zeython/testing.py`

```python
def websocket_client(app: Application) -> TestClient:
    """A ``starlette.testclient.TestClient`` wired to the app's ASGI callable, for testing WebSocket routes.

    Unlike :func:`client`, this is synchronous -- httpx has no WebSocket
    support, and Starlette's own ``TestClient`` is what actually drives a
    WebSocket handshake against an ASGI app in tests, no real socket
    involved either way.

    Usage::

        with websocket_client(app).websocket_connect("/ws/chat") as ws:
            ws.send_text("hi")
            assert ws.receive_text() == "hi"
    """
    return TestClient(app.asgi)
```

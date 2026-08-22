# Extensibility

Custom console commands, the plugin registry, localization, the auto-generated admin panel, and AI integration.

## console

Custom CLI commands: the `app/Console/Commands/` extension point.

Laravel's Artisan and Django's `manage.py` both let an application define its own CLI commands, wired into the same container/config the rest of the app uses -- without that, a one-off script (a data import, a cleanup job) ends up disconnected from the app entirely: its own hand-rolled `Application()` bootstrap, no access to `container.make(...)`, easy to drift from how the real app is actually configured. `zeython command <name>` closes that gap.

One file per command in `app/Console/Commands/`, one `Command` subclass per file -- `zeython make command SendReport` scaffolds one. The command's CLI name defaults to the snake_case filename; override with a `name` class attribute for something else (`reports:send`, ...).

### Command

```python
Command(app: Application)
```

Bases: `ABC`

Base class for a custom `zeython command <name>` CLI command.

Source code in `src/zeython/console.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

#### handle

```python
handle(*args: str) -> None
```

Do the work. `args` are the raw extra CLI arguments after the command name.

Runs outside any request, so there's no request-scoped database session automatically available -- open one explicitly if you need one, the same way any other out-of-request code does::

```text
async def handle(self, *args: str) -> None:
    database: Database = self.container.make(Database)
    async with database.session():
        ...
```

Source code in `src/zeython/console.py`

```python
@abstractmethod
async def handle(self, *args: str) -> None:
    """Do the work. ``args`` are the raw extra CLI arguments after the command name.

    Runs outside any request, so there's no request-scoped database
    session automatically available -- open one explicitly if you need
    one, the same way any other out-of-request code does::

        async def handle(self, *args: str) -> None:
            database: Database = self.container.make(Database)
            async with database.session():
                ...
    """
```

### discover_commands

```python
discover_commands(
    project_root: Path,
) -> dict[str, type[Command]]
```

Every :class:`Command` subclass in `app/Console/Commands/*.py`, keyed by CLI name.

Source code in `src/zeython/console.py`

```python
def discover_commands(project_root: Path) -> dict[str, type[Command]]:
    """Every :class:`Command` subclass in ``app/Console/Commands/*.py``, keyed by CLI name."""
    commands_dir = project_root / "app" / "Console" / "Commands"
    commands: dict[str, type[Command]] = {}
    if not commands_dir.is_dir():
        return commands

    root_str = str(project_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    sync_project_modules(project_root)

    # A freshly-scaffolded command file may not exist yet as far as the
    # path-based finder's directory-listing cache is concerned (e.g. right
    # after `zeython make command` wrote it) -- safe to call unconditionally,
    # unlike the sys.modules purge in sync_project_modules() above, since this
    # only clears finder caches and never un-registers an already-imported
    # module.
    importlib.invalidate_caches()

    for path in sorted(commands_dir.glob("*.py")):
        if path.stem == "__init__":
            continue

        module = importlib.import_module(f"app.Console.Commands.{path.stem}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is Command or not issubclass(obj, Command):
                continue
            if obj.__module__ != module.__name__:
                continue  # e.g. `from zeython.console import Command` itself, not a real command

            # `zeython make command` names the file with a `_command` suffix
            # (matching `make job`'s `_job.py` convention) but promises a
            # CLI name with that suffix stripped -- mirror the same stripping
            # here so a scaffolded command is actually runnable under the
            # name its own generated docstring claims.
            command_name = obj.name or path.stem.removesuffix("_command").replace("_", "-")
            commands[command_name] = obj

    return commands
```

## plugins

Plugin discovery: letting a pip-installed third-party package register its own service provider(s) with a Zeython app, without the app author having to add an `app.register(...)` line for every package.

Every other extension point in the framework is an explicit :class:`~zeython.providers.ServiceProvider`, registered by one line in `main.py` -- nothing auto-wires itself in behind the app author's back (see `SecurityHeadersServiceProvider`, `ErrorMonitoringServiceProvider`, etc., all opt-in). Plugins follow the same rule at the app level: a plugin package changes nothing until the app author registers :class:`PluginServiceProvider` once. From then on, *which* packages contribute providers is driven by what's `pip install`ed, the same way Laravel's package auto-discovery or Django's `INSTALLED_APPS` works -- one line turns on discovery, not one line per package.

A plugin package declares itself via a standard Python entry point in its own `pyproject.toml`::

```text
[project.entry-points."zeython.plugins"]
my_plugin = "my_package.providers:MyPluginServiceProvider"
```

The value is an import path to a :class:`~zeython.providers.ServiceProvider` subclass (or an instance), exactly what `app.register(...)` already accepts directly.

### PluginServiceProvider

```python
PluginServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Registers every plugin found by :func:`discover_plugins`.

Register this once, anywhere in `main.py`. A plugin adding routes should do it in its own `register()` (like the built-in `RouteServiceProvider`) -- route/model introspection (`zeython routes`/`about`, the MCP server's `list_routes`) reflects the app right after every provider's `register()` phase, not after `boot()`, which only runs lazily on the first real request. A plugin that needs another provider's binding already in place (`Gate`, `Database`) should defer that specific part to its own `boot()`, for the same reason every built-in provider does -- see docs/architecture.md. See docs/plugins.md.

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

### discover_plugins

```python
discover_plugins() -> list[
    type[ServiceProvider] | ServiceProvider
]
```

Load every provider registered under the `zeython.plugins` entry-point group by an installed package.

A plugin that fails to import is left to raise -- a broken or misconfigured plugin should fail loudly at boot, not vanish silently from an app that's relying on it.

Source code in `src/zeython/plugins.py`

```python
def discover_plugins() -> list[type[ServiceProvider] | ServiceProvider]:
    """Load every provider registered under the ``zeython.plugins`` entry-point
    group by an installed package.

    A plugin that fails to import is left to raise -- a broken or
    misconfigured plugin should fail loudly at boot, not vanish silently
    from an app that's relying on it.
    """
    return [entry_point.load() for entry_point in entry_points(group=_ENTRY_POINT_GROUP)]
```

## localization

Translation strings and per-request locale resolution.

Translations live in flat JSON files, one per locale, under `resources/lang/` by convention (`resources/lang/en.json`, `resources/lang/es.json`, ...) -- a dotted key mapped to its translated string, e.g. `{"welcome.title": "Welcome!", "greeting": "Hello, {name}!"}`. :class:`Translator` loads and caches them, resolving a key against the current request's locale (with a fallback locale for a missing key) and substituting `{name}`-style parameters.

`LocaleMiddleware` resolves the locale for each request -- an explicit `?lang=xx` query parameter, then the `Accept-Language` header, then the configured default -- against whichever locales actually have a translation file on disk, and makes it available to :func:`current_locale` for the request's duration via a :class:`~contextvars.ContextVar`, the same technique :func:`~zeython.request_id.request_id` uses. Translating a string never needs a `request` threaded through every call as a result -- `Translator.t()` (and the `t` global :class:`LocalizationServiceProvider` registers for Jinja templates) reads the current locale from that contextvar directly.

### Translator

```python
Translator(
    path: str | Path,
    *,
    default_locale: str = "en",
    fallback_locale: str | None = None,
)
```

Loads `{locale}.json` translation files from `path` and looks up keys by exact match, falling back to `fallback_locale` for a key missing from the requested locale, and to the key itself (so a missing translation degrades to something readable, not a crash) if it's missing from the fallback too.

Source code in `src/zeython/localization.py`

```python
def __init__(self, path: str | Path, *, default_locale: str = "en", fallback_locale: str | None = None) -> None:
    self.path = Path(path)
    self.default_locale = default_locale
    self.fallback_locale = fallback_locale or default_locale
    self._cache: dict[str, dict[str, str]] = {}
```

#### available_locales

```python
available_locales: set[str]
```

Locales with a translation file on disk -- what :class:`LocaleMiddleware` negotiates against. Empty for a project that hasn't added any yet, in which case every request just resolves to `default_locale`.

#### t

```python
t(
    key: str, *, locale: str | None = None, **params: Any
) -> str
```

Translate `key`, in `locale` if given, otherwise :func:`current_locale` (or `default_locale` outside a request). Any keyword arguments fill `{name}`-style placeholders in the translated string via `str.format` -- a placeholder with no matching argument is left as-is rather than raising.

Source code in `src/zeython/localization.py`

```python
def t(self, key: str, *, locale: str | None = None, **params: Any) -> str:
    """Translate ``key``, in ``locale`` if given, otherwise
    :func:`current_locale` (or ``default_locale`` outside a request).
    Any keyword arguments fill ``{name}``-style placeholders in the
    translated string via ``str.format`` -- a placeholder with no
    matching argument is left as-is rather than raising.
    """
    resolved_locale = locale or current_locale() or self.default_locale
    translations = self._translations_for(resolved_locale)
    if key not in translations and resolved_locale != self.fallback_locale:
        translations = self._translations_for(self.fallback_locale)
    text = translations.get(key, key)
    if params:
        with contextlib.suppress(KeyError, IndexError):
            text = text.format(**params)
    return text
```

### LocaleMiddleware

```python
LocaleMiddleware(
    app: Any,
    *,
    translator: Translator,
    query_param: str = "lang",
)
```

Pure ASGI middleware: resolves the request's locale and sets it as a contextvar for :func:`current_locale` (readable via :class:`Translator` without a `request` in hand) for the request's duration.

Source code in `src/zeython/localization.py`

```python
def __init__(self, app: Any, *, translator: Translator, query_param: str = "lang") -> None:
    self.app = app
    self.translator = translator
    self.query_param = query_param
```

### LocalizationServiceProvider

```python
LocalizationServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Binds a :class:`Translator` and registers :class:`LocaleMiddleware`.

- `LOCALE_PATH` -- default `resources/lang` under the project root.
- `LOCALE_DEFAULT` -- default `en`. Used when nothing else resolves a locale (no `?lang=`/`Accept-Language` match, or outside a request entirely).
- `LOCALE_FALLBACK` -- default: same as `LOCALE_DEFAULT`. Used when a key exists in some locale's file but not the requested one.
- `LOCALE_QUERY_PARAM` -- default `lang`. The query parameter a link can use to force a locale, e.g. `?lang=es`.

Also registers `t` as a Jinja global if :class:`~zeython.views.ViewServiceProvider` is registered, so a template can call `{{ t("welcome.title") }}` directly -- see docs/localization.md.

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

### current_locale

```python
current_locale() -> str | None
```

The current request's resolved locale, or `None` outside a request handled by :class:`LocaleMiddleware`.

Source code in `src/zeython/localization.py`

```python
def current_locale() -> str | None:
    """The current request's resolved locale, or ``None`` outside a request
    handled by :class:`LocaleMiddleware`."""
    return _current_locale.get()
```

### t

```python
t(request: Any, key: str, **params: Any) -> str
```

Translate `key` using the app's registered :class:`Translator`, in the current request's resolved locale. Usage inside a controller, exactly like :func:`~zeython.views.render`/:func:`~zeython.queue.dispatch`::

```text
from zeython.localization import t

async def show(self, request):
    return JSONResponse({"message": t(request, "welcome.title")})
```

Inside a Jinja template, call `t(...)` directly instead -- :class:`LocalizationServiceProvider` registers it as a template global, no `request` needed there. Outside a request entirely (a job, a script), resolve the translator directly instead: `app.container.make(Translator).t(key)`.

Source code in `src/zeython/localization.py`

```python
def t(request: Any, key: str, **params: Any) -> str:
    """Translate ``key`` using the app's registered :class:`Translator`, in
    the current request's resolved locale. Usage inside a controller,
    exactly like :func:`~zeython.views.render`/:func:`~zeython.queue.dispatch`::

        from zeython.localization import t

        async def show(self, request):
            return JSONResponse({"message": t(request, "welcome.title")})

    Inside a Jinja template, call ``t(...)`` directly instead --
    :class:`LocalizationServiceProvider` registers it as a template global,
    no ``request`` needed there. Outside a request entirely (a job, a
    script), resolve the translator directly instead:
    ``app.container.make(Translator).t(key)``.
    """
    container = request.app.state.container
    translator: Translator = container.make(Translator)
    return translator.t(key, **params)
```

## admin

An auto-generated CRUD admin UI for registered models.

Register a model and get list/create/edit/delete pages for it, generated from the model's own columns -- no hand-written admin templates, the same trade-off Django's admin makes. This is a lightweight v1, not a Django-admin clone: no relationship pickers (a foreign key column is a plain number input, you type the related row's ID), no search/filtering, no bulk actions. It's for internal, trusted-staff CRUD over your own models, not a public-facing UI -- see "What this isn't" below.

Every admin route requires a logged-in user (:func:`~zeython.auth.require_auth`) *and* an explicit `guard` callable you provide -- there is deliberately no default that lets any authenticated user in. Forcing that choice is the same reasoning as :class:`~zeython.security_headers.SecurityHeadersServiceProvider` having no default CSP: guessing a policy for you would be worse than requiring you to state one.

Pages are plain server-rendered HTML with a small inline script that turns a form submission into a `fetch` carrying the CSRF header (:mod:`zeython.csrf` reads the token from a header, not a form field -- see docs/csrf.md), not a second Jinja template system -- the admin UI works whether or not :class:`~zeython.views.ViewServiceProvider` is even registered.

### AdminServiceProvider

```python
AdminServiceProvider(
    app: Application,
    *,
    models: Sequence[type[Model]],
    guard: Guard,
    prefix: str = "/admin",
)
```

Bases: `ServiceProvider`

Registers a CRUD admin UI for `models` under `prefix` (default `/admin`).

`guard` is required, not optional -- `lambda user: getattr(user, "is_admin", False)` for a boolean flag on your user model, or anything else that returns (or awaits to) a bool. Every admin route also requires a logged-in user regardless of `guard` -- see :func:`~zeython.auth.require_auth`.

::

```text
from zeython import AdminServiceProvider
from app.Models.post import Post
from app.Models.user import User

app.register(AdminServiceProvider(
    app,
    models=[Post, User],
    guard=lambda user: user.is_admin,
))
```

See docs/admin.md.

Source code in `src/zeython/admin.py`

```python
def __init__(
    self,
    app: Application,
    *,
    models: Sequence[type[Model]],
    guard: Guard,
    prefix: str = "/admin",
) -> None:
    super().__init__(app)
    self.models = list(models)
    self.guard = guard
    self.prefix = prefix.rstrip("/") or "/admin"
```

## ai

AI-assisted app features: a small, provider-agnostic LLM client bound in the container, for calling a model from your own request handlers and jobs.

This is a different thing from `zeython.mcp`: that module lets an AI *agent* introspect and operate on a Zeython project (Laravel Boost's role). This module lets a Zeython *app* call an LLM as part of its own logic -- summarizing text, drafting a reply, classifying input -- the same role Vercel's AI SDK or LangChain's chat models play, kept to a fraction of the surface area.

Requires the `ai` extra (`pip install zeython[ai]`) only if you use :class:`AnthropicAI`; the interface and :class:`EchoAI` have no extra dependency.

### AI

Bases: `ABC`

A chat-style completion client.

#### complete

```python
complete(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 1024,
) -> AIResponse
```

Send `prompt` (plus optional `system` instructions) and return the model's reply.

Source code in `src/zeython/ai.py`

```python
@abstractmethod
async def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 1024) -> AIResponse:
    """Send ``prompt`` (plus optional ``system`` instructions) and return the model's reply."""
```

### EchoAI

Bases: `AI`

Returns the prompt back, unmodified, with no network call.

The default (`AI_PROVIDER=echo`) -- the same role :class:`~zeython.mail.LogMailer` and :class:`~zeython.queue.InMemoryQueue` play for their subsystems: a fresh `zeython new` project (and its tests) work immediately without external credentials. Switch to :class:`AnthropicAI` (`AI_PROVIDER=anthropic`) once you have an API key. See docs/ai.md.

### AnthropicAI

```python
AnthropicAI(*, api_key: str, model: str)
```

Bases: `AI`

Calls the Anthropic API via the official SDK. Requires the `ai` extra (`pip install zeython[ai]`).

Source code in `src/zeython/ai.py`

```python
def __init__(self, *, api_key: str, model: str) -> None:
    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:
        raise ImportError(
            "AnthropicAI requires the anthropic package. Install it with: pip install zeython[ai]"
        ) from exc

    self._client = AsyncAnthropic(api_key=api_key)
    self.model = model
```

### AIServiceProvider

```python
AIServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Binds an :class:`AI` client into the container from `.env`.

- `AI_PROVIDER` -- `echo` (default, no network/credentials) or `anthropic`
- `ANTHROPIC_API_KEY` -- required when `AI_PROVIDER=anthropic`
- `AI_MODEL` -- default `claude-sonnet-5`, only used by the `anthropic` provider

Not registered by default -- opt in with `app.register(AIServiceProvider)` once your app actually calls an LLM.

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

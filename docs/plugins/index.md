# Plugins

Every extension point in Zeython is a `ServiceProvider`, registered by one explicit line in `main.py` — nothing wires itself in behind your back. Plugins follow the same rule at the package level: installing a plugin package changes nothing until you register `PluginServiceProvider` once. From then on, *which* packages actually contribute something is driven by what's `pip install`ed — one line turns on discovery, not one line per package, the same way Laravel's package auto-discovery or Django's `INSTALLED_APPS` works.

## Using a plugin

```python
# main.py
from zeython import Application, PluginServiceProvider

app = Application()
app.register(PluginServiceProvider)
```

That's it — every plugin package currently installed gets its provider(s) registered (and booted, in the normal boot pass) automatically. Uninstall the package and it stops contributing anything, with no leftover line in `main.py` to clean up.

## Writing a plugin

A plugin is just a pip-installable package that ships a normal `ServiceProvider` and declares it under the `zeython.plugins` entry-point group in its own `pyproject.toml`:

```python
# my_zeython_plugin/providers.py
from zeython import ServiceProvider


class MyPluginServiceProvider(ServiceProvider):
    def register(self) -> None:
        """Bind services into the container."""

    def boot(self) -> None:
        """Run once every provider (including the host app's own) has registered."""
```

```toml
# pyproject.toml, in the plugin package
[project.entry-points."zeython.plugins"]
my_plugin = "my_zeython_plugin.providers:MyPluginServiceProvider"
```

The entry point's value is an import path to the provider class itself — exactly what `app.register(...)` already accepts directly, so there's nothing plugin-specific about the provider itself.

A plugin that adds routes should do it in its own `register()`, the same way the built-in `RouteServiceProvider` does — `zeython routes`/`about` and the MCP server's `list_routes`/`app_info` tools inspect the app right after every provider's `register()` phase, not after `boot()`, which only runs lazily on the app's first real request (or an explicit `app.boot()`). A route added in `boot()` still works for real traffic, just not for those introspection tools.

A plugin that needs something *another* provider bound — the host app's `Database`, a `Gate` — should defer that specific part to its own `boot()` instead, for the same reason every built-in provider does: `register()` runs for every provider (the host app's and every plugin's) before any provider's `boot()` runs, so a plugin can rely on another provider's binding existing by `boot()` regardless of registration order. See [Architecture](https://zeython.zaber.dev/docs/architecture/index.md).

A plugin package can declare more than one entry point in the group (e.g. one provider that adds routes, another that adds a CLI command) — every entry point under `zeython.plugins` across every installed package is discovered and registered.

## Failure is loud, not silent

A plugin whose provider fails to import, or whose `register()`/`boot()` raises, is not caught and skipped — it fails the app's boot the same way a broken `app.register(...)` line in `main.py` would. A plugin silently vanishing because of a typo in its own entry-point path, or a bug in its `register()`, would be a much worse failure mode than a loud stack trace at startup.

## Inspecting what's discovered

```python
from zeython import discover_plugins

for plugin in discover_plugins():
    print(plugin)
```

`discover_plugins()` is the plain function `PluginServiceProvider` calls internally — useful on its own for a `zeython about`-style diagnostic, or in a test asserting a particular plugin is (or isn't) installed. See [CLI Reference](https://zeython.zaber.dev/docs/cli/#project-introspection).

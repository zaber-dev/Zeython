"""Plugin discovery: letting a pip-installed third-party package register
its own service provider(s) with a Zeython app, without the app author
having to add an ``app.register(...)`` line for every package.

Every other extension point in the framework is an explicit
:class:`~zeython.providers.ServiceProvider`, registered by one line in
``main.py`` -- nothing auto-wires itself in behind the app author's back
(see ``SecurityHeadersServiceProvider``, ``ErrorMonitoringServiceProvider``,
etc., all opt-in). Plugins follow the same rule at the app level: a plugin
package changes nothing until the app author registers
:class:`PluginServiceProvider` once. From then on, *which* packages
contribute providers is driven by what's ``pip install``ed, the same way
Laravel's package auto-discovery or Django's ``INSTALLED_APPS`` works --
one line turns on discovery, not one line per package.

A plugin package declares itself via a standard Python entry point in its
own ``pyproject.toml``::

    [project.entry-points."zeython.plugins"]
    my_plugin = "my_package.providers:MyPluginServiceProvider"

The value is an import path to a :class:`~zeython.providers.ServiceProvider`
subclass (or an instance), exactly what ``app.register(...)`` already
accepts directly.
"""

from __future__ import annotations

from importlib.metadata import entry_points

from zeython.providers import ServiceProvider

__all__ = ["discover_plugins", "PluginServiceProvider"]

_ENTRY_POINT_GROUP = "zeython.plugins"


def discover_plugins() -> list[type[ServiceProvider] | ServiceProvider]:
    """Load every provider registered under the ``zeython.plugins`` entry-point
    group by an installed package.

    A plugin that fails to import is left to raise -- a broken or
    misconfigured plugin should fail loudly at boot, not vanish silently
    from an app that's relying on it.
    """
    return [entry_point.load() for entry_point in entry_points(group=_ENTRY_POINT_GROUP)]


class PluginServiceProvider(ServiceProvider):
    """Registers every plugin found by :func:`discover_plugins`.

    Register this once, anywhere in ``main.py``. A plugin adding routes
    should do it in its own ``register()`` (like the built-in
    ``RouteServiceProvider``) -- route/model introspection (``zeython
    routes``/``about``, the MCP server's ``list_routes``) reflects the app
    right after every provider's ``register()`` phase, not after ``boot()``,
    which only runs lazily on the first real request. A plugin that needs
    another provider's binding already in place (``Gate``, ``Database``)
    should defer that specific part to its own ``boot()``, for the same
    reason every built-in provider does -- see docs/architecture.md. See
    docs/plugins.md.
    """

    def register(self) -> None:
        for plugin in discover_plugins():
            self.app.register(plugin)

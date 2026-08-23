"""Feature flags: name a capability, decide who gets it, check it from
anywhere. Static (`.env`-driven) toggles and deterministic percentage
rollouts -- no database or Redis required. Mirrors the boolean/rollout
building blocks of Laravel Pennant, without persisted per-user storage;
:meth:`FeatureManager.define` takes a custom resolver if you need a flag
backed by a real store (a table, a third-party flag service) instead.
"""

from __future__ import annotations

import hashlib
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.requests import Request

from zeython.config import Config
from zeython.providers import ServiceProvider

logger = logging.getLogger("zeython.feature_flags")

Resolver = Callable[[Any], "bool | Awaitable[bool]"]


class FeatureManager:
    """Holds every defined feature flag and resolves them per-context.

    Bound in the container by :class:`FeatureServiceProvider` -- define
    flags in your own subclass of it (the same pattern
    :class:`~zeython.events.EventServiceProvider` uses)::

        class AppFeatureServiceProvider(FeatureServiceProvider):
            def boot(self) -> None:
                super().boot()
                manager = self.container.make(FeatureManager)
                manager.boolean("new_checkout")
                manager.percentage("beta_dashboard", rollout=10)
    """

    def __init__(self, *, config: Config | None = None) -> None:
        self._config = config
        self._resolvers: dict[str, Resolver] = {}

    def define(self, name: str, resolver: Resolver) -> None:
        """Register a flag with a custom resolver. ``resolver(context)``
        returns (or awaits to) a bool -- ``context`` is whatever the
        caller of :meth:`active`/:func:`feature` passed, typically the
        current user, ``None`` for a flag that doesn't vary per-request."""
        self._resolvers[name] = resolver

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

    def names(self) -> list[str]:
        """Every flag name currently defined, for introspection (`zeython features`)."""
        return sorted(self._resolvers)

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


class FeatureServiceProvider(ServiceProvider):
    """Binds a :class:`FeatureManager` into the container.

    Register no flags on its own -- subclass it and override ``boot()``
    (calling ``super().boot()`` first, so the manager exists) to define
    your own, the same pattern :class:`~zeython.events.EventServiceProvider`
    uses. See docs/feature-flags.md.
    """

    def register(self) -> None:
        manager = FeatureManager(config=self.config)
        self.container.singleton(FeatureManager, lambda: manager)


__all__ = ["FeatureManager", "FeatureServiceProvider", "feature"]

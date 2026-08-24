"""A minimal, type-hint-driven dependency injection container.

Zeython's :class:`Container` resolves dependencies by inspecting constructor
and function type annotations, in the spirit of Laravel's service container.
Bindings can be a plain instance, a factory callable, or a class to
autowire directly.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

Abstract = type[Any] | str
Factory = Callable[..., Any]


class BindingResolutionError(Exception):
    """Raised when the container cannot resolve a requested binding."""


class _Binding:
    __slots__ = ("factory", "shared")

    def __init__(self, factory: Factory, shared: bool) -> None:
        self.factory = factory
        self.shared = shared


class Container:
    """A small service container supporting binding, singletons, and autowiring.

    Fully synchronous by design (bindings resolve at boot, well before an
    event loop is necessarily running) -- an async factory is rejected
    with a clear error rather than silently returning an unawaited,
    never-usable coroutine that a shared/singleton binding would then
    cache and hand out forever. A circular dependency (``A`` needing
    ``B`` needing ``A``) is likewise rejected with a clear error instead
    of recursing until Python's own ``RecursionError``.
    """

    def __init__(self) -> None:
        self._bindings: dict[Abstract, _Binding] = {}
        self._instances: dict[Abstract, Any] = {}
        self._resolving: list[Abstract] = []

    def bind(self, abstract: Abstract, factory: Factory | None = None, *, shared: bool = False) -> None:
        """Register a binding. If ``factory`` is omitted, ``abstract`` must be a concrete class."""
        resolved_factory = factory or abstract
        if not callable(resolved_factory):
            raise TypeError(f"Binding for {abstract!r} must provide a callable factory")
        self._bindings[abstract] = _Binding(resolved_factory, shared)
        self._instances.pop(abstract, None)

    def singleton(self, abstract: Abstract, factory: Factory | None = None) -> None:
        """Register a binding that is instantiated once and reused."""
        self.bind(abstract, factory, shared=True)

    def instance(self, abstract: Abstract, value: Any) -> Any:
        """Register an already-constructed instance under ``abstract``."""
        self._instances[abstract] = value
        return value

    def has(self, abstract: Abstract) -> bool:
        return abstract in self._instances or abstract in self._bindings

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

    def flush(self) -> None:
        """Remove all bindings and cached instances."""
        self._bindings.clear()
        self._instances.clear()


def _is_builtin_scalar(annotation: type) -> bool:
    return annotation in (str, int, float, bool, bytes, type(None))

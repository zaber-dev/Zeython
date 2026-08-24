from __future__ import annotations

import pytest

from zeython.container import BindingResolutionError, Container

# Deliberately kept: this file uses postponed annotations (PEP 563), same
# as every zeython source module, precisely so every autowiring test below
# also exercises Container.call() with *string* annotations at runtime --
# not just the classes' real types -- since that's the regression this file
# guards.


class Engine:
    def __init__(self) -> None:
        self.started = False


class Car:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine


def test_autowires_constructor_dependencies() -> None:
    container = Container()
    car = container.make(Car)

    assert isinstance(car.engine, Engine)


def test_singleton_returns_the_same_instance() -> None:
    container = Container()
    container.singleton(Engine)

    first = container.make(Engine)
    second = container.make(Engine)

    assert first is second


def test_bind_without_shared_creates_new_instances() -> None:
    container = Container()
    container.bind(Engine)

    first = container.make(Engine)
    second = container.make(Engine)

    assert first is not second


def test_instance_registers_an_existing_object() -> None:
    container = Container()
    engine = Engine()
    container.instance(Engine, engine)

    assert container.make(Engine) is engine


def test_call_resolves_missing_arguments_from_the_container() -> None:
    container = Container()
    container.singleton(Engine)

    def start(engine: Engine, times: int = 1) -> int:
        engine.started = True
        return times

    result = container.call(start)

    assert result == 1
    assert container.make(Engine).started is True


def test_call_prefers_explicit_overrides() -> None:
    container = Container()

    def greet(name: str) -> str:
        return f"hello {name}"

    assert container.call(greet, name="world") == "hello world"


def test_unresolvable_scalar_parameter_raises() -> None:
    container = Container()

    def needs_name(name: str) -> str:
        return name

    with pytest.raises(BindingResolutionError):
        container.call(needs_name)


def test_a_dependency_with_a_default_is_still_autowired_from_a_binding() -> None:
    # Regression guard: under postponed annotations (this file's own
    # `from __future__ import annotations`), a parameter annotated with a
    # bindable class but given a default value (so it's not *required*)
    # used to be silently skipped rather than autowired -- Container.call()
    # read the annotation as the literal string "Engine", inspect.isclass()
    # on a str is False, so it fell straight through to "has a default,
    # leave it alone" instead of ever attempting to resolve the binding.
    container = Container()
    bound_engine = Engine()
    container.instance(Engine, bound_engine)

    def start(engine: Engine = None) -> Engine:  # type: ignore[assignment]
        return engine

    assert container.call(start) is bound_engine


def test_a_required_dependency_still_resolves_by_its_real_bound_type() -> None:
    # Same bug, the required-parameter side: previously raised a
    # misleading "no binding registered for 'Engine'" even when Engine
    # *was* bound -- just under the class object, not the string "Engine".
    container = Container()
    container.singleton(Engine)

    car = container.make(Car)

    assert isinstance(car.engine, Engine)
    assert car.engine is container.make(Engine)

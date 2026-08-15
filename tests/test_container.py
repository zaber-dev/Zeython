import pytest

from zeython.container import BindingResolutionError, Container


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

from pathlib import Path

from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.container import Container
from zeython.events import EventDispatcher, EventServiceProvider, emit
from zeython.testing import client

# -- EventDispatcher, direct (no container) ------------------------------------------


class OrderPlaced:
    def __init__(self, order_id: int) -> None:
        self.order_id = order_id


class OtherEvent:
    pass


async def test_listener_receives_the_dispatched_event() -> None:
    dispatcher = EventDispatcher()
    received: list[OrderPlaced] = []

    dispatcher.listen(OrderPlaced, lambda event: received.append(event))
    await dispatcher.dispatch(OrderPlaced(order_id=1))

    assert len(received) == 1
    assert received[0].order_id == 1


async def test_multiple_listeners_for_the_same_event_all_run() -> None:
    dispatcher = EventDispatcher()
    calls: list[str] = []

    dispatcher.listen(OrderPlaced, lambda event: calls.append("first"))
    dispatcher.listen(OrderPlaced, lambda event: calls.append("second"))
    await dispatcher.dispatch(OrderPlaced(order_id=1))

    assert calls == ["first", "second"]


async def test_listener_for_a_different_event_type_is_not_called() -> None:
    dispatcher = EventDispatcher()
    calls: list[str] = []

    dispatcher.listen(OtherEvent, lambda event: calls.append("wrong"))
    await dispatcher.dispatch(OrderPlaced(order_id=1))

    assert calls == []


async def test_async_listeners_are_awaited() -> None:
    dispatcher = EventDispatcher()
    calls: list[int] = []

    async def handler(event: OrderPlaced) -> None:
        calls.append(event.order_id)

    dispatcher.listen(OrderPlaced, handler)
    await dispatcher.dispatch(OrderPlaced(order_id=42))

    assert calls == [42]


async def test_sync_listeners_are_supported_too() -> None:
    dispatcher = EventDispatcher()
    calls: list[int] = []

    def handler(event: OrderPlaced) -> None:
        calls.append(event.order_id)

    dispatcher.listen(OrderPlaced, handler)
    await dispatcher.dispatch(OrderPlaced(order_id=7))

    assert calls == [7]


async def test_on_decorator_registers_a_listener() -> None:
    dispatcher = EventDispatcher()
    calls: list[int] = []

    @dispatcher.on(OrderPlaced)
    async def handler(event: OrderPlaced) -> None:
        calls.append(event.order_id)

    await dispatcher.dispatch(OrderPlaced(order_id=9))

    assert calls == [9]


async def test_listeners_for_reports_registered_listeners() -> None:
    dispatcher = EventDispatcher()

    def handler(event: OrderPlaced) -> None: ...

    assert dispatcher.listeners_for(OrderPlaced) == []
    dispatcher.listen(OrderPlaced, handler)
    assert dispatcher.listeners_for(OrderPlaced) == [handler]


async def test_a_failing_listener_does_not_stop_other_listeners() -> None:
    dispatcher = EventDispatcher()
    calls: list[str] = []

    def broken(event: OrderPlaced) -> None:
        raise RuntimeError("boom")

    dispatcher.listen(OrderPlaced, broken)
    dispatcher.listen(OrderPlaced, lambda event: calls.append("still ran"))

    await dispatcher.dispatch(OrderPlaced(order_id=1))  # must not raise

    assert calls == ["still ran"]


# -- EventDispatcher, with a container (dependency-injected listener params) --------


class _Mailer:
    def __init__(self) -> None:
        self.sent: list[int] = []


async def test_listener_dependencies_are_resolved_via_the_container() -> None:
    container = Container()
    mailer = _Mailer()
    container.instance(_Mailer, mailer)
    dispatcher = EventDispatcher(container=container)

    async def send_receipt(event: OrderPlaced, mailer: _Mailer) -> None:
        mailer.sent.append(event.order_id)

    dispatcher.listen(OrderPlaced, send_receipt)
    await dispatcher.dispatch(OrderPlaced(order_id=5))

    assert mailer.sent == [5]


# -- EventServiceProvider / emit() -----------------------------------------------


def _make_app(tmp_path: Path) -> Application:
    app = Application(Config.load(tmp_path))
    app.register(EventServiceProvider)
    return app


async def test_event_service_provider_binds_a_dispatcher_in_the_container(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    assert isinstance(app.container.make(EventDispatcher), EventDispatcher)


async def test_emit_dispatches_through_the_bound_dispatcher(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    calls: list[int] = []
    app.container.make(EventDispatcher).listen(OrderPlaced, lambda event: calls.append(event.order_id))

    @app.post("/orders")
    async def create_order(request):
        await emit(request, OrderPlaced(order_id=100))
        return JSONResponse({"ok": True}, status_code=201)

    async with client(app) as http:
        response = await http.post("/orders")

    assert response.status_code == 201
    assert calls == [100]

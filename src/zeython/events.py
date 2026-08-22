"""Application-level events: decoupled listeners reacting to a domain event
(``OrderPlaced``, ``UserRegistered``, ...) without the code that raises it
needing to know who's listening.

Deliberately separate from :class:`zeython.db.Observer` -- an Observer
reacts to one model's own lifecycle (``creating``, ``updated``, ...); an
event here can be anything your application defines, dispatched from
anywhere (a controller, a job, a scheduled task), with any number of
independent listeners reacting to it without editing the code that
dispatches it. A common pattern is dispatching an event *from* a model
hook (``created()``) once the write itself is the model's own concern but
what happens next (send a receipt, notify a webhook, update a search
index) isn't.
"""

from __future__ import annotations

import inspect
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any, TypeVar

from starlette.requests import Request

from zeython.container import Container
from zeython.error_monitoring import report_exception
from zeython.providers import ServiceProvider

logger = logging.getLogger(__name__)

E = TypeVar("E")
#: A listener's first parameter receives the dispatched event; any other
#: parameters are resolved from the container the same way Job.handle()'s
#: are. May be a plain function or a coroutine function.
Listener = Callable[..., Any]


class EventDispatcher:
    """Maps an event type to the listeners registered for it."""

    def __init__(self, *, container: Container | None = None) -> None:
        self._listeners: dict[type, list[Listener]] = defaultdict(list)
        self._container = container

    def listen(self, event_type: type[E], listener: Listener) -> None:
        """Register ``listener`` to run whenever an instance of ``event_type`` is dispatched."""
        self._listeners[event_type].append(listener)

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

    def listeners_for(self, event_type: type) -> list[Listener]:
        """The listeners currently registered for ``event_type``, in registration order."""
        return list(self._listeners.get(event_type, ()))

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

    async def _invoke(self, listener: Listener, event: object) -> None:
        parameters = list(inspect.signature(listener).parameters)
        overrides = {parameters[0]: event} if parameters else {}
        result = self._container.call(listener, **overrides) if self._container is not None else listener(event)
        if inspect.isawaitable(result):
            await result


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


class EventServiceProvider(ServiceProvider):
    """Binds an :class:`EventDispatcher` into the container.

    Register your own listeners by subclassing and overriding ``boot()``
    (calling ``super().boot()`` first, so the dispatcher exists) --
    registration happens once, at startup, the same way route modules and
    other providers wire themselves up::

        class AppEventServiceProvider(EventServiceProvider):
            def boot(self) -> None:
                super().boot()
                dispatcher = self.container.make(EventDispatcher)
                dispatcher.listen(OrderPlaced, send_receipt_email)
                dispatcher.listen(OrderPlaced, notify_fulfillment_webhook)
    """

    def register(self) -> None:
        dispatcher = EventDispatcher(container=self.container)
        self.container.singleton(EventDispatcher, lambda: dispatcher)


__all__ = ["EventDispatcher", "emit", "EventServiceProvider"]

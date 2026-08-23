"""Multi-channel notifications: one :class:`Notification` subclass
describes what happened and which channels (``mail``, ``database``,
``broadcast``) should carry it; :func:`notify` fires all of them.
Mirrors Laravel's Notification system.

Deliberately separate from :mod:`zeython.events` -- an event is "this
happened, react however you like" (any number of independent listeners,
no fixed shape); a notification is "tell *this one recipient*, on
*these* channels, in *this* format" -- one `Notification` instance
describes its own rendering per channel rather than leaving each
listener to reinvent it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from starlette.requests import Request

from zeython.container import Container
from zeython.db import Model
from zeython.error_monitoring import report_exception
from zeython.mail import Mailer, Message
from zeython.providers import ServiceProvider

logger = logging.getLogger("zeython.notifications")

DEFAULT_CHANNELS = ("database",)


class Notification:
    """Base class for a notification.

    Override :meth:`via` to pick channels for a given recipient, and
    whichever ``to_*`` builder each of those channels actually needs::

        class InvoicePaid(Notification):
            def __init__(self, invoice: Invoice) -> None:
                self.invoice = invoice

            def via(self, notifiable: Any) -> list[str]:
                return ["mail", "database"]

            def to_mail(self, notifiable: Any) -> Message:
                return Message(
                    to=notifiable.email,
                    subject="Invoice paid",
                    body=f"Thanks! We received ${self.invoice.amount}.",
                )

            def to_database(self, notifiable: Any) -> dict:
                return {"invoice_id": self.invoice.id, "amount": self.invoice.amount}
    """

    def via(self, notifiable: Any) -> list[str]:
        return list(DEFAULT_CHANNELS)

    def to_mail(self, notifiable: Any) -> Message:
        raise NotImplementedError(f"{type(self).__name__} doesn't define to_mail()")

    def to_database(self, notifiable: Any) -> dict[str, Any]:
        raise NotImplementedError(f"{type(self).__name__} doesn't define to_database()")

    def to_broadcast(self, notifiable: Any) -> dict[str, Any]:
        # A sane default: reuse the database payload rather than forcing
        # every notification that wants both channels to write it twice.
        return self.to_database(notifiable)


class NotificationManager:
    """Fires a :class:`Notification` at a recipient across whichever
    channels it asks for. Bound in the container by
    :class:`NotificationServiceProvider` -- use :func:`notify` from a
    request handler, or resolve this directly outside of one (a job, a
    scheduled task).
    """

    def __init__(self, container: Container, *, record_model: type[Model] | None = None) -> None:
        self._container = container
        self.record_model = record_model

    async def notify(self, notifiable: Any, notification: Notification) -> None:
        """Send ``notification`` to ``notifiable`` on every channel
        :meth:`Notification.via` names.

        A channel's own failure is logged and reported (see
        :mod:`zeython.error_monitoring`), not raised -- the same reasoning
        :class:`~zeython.events.EventDispatcher` uses for listeners: a
        down SMTP server shouldn't also silently swallow the in-app
        notification that would have told the user something happened.
        """
        for channel in notification.via(notifiable):
            try:
                await self._send(channel, notifiable, notification)
            except Exception as exc:
                report_exception(
                    exc, channel=channel, notification=type(notification).__name__
                )
                logger.exception(
                    "Notification channel %r failed for %s", channel, type(notification).__name__
                )

    async def _send(self, channel: str, notifiable: Any, notification: Notification) -> None:
        if channel == "mail":
            mailer = self._container.make(Mailer)
            await mailer.send(notification.to_mail(notifiable))
        elif channel == "database":
            if self.record_model is None:
                raise RuntimeError(
                    "The 'database' notification channel requires "
                    "NotificationServiceProvider(app, record_model=...) -- "
                    "see docs/notifications.md."
                )
            await self.record_model.create(
                notifiable_id=notifiable.id,
                type=type(notification).__name__,
                data=notification.to_database(notifiable),
            )
        elif channel == "broadcast":
            from zeython.websockets import WebSocketHub

            if not self._container.has(WebSocketHub):
                raise RuntimeError(
                    "The 'broadcast' notification channel requires "
                    "WebSocketHubServiceProvider to be registered."
                )
            hub = self._container.make(WebSocketHub)
            await hub.broadcast(
                {
                    "type": type(notification).__name__,
                    "notifiable_id": getattr(notifiable, "id", None),
                    "data": notification.to_broadcast(notifiable),
                }
            )
        else:
            logger.warning(
                "Unknown notification channel %r on %s -- via() must return one of "
                "'mail', 'database', 'broadcast'.",
                channel,
                type(notification).__name__,
            )


async def notify(request: Request, notifiable: Any, notification: Notification) -> None:
    """Send ``notification`` to ``notifiable`` using whichever
    :class:`NotificationManager` is bound in the container (see
    :class:`NotificationServiceProvider`). Outside of a request -- a job,
    a scheduled task -- resolve directly instead::

        manager = app.container.make(NotificationManager)
        await manager.notify(user, WelcomeNotification())
    """
    manager: NotificationManager = request.app.state.container.make(NotificationManager)
    await manager.notify(notifiable, notification)


async def unread_notifications(notifiable: Any, record_model: type[Model]) -> list[Model]:
    """Every ``record_model`` row for ``notifiable`` not yet marked read,
    newest first -- the framework doesn't force a mixin onto your
    notifiable model to get this, just pass the same ``record_model`` you
    registered with :class:`NotificationServiceProvider`."""
    rows = await record_model.find_by(notifiable_id=notifiable.id, read_at=None)
    return sorted(rows, key=lambda row: row.created_at, reverse=True)


async def mark_as_read(notification: Model) -> Model:
    """Stamp ``notification.read_at`` with the current time and save it."""
    return await notification.update(read_at=datetime.now(UTC))


class NotificationServiceProvider(ServiceProvider):
    """Binds a :class:`NotificationManager` into the container.

        app.register(NotificationServiceProvider(app, record_model=Notification))

    ``record_model`` is your own ``Model`` subclass for the ``database``
    channel (columns: ``notifiable_id``, ``type``, ``data``, ``read_at``)
    -- generated by `zeython make notification` alongside a
    ``Notification`` example class, wired into a fresh project's
    ``app/Models/notification.py`` by default. Omit it if you only ever
    use the ``mail``/``broadcast`` channels; calling the ``database``
    channel without one raises immediately, naming the fix.
    """

    def __init__(self, app: Any, *, record_model: type[Model] | None = None) -> None:
        super().__init__(app)
        self.record_model = record_model

    def register(self) -> None:
        manager = NotificationManager(self.container, record_model=self.record_model)
        self.container.singleton(NotificationManager, lambda: manager)


__all__ = [
    "Notification",
    "NotificationManager",
    "NotificationServiceProvider",
    "mark_as_read",
    "notify",
    "unread_notifications",
]

"""Outbound email: a small ``Mailer`` interface, a log-only default so
`zeython new` works with zero mail configuration, and an SMTP backend for
when you actually have credentials.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.message import EmailMessage

from zeython.providers import ServiceProvider

logger = logging.getLogger("zeython.mail")


@dataclass
class Message:
    """An email to send. ``to`` accepts a single address or a list."""

    to: str | list[str]
    subject: str
    body: str
    html: str | None = None
    from_address: str | None = None

    def recipients(self) -> list[str]:
        return [self.to] if isinstance(self.to, str) else list(self.to)


class Mailer(ABC):
    @abstractmethod
    async def send(self, message: Message) -> None: ...


class LogMailer(Mailer):
    """Writes the email to your app's logs instead of sending it.

    The default (``MAIL_DRIVER=log``), so a fresh ``zeython new`` project
    can dispatch mail-sending jobs immediately without SMTP credentials.
    Switch to :class:`SmtpMailer` (``MAIL_DRIVER=smtp``) once you have real
    ones. See docs/mail.md.
    """

    async def send(self, message: Message) -> None:
        logger.info(
            "Email (not sent -- MAIL_DRIVER=log): to=%s subject=%r\n%s",
            ", ".join(message.recipients()),
            message.subject,
            message.body,
        )


class SmtpMailer(Mailer):
    """Sends real email over SMTP, via the stdlib (no third-party dependency).

    ``smtplib`` is blocking, so :meth:`send` runs it on a worker thread
    (``asyncio.to_thread``) rather than blocking the event loop.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        use_tls: bool,
        default_from: str,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.default_from = default_from

    async def send(self, message: Message) -> None:
        await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: Message) -> None:
        email = EmailMessage()
        email["Subject"] = message.subject
        email["From"] = message.from_address or self.default_from
        email["To"] = ", ".join(message.recipients())
        email.set_content(message.body)
        if message.html:
            email.add_alternative(message.html, subtype="html")

        with smtplib.SMTP(self.host, self.port) as client:
            if self.use_tls:
                client.starttls()
            if self.username and self.password:
                client.login(self.username, self.password)
            client.send_message(email)


class MailServiceProvider(ServiceProvider):
    """Binds a :class:`Mailer` into the container from ``.env``.

    - ``MAIL_DRIVER`` — ``log`` (default) or ``smtp``
    - ``MAIL_HOST``, ``MAIL_PORT`` (default ``587``)
    - ``MAIL_USERNAME``, ``MAIL_PASSWORD``
    - ``MAIL_ENCRYPTION`` — ``tls`` (default) or ``none``
    - ``MAIL_FROM_ADDRESS`` (default ``no-reply@example.com``)
    """

    def register(self) -> None:
        driver = self.config.get("mail.driver", "log")
        mailer: Mailer
        if driver == "smtp":
            mailer = SmtpMailer(
                host=self.config.get("mail.host", "localhost"),
                port=int(self.config.get("mail.port", 587)),
                username=self.config.get("mail.username"),
                password=self.config.get("mail.password"),
                use_tls=str(self.config.get("mail.encryption", "tls")).lower() == "tls",
                default_from=self.config.get("mail.from_address", "no-reply@example.com"),
            )
        else:
            mailer = LogMailer()
        self.container.singleton(Mailer, lambda: mailer)


__all__ = ["Message", "Mailer", "LogMailer", "SmtpMailer", "MailServiceProvider"]

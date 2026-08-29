from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from zeython import Model


class WebhookEndpoint(Model):
    """A third party's subscription to one event -- see docs/webhooks.md.
    Passed to WebhookServiceProvider in main.py. One row per (url, event)
    pair, so a single receiving URL that wants several event types just
    gets several rows.

    There's no admin UI or API for creating these yet -- add one via
    `zeython tinker` or a seeder:

        await WebhookEndpoint.create(
            url="https://example.com/hooks/zeython",
            event="user.registered",
            secret=secrets.token_hex(32),
            active=True,
        )
    """

    __tablename__ = "webhook_endpoints"

    url: Mapped[str] = mapped_column(String(2048))
    event: Mapped[str] = mapped_column(String(255), index=True)
    secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

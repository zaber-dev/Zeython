from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from zeython import Model


class WebhookDelivery(Model):
    """One delivery *attempt* to a `WebhookEndpoint` -- see docs/webhooks.md.
    Passed to WebhookServiceProvider in main.py. Every retry gets its own
    row, so this doubles as an audit trail of what was sent and whether it
    arrived, the same thing Stripe/GitHub show in their own webhook
    dashboards. Optional -- omit `delivery_model` in main.py if you don't
    need one."""

    __tablename__ = "webhook_deliveries"

    endpoint_id: Mapped[int] = mapped_column(Integer, ForeignKey("webhook_endpoints.id"), index=True)
    event: Mapped[str] = mapped_column(String(255))
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)

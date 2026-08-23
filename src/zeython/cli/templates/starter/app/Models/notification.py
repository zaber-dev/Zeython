from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from zeython import Model


class Notification(Model):
    """Record model for the ``database`` notification channel -- see
    docs/notifications.md. Passed to NotificationServiceProvider in
    main.py; not the notification classes themselves (app/Notifications/)."""

    __tablename__ = "notifications"

    notifiable_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(255))
    data: Mapped[dict] = mapped_column(JSON)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from zeython import Model


class AuditLog(Model):
    """Record model for zeython.audit_log -- see docs/audit-log.md. Passed
    to AuditObserver wherever a model opts into auditing
    (app/Providers/app_audit_service_provider.py), not the audited models
    themselves."""

    __tablename__ = "audit_logs"

    auditable_type: Mapped[str] = mapped_column(String(255), index=True)
    auditable_id: Mapped[int] = mapped_column(Integer, index=True)
    event: Mapped[str] = mapped_column(String(50))
    changes: Mapped[dict] = mapped_column(JSON)
    actor_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

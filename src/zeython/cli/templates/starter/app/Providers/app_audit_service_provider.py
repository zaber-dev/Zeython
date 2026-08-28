from zeython import AuditObserver, ServiceProvider

from app.Models.audit_log import AuditLog
from app.Models.post import Post


class AppAuditServiceProvider(ServiceProvider):
    """Registers this app's audit logging -- see docs/audit-log.md.

    One ``AuditObserver`` per audited model, each pointed at the same
    ``AuditLog`` record model -- add another ``SomeModel.observe(...)``
    call here for any other model you want tracked. Never attach one to
    ``AuditLog`` itself (see ``AuditObserver``'s own docstring for why).
    """

    def boot(self) -> None:
        Post.observe(AuditObserver(AuditLog))

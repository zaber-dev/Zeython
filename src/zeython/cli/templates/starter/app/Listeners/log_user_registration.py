import logging

from app.Events.user_registered import UserRegistered

logger = logging.getLogger(__name__)


async def log_user_registration(event: UserRegistered) -> None:
    """A second, independent reaction to a new signup, alongside the welcome
    email `AuthController.register` already dispatches as a queued job --
    this one doesn't touch AuthController at all (see docs/events.md).
    Swap in a real audit-log write, an analytics call, or a CRM sync.
    """
    logger.info("user registered: id=%s email=%s", event.user_id, event.email)

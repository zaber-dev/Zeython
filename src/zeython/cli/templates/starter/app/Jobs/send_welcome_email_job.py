import logging
from dataclasses import dataclass

from zeython import Job

logger = logging.getLogger("app.jobs.send_welcome_email")


@dataclass
class SendWelcomeEmailJob(Job):
    """Stands in for real email delivery -- swap the body of handle() for
    your actual mail provider. See docs/queues.md.
    """

    to_email: str
    name: str

    async def handle(self) -> None:
        logger.info("(pretend) sending welcome email to %s <%s>", self.name, self.to_email)

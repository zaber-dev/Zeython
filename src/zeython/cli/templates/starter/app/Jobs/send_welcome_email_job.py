from dataclasses import dataclass

from zeython import Job, Mailer, Message


@dataclass
class SendWelcomeEmailJob(Job):
    """Dispatched from AuthController.register (see docs/queues.md).

    `mailer` is resolved automatically from the container when the queue
    worker runs this job's handle() -- see docs/mail.md. MAIL_DRIVER=log
    (the default) just logs the email instead of sending it, so this works
    with zero mail configuration until you set real SMTP credentials.
    """

    to_email: str
    name: str

    async def handle(self, mailer: Mailer) -> None:
        await mailer.send(
            Message(
                to=self.to_email,
                subject="Welcome!",
                body=f"Hi {self.name}, welcome aboard.",
            )
        )

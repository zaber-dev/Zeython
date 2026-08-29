from zeython.webhooks import WebhookManager

from app.Events.user_registered import UserRegistered


async def notify_webhooks_of_registration(event: UserRegistered, webhooks: WebhookManager) -> None:
    """Tell any subscribed third party a new user signed up -- see
    docs/webhooks.md. `webhooks` is autowired from the container the same
    way `Job.handle()`'s extra parameters are (see docs/queues.md);
    nothing to pass explicitly.
    """
    await webhooks.fire("user.registered", {"user_id": event.user_id, "email": event.email})

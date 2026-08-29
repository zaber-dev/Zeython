from zeython import EventDispatcher, EventServiceProvider

from app.Events.user_registered import UserRegistered
from app.Listeners.log_user_registration import log_user_registration
from app.Listeners.notify_webhooks_of_registration import notify_webhooks_of_registration


class AppEventServiceProvider(EventServiceProvider):
    """Registers this app's event listeners (see docs/events.md).

    ``super().boot()`` first -- it's what actually binds the
    `EventDispatcher` this then resolves and adds listeners to.
    """

    def boot(self) -> None:
        super().boot()
        dispatcher = self.container.make(EventDispatcher)
        dispatcher.listen(UserRegistered, log_user_registration)
        dispatcher.listen(UserRegistered, notify_webhooks_of_registration)

from typing import Any

from zeython import Notification


class WelcomeNotification(Notification):
    """An in-app record that a new user signed up -- see docs/notifications.md.

    Separate from SendWelcomeEmailJob (app/Jobs/), which sends the actual
    welcome *email* -- this is what a "you have notifications" UI would
    read from, via unread_notifications(user, Notification)."""

    def via(self, notifiable: Any) -> list[str]:
        return ["database"]

    def to_database(self, notifiable: Any) -> dict:
        return {"message": f"Welcome, {notifiable.name}!"}

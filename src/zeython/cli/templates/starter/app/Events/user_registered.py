from dataclasses import dataclass


@dataclass
class UserRegistered:
    """Dispatched from AuthController.register once the account exists (see
    docs/events.md). Carries just enough for a listener to act without
    re-querying the user it already has -- add fields as listeners need them.
    """

    user_id: int
    email: str

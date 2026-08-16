from zeython import Factory, hash_password

from app.Models.user import User


class UserFactory(Factory[User]):
    model = User

    def definition(self, sequence: int) -> dict:
        return {
            "name": f"User {sequence}",
            "email": f"user{sequence}@example.com",
            "password_hash": hash_password("password"),
        }

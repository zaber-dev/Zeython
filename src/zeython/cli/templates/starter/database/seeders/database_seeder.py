from zeython import Seeder

from database.factories.post_factory import PostFactory
from database.factories.user_factory import UserFactory


class DatabaseSeeder(Seeder):
    """Entry point for `zeython db seed`. Compose other seeders with `self.call(...)`."""

    async def run(self) -> None:
        users = await UserFactory().create_many(3)
        for user in users:
            await PostFactory().create_many(2, author_id=user.id)

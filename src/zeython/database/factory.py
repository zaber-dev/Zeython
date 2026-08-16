"""Model factories: generating realistic model instances for tests and seeding.

Every ORM-backed app eventually reinvents this -- a helper that builds a
``User`` with plausible-but-fake data, so a test doesn't need to spell out
every column by hand, and two factory-built rows don't collide on a unique
constraint. Laravel's ``UserFactory`` and ``factory_boy`` both solve the same
problem; this is Zeython's version, with no dependency of its own -- pull in
`Faker <https://faker.readthedocs.io/>`_ yourself inside ``definition()`` if
you want realistic names/addresses/etc., or keep it simple with an f-string
built from the sequence number.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Generic, TypeVar

from zeython.db import Model

ModelT = TypeVar("ModelT", bound=Model)


class Factory(ABC, Generic[ModelT]):
    """Base class for a model factory. One subclass per model.

    ::

        class UserFactory(Factory[User]):
            model = User

            def definition(self, sequence: int) -> dict:
                return {
                    "name": f"User {sequence}",
                    "email": f"user{sequence}@example.com",
                    "password_hash": hash_password("password"),
                }

        user = await UserFactory().create()
        users = await UserFactory().create_many(5)
        unsaved = UserFactory().make(name="Override")  # not persisted
    """

    #: The model this factory builds. Set on the subclass.
    model: ClassVar[type[Model]]

    def __init__(self) -> None:
        self._sequence = 0

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    @abstractmethod
    def definition(self, sequence: int) -> dict[str, Any]:
        """Default attributes for one instance.

        ``sequence`` starts at 1 and increments on every ``make()``/
        ``create()`` call on this factory instance -- use it to keep
        unique-constrained columns (an email, a slug) actually unique
        across a batch, without reaching for a random-data library.
        """

    def make(self, **overrides: Any) -> ModelT:
        """Build an instance in memory. Not persisted -- nothing touches the database."""
        data = {**self.definition(self._next_sequence()), **overrides}
        return self.model(**data)  # type: ignore[return-value]

    def make_many(self, count: int, **overrides: Any) -> list[ModelT]:
        return [self.make(**overrides) for _ in range(count)]

    async def create(self, **overrides: Any) -> ModelT:
        """Build an instance and save it, the same way ``Model.create()`` does.

        Requires an active database session (a request, or an explicit
        ``async with database.session():`` block) -- same requirement as
        every other persistence method in the framework.
        """
        data = {**self.definition(self._next_sequence()), **overrides}
        return await self.model.create(**data)  # type: ignore[return-value]

    async def create_many(self, count: int, **overrides: Any) -> list[ModelT]:
        return [await self.create(**overrides) for _ in range(count)]


__all__ = ["Factory"]

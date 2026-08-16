"""Active-Record style base model, async throughout."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar, Self

from sqlalchemy import Boolean, DateTime, Integer, inspect, select
from sqlalchemy.orm import Mapped, mapped_column

from zeython.db.session import Base, current_session
from zeython.exceptions import ValidationException
from zeython.validation import Rule


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Model(Base):
    """Base class for application models.

    Provides an Active-Record style async API (``create``, ``find``, ``all``,
    ``save``, ``delete``) plus soft deletes and audit timestamps out of the
    box. All methods operate on the session bound to the current request
    via :data:`zeython.db.session.current_session`.
    """

    __abstract__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Fields hidden from ``to_dict``/``to_json`` output, e.g. password hashes.
    __hidden__: ClassVar[tuple[str, ...]] = ()

    #: Declarative validation rules, e.g. ``{"email": [required(), email()]}``.
    #: Checked by ``save()`` (and therefore ``create()``/``update()``); a
    #: failing rule raises :class:`~zeython.exceptions.ValidationException`.
    __rules__: ClassVar[dict[str, list[Rule]]] = {}

    def validate(self) -> dict[str, list[str]]:
        """Run ``__rules__`` against the current field values. Does not raise."""
        errors: dict[str, list[str]] = {}
        for field, rules in self.__rules__.items():
            value = getattr(self, field, None)
            for rule in rules:
                if not rule(value):
                    errors.setdefault(field, []).append(rule.message)
        return errors

    def validate_or_raise(self) -> None:
        errors = self.validate()
        if errors:
            raise ValidationException(errors)

    @classmethod
    async def create(cls, **attributes: Any) -> Self:
        instance = cls(**attributes)
        return await instance.save()

    @classmethod
    async def find(cls, id_: Any, *, include_deleted: bool = False) -> Self | None:
        session = current_session()
        stmt = select(cls).where(cls.id == id_)
        if not include_deleted:
            stmt = stmt.where(cls.is_deleted.is_(False))
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @classmethod
    async def all(cls, *, include_deleted: bool = False) -> list[Self]:
        session = current_session()
        stmt = select(cls)
        if not include_deleted:
            stmt = stmt.where(cls.is_deleted.is_(False))
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @classmethod
    async def find_by(cls, *, include_deleted: bool = False, **filters: Any) -> list[Self]:
        session = current_session()
        stmt = select(cls)
        if not include_deleted:
            stmt = stmt.where(cls.is_deleted.is_(False))
        for field, value in filters.items():
            stmt = stmt.where(getattr(cls, field) == value)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @classmethod
    async def first_where(cls, *, include_deleted: bool = False, **filters: Any) -> Self | None:
        results = await cls.find_by(include_deleted=include_deleted, **filters)
        return results[0] if results else None

    async def save(self) -> Self:
        self.validate_or_raise()
        session = current_session()
        session.add(self)
        await session.flush()
        return self

    async def update(self, **attributes: Any) -> Self:
        for key, value in attributes.items():
            setattr(self, key, value)
        return await self.save()

    async def delete(self, *, soft: bool = True) -> None:
        session = current_session()
        if soft:
            self.is_deleted = True
            self.deleted_at = _utcnow()
            session.add(self)
            await session.flush()
        else:
            await session.delete(self)
            await session.flush()

    async def restore(self) -> Self:
        self.is_deleted = False
        self.deleted_at = None
        return await self.save()

    def to_dict(self, *, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
        hidden = set(self.__hidden__) | set(exclude)
        mapper = inspect(self.__class__)
        result: dict[str, Any] = {}
        for column in mapper.columns:
            if column.name in hidden:
                continue
            value = getattr(self, column.name)
            if isinstance(value, datetime):
                value = value.isoformat()
            result[column.name] = value
        return result

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id!r}>"

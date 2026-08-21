"""Active-Record style base model, async throughout."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Generic, Self, TypeVar

from sqlalchemy import Boolean, DateTime, Integer, func, inspect, select
from sqlalchemy.orm import Mapped, mapped_column, selectinload
from starlette.requests import Request

from zeython.db.session import Base, current_session
from zeython.exceptions import ValidationException
from zeython.validation import Rule
from zeython.validation import validate as validate_data


def _utcnow() -> datetime:
    return datetime.now(UTC)


T = TypeVar("T")


@dataclass(frozen=True)
class Page(Generic[T]):
    """One page of results from :meth:`Model.paginate`."""

    items: list[T]
    page: int
    per_page: int
    total: int

    @property
    def total_pages(self) -> int:
        if self.per_page <= 0:
            return 0
        return -(-self.total // self.per_page)  # ceil division

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    def to_dict(self, *, request: Request | None = None) -> dict[str, Any]:
        """Serialize this page: items (via ``.to_dict()`` for ``Model``
        instances, as-is otherwise) plus pagination metadata.

        Pass the current request to also get ``next_url``/``prev_url`` --
        the same URL with only the ``page`` query param changed (every
        other query param, e.g. ``per_page`` or a filter, carries over),
        ``None`` when there is no next/previous page.
        """
        items = [item.to_dict() if isinstance(item, Model) else item for item in self.items]
        result: dict[str, Any] = {
            "items": items,
            "page": self.page,
            "per_page": self.per_page,
            "total": self.total,
            "total_pages": self.total_pages,
            "has_next": self.has_next,
            "has_prev": self.has_prev,
        }
        if request is not None:
            result["next_url"] = (
                str(request.url.include_query_params(page=self.page + 1)) if self.has_next else None
            )
            result["prev_url"] = (
                str(request.url.include_query_params(page=self.page - 1)) if self.has_prev else None
            )
        return result


class Observer:
    """Base class for model observers -- mirrors Laravel's ``Model::observe()``.

    A model's own lifecycle hooks (``saving``/``saved``/...) live on the
    model itself, one implementation per class. An observer is a separate
    object registered against a model class with :meth:`Model.observe`,
    for cross-cutting concerns that don't belong on the model (search-index
    sync, cache invalidation, audit logging) and that several independent
    observers might want to react to. Override any subset of these hooks;
    the rest are no-ops. Called in the same order as the model's own hooks,
    immediately after each one.
    """

    async def saving(self, model: Model) -> None:
        """Runs before every save() -- both create and update."""

    async def saved(self, model: Model) -> None:
        """Runs after every successful save() -- both create and update."""

    async def creating(self, model: Model) -> None:
        """Runs before a new record's first save()."""

    async def created(self, model: Model) -> None:
        """Runs after a new record's first save()."""

    async def updating(self, model: Model) -> None:
        """Runs before saving changes to an existing record."""

    async def updated(self, model: Model) -> None:
        """Runs after saving changes to an existing record."""

    async def deleting(self, model: Model) -> None:
        """Runs before delete() -- soft or hard."""

    async def deleted(self, model: Model) -> None:
        """Runs after delete() -- soft or hard."""


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

    #: Observers registered via :meth:`observe`. Re-initialized to a fresh,
    #: empty list for every subclass by ``__init_subclass__`` below -- never
    #: mutate this default directly, it isn't per-class on its own.
    __observers__: ClassVar[list[Observer]] = []

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.__observers__ = []

    @classmethod
    def observe(cls, observer: type[Observer] | Observer) -> None:
        """Register an observer for this model class -- a class (instantiated
        with no arguments) or an already-constructed instance. Typically
        called once, e.g. in a service provider's ``boot()``.
        """
        instance = observer() if isinstance(observer, type) else observer
        cls.__observers__.append(instance)

    async def _notify(self, event: str) -> None:
        for observer in type(self).__observers__:
            await getattr(observer, event)(self)

    def validate(self) -> dict[str, list[str]]:
        """Run ``__rules__`` against the current field values. Does not raise.

        A thin wrapper over :func:`zeython.validation.validate` applied to
        this instance's own field values -- use that function directly to
        run the same rule sets against a plain dict (a request payload, not
        yet a model instance).
        """
        data = {field: getattr(self, field, None) for field in self.__rules__}
        return validate_data(data, self.__rules__)

    def validate_or_raise(self) -> None:
        errors = self.validate()
        if errors:
            raise ValidationException(errors)

    # -- Lifecycle hooks ---------------------------------------------------------
    #
    # No-op by default; override in a subclass to hook into save()/delete().
    # save() calls, in order: saving() -> creating() or updating() -> (write
    # to the database) -> created() or updated() -> saved(). The
    # creating()/updating() hooks run *before* validate_or_raise(), so they're
    # the right place to derive/default a field (e.g. normalizing an email)
    # that validation then checks -- not just to react after the fact.

    async def saving(self) -> None:
        """Runs before every save() -- both create and update."""

    async def saved(self) -> None:
        """Runs after every successful save() -- both create and update."""

    async def creating(self) -> None:
        """Runs before a new record's first save()."""

    async def created(self) -> None:
        """Runs after a new record's first save()."""

    async def updating(self) -> None:
        """Runs before saving changes to an existing record."""

    async def updated(self) -> None:
        """Runs after saving changes to an existing record."""

    async def deleting(self) -> None:
        """Runs before delete() -- soft or hard."""

    async def deleted(self) -> None:
        """Runs after delete() -- soft or hard."""

    @classmethod
    async def create(cls, **attributes: Any) -> Self:
        instance = cls(**attributes)
        return await instance.save()

    @classmethod
    def _with_includes(cls, stmt: Any, include: Iterable[str]) -> Any:
        """Apply ``selectinload()`` for each relationship name in ``include``.

        This is what makes touching a relationship afterward safe: without
        it, accessing an unloaded relationship on an async session raises
        ``MissingGreenlet`` rather than lazily fetching it the way a sync
        session would. See docs/relationships.md.
        """
        for name in include:
            stmt = stmt.options(selectinload(getattr(cls, name)))
        return stmt

    @classmethod
    def _base_select(cls) -> Any:
        """The starting ``select(cls)`` every query method below builds on.

        A model that declares a ``tenant_id`` column (see
        :mod:`zeython.tenancy`) gets every read -- ``find``, ``all``,
        ``find_by``, ``paginate`` -- scoped to
        :func:`~zeython.tenancy.current_tenant_id` automatically, with no
        mixin or per-query opt-in needed. A model with no such column is
        completely unaffected -- this is a plain ``select(cls)``, same as
        every query method built directly here before.
        """
        stmt = select(cls)
        if hasattr(cls, "tenant_id"):
            from zeython.tenancy import current_tenant_id

            tenant_id = current_tenant_id()
            if tenant_id is not None:
                stmt = stmt.where(cls.tenant_id == tenant_id)  # type: ignore[misc,has-type]
        return stmt

    @classmethod
    async def find(cls, id_: Any, *, include_deleted: bool = False, include: Iterable[str] = ()) -> Self | None:
        session = current_session()
        stmt = cls._base_select().where(cls.id == id_)
        if not include_deleted:
            stmt = stmt.where(cls.is_deleted.is_(False))
        stmt = cls._with_includes(stmt, include)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @classmethod
    async def all(cls, *, include_deleted: bool = False, include: Iterable[str] = ()) -> list[Self]:
        session = current_session()
        stmt = cls._base_select()
        if not include_deleted:
            stmt = stmt.where(cls.is_deleted.is_(False))
        stmt = cls._with_includes(stmt, include)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @classmethod
    async def paginate(
        cls,
        *,
        page: int = 1,
        per_page: int = 20,
        include_deleted: bool = False,
        include: Iterable[str] = (),
    ) -> Page[Self]:
        """One page of results, plus the total row count for building pager UI.

        ``total`` (and therefore ``total_pages``) reflects every matching
        row, not just this page -- it costs a second query (a ``COUNT(*)``
        over the same filters) to get that number. If you only need the
        rows themselves, ``all()`` is cheaper.
        """
        if page < 1:
            raise ValueError("page must be >= 1")
        if per_page < 1:
            raise ValueError("per_page must be >= 1")

        session = current_session()
        stmt = cls._base_select()
        if not include_deleted:
            stmt = stmt.where(cls.is_deleted.is_(False))

        total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

        stmt = cls._with_includes(stmt, include)
        stmt = stmt.limit(per_page).offset((page - 1) * per_page)
        result = await session.execute(stmt)
        items = list(result.scalars().all())

        return Page(items=items, page=page, per_page=per_page, total=total)

    @classmethod
    async def find_by(
        cls, *, include_deleted: bool = False, include: Iterable[str] = (), **filters: Any
    ) -> list[Self]:
        session = current_session()
        stmt = cls._base_select()
        if not include_deleted:
            stmt = stmt.where(cls.is_deleted.is_(False))
        for field, value in filters.items():
            stmt = stmt.where(getattr(cls, field) == value)
        stmt = cls._with_includes(stmt, include)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @classmethod
    async def first_where(
        cls, *, include_deleted: bool = False, include: Iterable[str] = (), **filters: Any
    ) -> Self | None:
        results = await cls.find_by(include_deleted=include_deleted, include=include, **filters)
        return results[0] if results else None

    async def save(self) -> Self:
        is_new = self.id is None
        if is_new and hasattr(self, "tenant_id") and self.tenant_id is None:  # type: ignore[has-type]
            from zeython.tenancy import current_tenant_id

            self.tenant_id = current_tenant_id()  # type: ignore[attr-defined]
        await self.saving()
        await self._notify("saving")
        await (self.creating() if is_new else self.updating())
        await self._notify("creating" if is_new else "updating")

        self.validate_or_raise()
        session = current_session()
        session.add(self)
        await session.flush()

        await (self.created() if is_new else self.updated())
        await self._notify("created" if is_new else "updated")
        await self.saved()
        await self._notify("saved")
        return self

    async def update(self, **attributes: Any) -> Self:
        for key, value in attributes.items():
            setattr(self, key, value)
        return await self.save()

    async def delete(self, *, soft: bool = True) -> None:
        await self.deleting()
        await self._notify("deleting")
        session = current_session()
        if soft:
            self.is_deleted = True
            self.deleted_at = _utcnow()
            session.add(self)
            await session.flush()
        else:
            await session.delete(self)
            await session.flush()
        await self.deleted()
        await self._notify("deleted")

    async def restore(self) -> Self:
        self.is_deleted = False
        self.deleted_at = None
        return await self.save()

    def to_dict(self, *, exclude: tuple[str, ...] = (), include: tuple[str, ...] = ()) -> dict[str, Any]:
        """Serialize columns, plus any eagerly-loaded relationships named in ``include``.

        Raises ``RuntimeError`` (not the framework's problem to swallow) if
        a name in ``include`` wasn't eager-loaded on the query that fetched
        this instance -- see docs/relationships.md for why serializing an
        unloaded relationship isn't something this silently attempts.
        """
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

        if include:
            unloaded = inspect(self).unloaded
            for name in include:
                if name in unloaded:
                    raise RuntimeError(
                        f"Cannot serialize unloaded relationship '{name}' on {type(self).__name__}. "
                        f"Eager-load it first, e.g. "
                        f"`await {type(self).__name__}.find(id, include=('{name}',))`."
                    )
                related = getattr(self, name)
                if isinstance(related, list):
                    result[name] = [item.to_dict() if isinstance(item, Model) else item for item in related]
                elif isinstance(related, Model):
                    result[name] = related.to_dict()
                else:
                    result[name] = related

        return result

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id!r}>"

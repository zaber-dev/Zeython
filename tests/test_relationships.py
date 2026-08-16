from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from zeython.db import Model
from zeython.db.session import Database


class Author(Model):
    __tablename__ = "rel_authors"

    name: Mapped[str] = mapped_column(String(100))
    books: Mapped[list["Book"]] = relationship(back_populates="author")


class Book(Model):
    __tablename__ = "rel_books"

    title: Mapped[str] = mapped_column(String(100))
    author_id: Mapped[int] = mapped_column(ForeignKey("rel_authors.id"))
    author: Mapped[Author] = relationship(back_populates="books")


@pytest_asyncio.fixture
async def database() -> AsyncIterator[Database]:
    db = Database("sqlite+aiosqlite:///:memory:")
    async with db.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)
    yield db
    await db.dispose()


async def _seed(database: Database) -> int:
    async with database.session():
        author = await Author.create(name="Ada")
        await Book.create(title="Learning Python", author_id=author.id)
        return author.id


# -- include= eager loading ----------------------------------------------------------


async def test_find_without_include_leaves_relationship_unloaded(database: Database) -> None:
    await _seed(database)

    async with database.session():
        book = await Book.first_where(title="Learning Python")

    from sqlalchemy import inspect

    assert "author" in inspect(book).unloaded


async def test_find_with_include_loads_the_relationship(database: Database) -> None:
    await _seed(database)

    async with database.session():
        book = await Book.first_where(title="Learning Python", include=("author",))

    # Accessed *after* the session block closed -- this is the whole point:
    # eager loading means the data is already in memory, no further DB access needed.
    assert book.author.name == "Ada"


async def test_all_with_include_eager_loads_every_row(database: Database) -> None:
    async with database.session():
        author = await Author.create(name="Ada")
        await Book.create(title="Book One", author_id=author.id)
        await Book.create(title="Book Two", author_id=author.id)

    async with database.session():
        books = await Book.all(include=("author",))

    assert {book.author.name for book in books} == {"Ada"}


async def test_one_to_many_include(database: Database) -> None:
    author_id = await _seed(database)

    async with database.session():
        author = await Author.find(author_id, include=("books",))

    titles = {book.title for book in author.books}
    assert titles == {"Learning Python"}


async def test_find_by_and_first_where_accept_include(database: Database) -> None:
    await _seed(database)

    async with database.session():
        books = await Book.find_by(title="Learning Python", include=("author",))

    assert books[0].author.name == "Ada"


# -- to_dict(include=...) --------------------------------------------------------------


async def test_to_dict_serializes_eager_loaded_relationship(database: Database) -> None:
    await _seed(database)

    async with database.session():
        book = await Book.first_where(title="Learning Python", include=("author",))
        data = book.to_dict(include=("author",))

    assert data["title"] == "Learning Python"
    assert data["author"]["name"] == "Ada"


async def test_to_dict_serializes_eager_loaded_list_relationship(database: Database) -> None:
    author_id = await _seed(database)

    async with database.session():
        author = await Author.find(author_id, include=("books",))
        data = author.to_dict(include=("books",))

    assert data["name"] == "Ada"
    assert [b["title"] for b in data["books"]] == ["Learning Python"]


async def test_to_dict_raises_a_clear_error_for_unloaded_relationship(database: Database) -> None:
    await _seed(database)

    async with database.session():
        book = await Book.first_where(title="Learning Python")  # no include=

        with pytest.raises(RuntimeError, match="Eager-load it first"):
            book.to_dict(include=("author",))


async def test_to_dict_without_include_ignores_relationships_entirely(database: Database) -> None:
    await _seed(database)

    async with database.session():
        book = await Book.first_where(title="Learning Python")
        data = book.to_dict()  # no include= at all -- must not touch the relationship

    assert "author" not in data

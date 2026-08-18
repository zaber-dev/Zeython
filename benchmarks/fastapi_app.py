"""FastAPI + SQLAlchemy benchmark app -- see benchmarks/README.md.

Requires `pip install fastapi` (not a Zeython dependency -- this file
exists purely as a comparison reference point).
"""

from fastapi import FastAPI
from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DB_URL = "sqlite+aiosqlite:///./benchmark.db"
engine = create_async_engine(DB_URL)
Session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))


app = FastAPI()


@app.get("/json")
async def json_route():
    return {"hello": "world"}


@app.get("/items")
async def items_route():
    async with Session() as session:
        result = await session.execute(select(Item))
        items = result.scalars().all()
        return [{"id": item.id, "name": item.name} for item in items]

"""Raw Starlette + SQLAlchemy benchmark app -- see benchmarks/README.md.

No framework beyond Starlette itself: a plain declarative model, a plain
async engine, a session opened and closed by hand per request. This is
the "what you'd hand-roll without a framework" reference point.
"""

from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

DB_URL = "sqlite+aiosqlite:///./benchmark.db"
engine = create_async_engine(DB_URL)
Session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))


async def json_route(request):
    return JSONResponse({"hello": "world"})


async def items_route(request):
    async with Session() as session:
        result = await session.execute(select(Item))
        items = result.scalars().all()
        return JSONResponse([{"id": item.id, "name": item.name} for item in items])


app = Starlette(
    routes=[
        Route("/json", json_route),
        Route("/items", items_route),
    ]
)

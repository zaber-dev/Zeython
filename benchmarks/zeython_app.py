"""Zeython benchmark app -- see benchmarks/README.md for how to run this."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from starlette.responses import JSONResponse

from zeython import Application, DatabaseServiceProvider, Model

DB_PATH = "./benchmark.db"


class Item(Model):
    __tablename__ = "items"

    name: Mapped[str] = mapped_column(String(255))


app = Application()
app.register(DatabaseServiceProvider)


@app.get("/json")
async def json_route(request):
    return JSONResponse({"hello": "world"})


@app.get("/items")
async def items_route(request):
    items = await Item.all()
    return JSONResponse([item.to_dict() for item in items])


if __name__ == "__main__":
    app.run()

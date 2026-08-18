"""Creates benchmarks/benchmark.db with the `items` table and 100 seed
rows, shared by all three apps in this directory. Run once before
benchmarking: `python seed.py`.

Creates the table from zeython_app.py's own `Item(Model)` -- Model adds
`created_at`/`updated_at`/`is_deleted`/`deleted_at` columns Zeython's app
expects to exist. starlette_app.py/fastapi_app.py's own `Item` classes
only declare `id`/`name`; querying a table with columns beyond what a
model declares is exactly what they do, and works fine -- each app's
model determines what it selects, not what's in the table.
"""

import asyncio

from sqlalchemy.ext.asyncio import create_async_engine
from zeython_app import DB_PATH, Item

from zeython.db import Model

DB_URL = f"sqlite+aiosqlite:///{DB_PATH}"


async def main() -> None:
    engine = create_async_engine(DB_URL)
    async with engine.begin() as connection:
        await connection.run_sync(Model.metadata.drop_all)
        await connection.run_sync(Model.metadata.create_all)
        await connection.execute(Item.__table__.insert(), [{"name": f"Item {i}"} for i in range(100)])
    await engine.dispose()
    print("Seeded benchmark.db with 100 rows in `items`.")


if __name__ == "__main__":
    asyncio.run(main())

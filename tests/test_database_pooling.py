from pathlib import Path

import pytest
from sqlalchemy.pool import AsyncAdaptedQueuePool

from zeython.application import Application
from zeython.config import Config
from zeython.db.session import Database
from zeython.providers import DatabaseServiceProvider


def test_database_forwards_pool_size_and_max_overflow_to_the_engine() -> None:
    # In-memory SQLite's default pool (StaticPool) doesn't accept
    # pool_size/max_overflow at all -- forcing AsyncAdaptedQueuePool here
    # (what a file-based SQLite URL and postgresql+asyncpg/mysql+asyncmy
    # all use by default) is what makes this a real assertion against
    # SQLAlchemy's own pool configuration, not a mock, without requiring
    # the optional postgres/mysql extras.
    database = Database(
        "sqlite+aiosqlite:///:memory:",
        poolclass=AsyncAdaptedQueuePool,
        pool_size=5,
        max_overflow=10,
    )
    assert database.engine.pool.size() == 5
    assert database.engine.pool._max_overflow == 10


def test_database_service_provider_leaves_pool_kwargs_out_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Unset by default -- an explicit pool_size/max_overflow would only
    # ever break in-memory SQLite (StaticPool), not the file-based default
    # this provider actually points at, but there's still no good default
    # number to guess for every deployment.
    captured_kwargs: dict[str, object] = {}
    original_init = Database.__init__

    def spy_init(self: Database, url: str, *, echo: bool = False, **engine_kwargs: object) -> None:
        captured_kwargs.update(engine_kwargs)
        original_init(self, url, echo=echo, **engine_kwargs)

    monkeypatch.setattr(Database, "__init__", spy_init)

    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)

    assert "pool_size" not in captured_kwargs
    assert "max_overflow" not in captured_kwargs


def test_database_service_provider_forwards_configured_pool_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A real engine against the default file-based SQLite URL would also
    # work here (see test_database_forwards_pool_size_and_max_overflow_to_the_engine
    # for the direct proof) -- this test only checks that the provider
    # reads the config and passes it through, so the spy never calls the
    # real constructor.
    (tmp_path / ".env").write_text(
        "APP_SECRET_KEY=test\nDATABASE_POOL_SIZE=5\nDATABASE_MAX_OVERFLOW=10\n"
    )
    captured_kwargs: dict[str, object] = {}

    def spy_init(self: Database, url: str, *, echo: bool = False, **engine_kwargs: object) -> None:
        captured_kwargs.update(engine_kwargs)

    monkeypatch.setattr(Database, "__init__", spy_init)

    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)

    assert captured_kwargs["pool_size"] == 5
    assert captured_kwargs["max_overflow"] == 10


def test_end_to_end_against_the_real_default_file_based_sqlite_url(tmp_path: Path) -> None:
    # No mocking at all: registers the provider against the same
    # file-based SQLite URL `zeython new` scaffolds by default (unlike the
    # framework's own test suite, which uses :memory: everywhere else) and
    # inspects the real engine it builds.
    (tmp_path / ".env").write_text(
        "APP_SECRET_KEY=test\nDATABASE_POOL_SIZE=5\nDATABASE_MAX_OVERFLOW=10\n"
    )
    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)

    database = app.container.make(Database)
    assert isinstance(database.engine.pool, AsyncAdaptedQueuePool)
    assert database.engine.pool.size() == 5
    assert database.engine.pool._max_overflow == 10

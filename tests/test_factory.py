from pathlib import Path

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from zeython.application import Application
from zeython.config import Config
from zeython.database.factory import Factory
from zeython.db import Model
from zeython.db.session import Database
from zeython.providers import DatabaseServiceProvider

# Unique table name -- Model.metadata is process-global, so a name shared
# with another test file's throwaway model would collide on redefinition.


class FactoryWidget(Model):
    __tablename__ = "factory_widgets"

    name: Mapped[str] = mapped_column(String(255))


class WidgetFactory(Factory[FactoryWidget]):
    model = FactoryWidget

    def definition(self, sequence: int) -> dict:
        return {"name": f"Widget {sequence}"}


# -- make() / make_many() -- no database involved ------------------------------------


def test_make_builds_an_unsaved_instance_with_sequence_defaults() -> None:
    factory = WidgetFactory()

    first = factory.make()
    second = factory.make()

    assert first.name == "Widget 1"
    assert second.name == "Widget 2"
    assert first.id is None


def test_make_applies_overrides() -> None:
    widget = WidgetFactory().make(name="Custom")
    assert widget.name == "Custom"


def test_make_many_returns_distinct_sequence_values() -> None:
    widgets = WidgetFactory().make_many(3)
    assert [w.name for w in widgets] == ["Widget 1", "Widget 2", "Widget 3"]


def test_each_factory_instance_has_its_own_sequence() -> None:
    first_factory = WidgetFactory()
    second_factory = WidgetFactory()

    assert first_factory.make().name == "Widget 1"
    assert second_factory.make().name == "Widget 1"
    assert first_factory.make().name == "Widget 2"


# -- create() / create_many() -- persists via Model.create() -------------------------


async def _make_app(tmp_path: Path) -> Application:
    (tmp_path / ".env").write_text(
        "APP_SECRET_KEY=test-only-secret-not-for-production\nDATABASE_URL=sqlite+aiosqlite:///:memory:\n"
    )
    app = Application(Config.load(tmp_path))
    app.register(DatabaseServiceProvider)

    database = app.container.make(Database)
    async with database.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)

    return app


async def test_create_persists_via_model_create(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    database = app.container.make(Database)

    async with database.session():
        widget = await WidgetFactory().create()

        assert widget.id is not None
        found = await FactoryWidget.find(widget.id)
        assert found is not None
        assert found.name == "Widget 1"


async def test_create_applies_overrides(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    database = app.container.make(Database)

    async with database.session():
        widget = await WidgetFactory().create(name="Override")
        assert widget.name == "Override"


async def test_create_many_persists_count_rows(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    database = app.container.make(Database)

    async with database.session():
        widgets = await WidgetFactory().create_many(3)

        assert len(widgets) == 3
        assert len({w.id for w in widgets}) == 3
        assert len(await FactoryWidget.all()) == 3

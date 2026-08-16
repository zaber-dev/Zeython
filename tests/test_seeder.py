import asyncio
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from zeython.application import Application
from zeython.cli.loader import load_app
from zeython.cli.main import app as cli_app
from zeython.config import Config
from zeython.database.seeder import Seeder, discover_seeders
from zeython.db.session import Database

runner = CliRunner()


# -- Seeder.call() -- no database involved --------------------------------------------


async def test_call_runs_each_seeder_in_order(tmp_path: Path) -> None:
    calls: list[str] = []

    class FirstSeeder(Seeder):
        async def run(self) -> None:
            calls.append("first")

    class SecondSeeder(Seeder):
        async def run(self) -> None:
            calls.append("second")

    class RootSeeder(Seeder):
        async def run(self) -> None:
            await self.call(FirstSeeder, SecondSeeder)

    (tmp_path / ".env").write_text(
        "APP_SECRET_KEY=test-only-secret-not-for-production\nDATABASE_URL=sqlite+aiosqlite:///:memory:\n"
    )
    app = Application(Config.load(tmp_path))

    await RootSeeder(app).run()

    assert calls == ["first", "second"]


# -- discover_seeders() -- filesystem only, no CLI ------------------------------------


def _write_seeder(seeders_dir: Path, filename: str, source: str) -> None:
    seeders_dir.mkdir(parents=True, exist_ok=True)
    (seeders_dir / "__init__.py").touch(exist_ok=True)
    (seeders_dir.parent / "__init__.py").touch(exist_ok=True)
    (seeders_dir.parent.parent / "__init__.py").touch(exist_ok=True)
    (seeders_dir / filename).write_text(source)


def test_discover_seeders_returns_empty_dict_when_no_seeders_dir(tmp_path: Path) -> None:
    assert discover_seeders(tmp_path) == {}


def test_discover_seeders_finds_seeder_subclasses_keyed_by_class_name(tmp_path: Path) -> None:
    _write_seeder(
        tmp_path / "database" / "seeders",
        "user_seeder.py",
        "from zeython.database.seeder import Seeder\n\n"
        "class UserSeeder(Seeder):\n"
        "    async def run(self): ...\n",
    )

    seeders = discover_seeders(tmp_path)

    assert set(seeders) == {"UserSeeder"}


def test_discover_seeders_skips_non_seeder_classes(tmp_path: Path) -> None:
    _write_seeder(
        tmp_path / "database" / "seeders",
        "user_seeder.py",
        "from zeython.database.seeder import Seeder\n\n"
        "class NotASeederHelper:\n"
        "    pass\n\n"
        "class UserSeeder(Seeder):\n"
        "    async def run(self): ...\n",
    )

    seeders = discover_seeders(tmp_path)

    assert set(seeders) == {"UserSeeder"}


# -- CLI: `zeython db seed` / `zeython make factory|seeder` --------------------------


@pytest.fixture(scope="module")
def seed_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # Module-scoped, like test_mcp.py's scaffold_project: Model.metadata is
    # process-global, so a second differently-rooted project redefining a
    # "seed_widgets" table (one per test, via a function-scoped fixture)
    # would collide the moment its Widget model gets re-imported.
    destination = tmp_path_factory.mktemp("seed_test_app")
    (destination / "app" / "Models").mkdir(parents=True)
    (destination / "database" / "factories").mkdir(parents=True)
    (destination / "database" / "seeders").mkdir(parents=True)
    for pkg_init in [
        destination / "app" / "__init__.py",
        destination / "app" / "Models" / "__init__.py",
        destination / "database" / "__init__.py",
        destination / "database" / "factories" / "__init__.py",
        destination / "database" / "seeders" / "__init__.py",
    ]:
        pkg_init.touch()

    db_path = destination / "database.db"
    (destination / ".env").write_text(
        f"APP_NAME=Seed Test App\nAPP_SECRET_KEY=test-secret\nDATABASE_URL=sqlite+aiosqlite:///{db_path}\n"
    )
    (destination / "main.py").write_text(
        "from zeython import Application, DatabaseServiceProvider\n\n"
        "from app.Models.widget import Widget  # noqa: F401 -- registers the table for create_all()\n\n"
        "app = Application()\n"
        "app.register(DatabaseServiceProvider)\n"
    )
    (destination / "app" / "Models" / "widget.py").write_text(
        "from sqlalchemy import String\n"
        "from sqlalchemy.orm import Mapped, mapped_column\n\n"
        "from zeython import Model\n\n\n"
        "class Widget(Model):\n"
        "    __tablename__ = 'seed_widgets'\n\n"
        "    name: Mapped[str] = mapped_column(String(255))\n"
    )
    (destination / "database" / "factories" / "widget_factory.py").write_text(
        "from zeython import Factory\n\n"
        "from app.Models.widget import Widget\n\n\n"
        "class WidgetFactory(Factory[Widget]):\n"
        "    model = Widget\n\n"
        "    def definition(self, sequence: int) -> dict:\n"
        "        return {'name': f'Widget {sequence}'}\n"
    )
    (destination / "database" / "seeders" / "database_seeder.py").write_text(
        "from zeython import Seeder\n\n"
        "from database.factories.widget_factory import WidgetFactory\n\n\n"
        "class DatabaseSeeder(Seeder):\n"
        "    async def run(self) -> None:\n"
        "        await WidgetFactory().create_many(3)\n"
    )

    async def _run() -> None:
        application = load_app(destination)
        database = application.container.make(Database)
        await database.create_all()
        await database.dispose()

    asyncio.run(_run())

    return destination


def test_db_seed_runs_the_default_database_seeder(seed_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(seed_project)

    result = runner.invoke(cli_app, ["db", "seed"])

    assert result.exit_code == 0, result.output
    assert "Seeded using DatabaseSeeder" in result.output

    connection = sqlite3.connect(seed_project / "database.db")
    try:
        count = connection.execute("SELECT COUNT(*) FROM seed_widgets").fetchone()[0]
    finally:
        connection.close()
    assert count == 3


def test_db_seed_unknown_class_exits_nonzero_and_lists_available(
    seed_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(seed_project)

    result = runner.invoke(cli_app, ["db", "seed", "--class", "NotARealSeeder"])

    assert result.exit_code == 1
    assert "DatabaseSeeder" in result.output


def test_make_factory_scaffolds_a_factory_file(seed_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(seed_project)

    result = runner.invoke(cli_app, ["make", "factory", "Tag"])

    assert result.exit_code == 0
    assert (seed_project / "database" / "factories" / "tag_factory.py").is_file()


def test_make_seeder_scaffolds_a_seeder_file(seed_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(seed_project)

    result = runner.invoke(cli_app, ["make", "seeder", "Tag"])

    assert result.exit_code == 0
    assert (seed_project / "database" / "seeders" / "tag_seeder.py").is_file()

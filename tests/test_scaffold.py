from pathlib import Path

import pytest

from zeython.cli import scaffold

# -- naming helpers -------------------------------------------------------------------


def test_to_snake_case_converts_pascal_case() -> None:
    assert scaffold.to_snake_case("PostController") == "post_controller"


def test_to_snake_case_converts_spaced_words() -> None:
    assert scaffold.to_snake_case("My Blog") == "my_blog"


def test_to_snake_case_is_idempotent_on_already_snake_case() -> None:
    assert scaffold.to_snake_case("send_welcome_email") == "send_welcome_email"


def test_to_pascal_case_converts_snake_case() -> None:
    assert scaffold.to_pascal_case("send_welcome_email") == "SendWelcomeEmail"


def test_to_pascal_case_converts_spaced_words() -> None:
    assert scaffold.to_pascal_case("My Blog") == "MyBlog"


# -- new_project ------------------------------------------------------------------------


def test_new_project_creates_the_full_directory_layout(tmp_path: Path) -> None:
    destination = tmp_path / "my_blog"
    scaffold.new_project("My Blog", destination)

    for expected in (
        "main.py",
        "alembic.ini",
        ".env.example",
        "Dockerfile",
        "docker-compose.yml",
        ".dockerignore",
        "app/__init__.py",
        "app/Controllers/__init__.py",
        "app/Models/__init__.py",
        "app/Middleware/__init__.py",
        "app/Jobs/__init__.py",
        "app/Providers/__init__.py",
        "app/Console/Commands/__init__.py",
        "database/__init__.py",
        "database/factories/__init__.py",
        "database/factories/user_factory.py",
        "database/seeders/__init__.py",
        "database/seeders/database_seeder.py",
        "routes/web.py",
        "migrations/env.py",
        "tests/conftest.py",
    ):
        assert (destination / expected).is_file(), f"missing {expected}"


def test_new_project_renders_placeholders(tmp_path: Path) -> None:
    destination = tmp_path / "my_blog"
    scaffold.new_project("My Blog", destination)

    pyproject = (destination / "pyproject.toml").read_text()
    assert "my_blog" in pyproject
    assert "{{" not in pyproject

    env_example = (destination / ".env.example").read_text()
    assert "My Blog" in env_example
    assert "{{" not in env_example


def test_new_project_pyproject_declares_a_dev_extra_with_pytest(tmp_path: Path) -> None:
    # docs/testing.md and the generated README both tell users to run
    # `pytest` after `pip install -e ".[dev]"` -- if the generated
    # pyproject.toml has no `dev` extra, pip silently installs without it
    # (a missing extra is a warning, not an error) and `pytest` is never
    # actually on PATH. Guards against that regressing silently again.
    destination = tmp_path / "my_blog"
    scaffold.new_project("My Blog", destination)

    pyproject = (destination / "pyproject.toml").read_text()
    assert "[project.optional-dependencies]" in pyproject
    assert "pytest" in pyproject
    assert "pytest-asyncio" in pyproject
    assert "httpx" in pyproject


def test_new_project_generates_a_fresh_secret_key_each_time(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    scaffold.new_project("First", first)
    scaffold.new_project("Second", second)

    def secret_key(env_example: Path) -> str:
        for line in env_example.read_text().splitlines():
            if line.startswith("APP_SECRET_KEY="):
                return line
        raise AssertionError("APP_SECRET_KEY not found")

    assert secret_key(first / ".env.example") != secret_key(second / ".env.example")


def test_new_project_skips_pycache_directories(tmp_path: Path) -> None:
    # A pip install of the framework bytecode-compiles the template .py files,
    # leaving __pycache__ dirs alongside them in an installed copy -- those
    # must never be copied into a generated project.
    pycache = scaffold._TEMPLATES_DIR / "__pycache__"
    pycache.mkdir(exist_ok=True)
    (pycache / "junk.pyc").write_bytes(b"")
    try:
        destination = tmp_path / "my_blog"
        scaffold.new_project("My Blog", destination)
        assert not any(destination.rglob("__pycache__"))
    finally:
        import shutil

        shutil.rmtree(pycache, ignore_errors=True)


def test_new_project_raises_if_destination_exists_and_is_not_empty(tmp_path: Path) -> None:
    destination = tmp_path / "my_blog"
    destination.mkdir()
    (destination / "keep.txt").write_text("pre-existing")

    with pytest.raises(FileExistsError):
        scaffold.new_project("My Blog", destination)


def test_new_project_allows_an_existing_empty_destination(tmp_path: Path) -> None:
    destination = tmp_path / "my_blog"
    destination.mkdir()
    scaffold.new_project("My Blog", destination)  # must not raise
    assert (destination / "main.py").is_file()


# -- make_model / make_controller / make_middleware / make_provider / make_job --------


@pytest.fixture
def project(tmp_path: Path) -> Path:
    destination = tmp_path / "my_blog"
    scaffold.new_project("My Blog", destination)
    return destination


def test_make_model_creates_the_file_and_registers_the_import(project: Path) -> None:
    path = scaffold.make_model("Comment", project)

    assert path == project / "app" / "Models" / "comment.py"
    assert "class Comment(Model):" in path.read_text()
    assert '__tablename__ = "comments"' in path.read_text()

    init_contents = (project / "app" / "Models" / "__init__.py").read_text()
    assert "from app.Models.comment import Comment" in init_contents


def test_make_model_raises_if_the_file_already_exists(project: Path) -> None:
    scaffold.make_model("Comment", project)
    with pytest.raises(FileExistsError):
        scaffold.make_model("Comment", project)


def test_make_controller_appends_controller_suffix_once(project: Path) -> None:
    path = scaffold.make_controller("Comment", project)
    assert path == project / "app" / "Controllers" / "comment_controller.py"
    assert "class CommentController(Controller):" in path.read_text()


def test_make_controller_does_not_double_the_suffix(project: Path) -> None:
    path = scaffold.make_controller("CommentController", project)
    assert path == project / "app" / "Controllers" / "comment_controller.py"
    assert "class CommentController(Controller):" in path.read_text()


def test_make_middleware_creates_the_file(project: Path) -> None:
    path = scaffold.make_middleware("RequestLogger", project)
    assert path == project / "app" / "Middleware" / "request_logger.py"
    assert "class RequestLogger:" in path.read_text()


def test_make_provider_appends_service_provider_suffix(project: Path) -> None:
    path = scaffold.make_provider("Payment", project)
    assert path == project / "app" / "Providers" / "payment_service_provider.py"
    assert "class PaymentServiceProvider(ServiceProvider):" in path.read_text()


def test_make_provider_does_not_double_an_existing_provider_suffix(project: Path) -> None:
    path = scaffold.make_provider("PaymentProvider", project)
    assert path == project / "app" / "Providers" / "payment_provider.py"
    assert "class PaymentProvider(ServiceProvider):" in path.read_text()


def test_make_job_appends_job_suffix(project: Path) -> None:
    path = scaffold.make_job("SendInvoice", project)
    assert path == project / "app" / "Jobs" / "send_invoice_job.py"
    assert "class SendInvoiceJob(Job):" in path.read_text()


def test_make_command_appends_command_suffix(project: Path) -> None:
    path = scaffold.make_command("PruneOldSessions", project)
    assert path == project / "app" / "Console" / "Commands" / "prune_old_sessions_command.py"
    assert "class PruneOldSessionsCommand(Command):" in path.read_text()
    assert "zeython command prune-old-sessions" in path.read_text()


def test_make_factory_appends_factory_suffix(project: Path) -> None:
    path = scaffold.make_factory("Comment", project)
    assert path == project / "database" / "factories" / "comment_factory.py"
    content = path.read_text()
    assert "class CommentFactory(Factory[Comment]):" in content
    assert "from app.Models.comment import Comment" in content


def test_make_factory_does_not_double_the_suffix(project: Path) -> None:
    path = scaffold.make_factory("CommentFactory", project)
    assert path == project / "database" / "factories" / "comment_factory.py"
    assert "class CommentFactory(Factory[Comment]):" in path.read_text()


def test_make_seeder_appends_seeder_suffix(project: Path) -> None:
    path = scaffold.make_seeder("Comment", project)
    assert path == project / "database" / "seeders" / "comment_seeder.py"
    assert "class CommentSeeder(Seeder):" in path.read_text()


def test_make_seeder_does_not_double_the_suffix(project: Path) -> None:
    path = scaffold.make_seeder("CommentSeeder", project)
    assert path == project / "database" / "seeders" / "comment_seeder.py"
    assert "class CommentSeeder(Seeder):" in path.read_text()


def test_new_project_migrations_env_enables_sqlite_batch_mode(tmp_path: Path) -> None:
    # Without render_as_batch=True, Alembic can only emit a bare ALTER TABLE,
    # which SQLite rejects for anything beyond adding a plain column (no
    # constraint changes) -- e.g. `alembic revision --autogenerate` after
    # adding a ForeignKey to an existing model raises "No support for ALTER
    # of constraints in SQLite dialect" the first time a generated project
    # runs a real migration. Batch mode is a no-op on Postgres/MySQL.
    destination = tmp_path / "my_blog"
    scaffold.new_project("My Blog", destination)

    env_py = (destination / "migrations" / "env.py").read_text()
    assert env_py.count("render_as_batch=True") == 2


def test_new_project_conftest_isolates_tests_from_the_dev_database(tmp_path: Path) -> None:
    # Without this, `pytest` shares the same DATABASE_URL as `zeython serve`
    # (a persistent file, not :memory:) -- a test registering a user with an
    # email already used against the running dev server fails on a UNIQUE
    # constraint that has nothing to do with the test itself.
    destination = tmp_path / "my_blog"
    scaffold.new_project("My Blog", destination)

    conftest = (destination / "tests" / "conftest.py").read_text()
    assert "sqlite+aiosqlite:///:memory:" in conftest

"""Direct tests for zeython.cli.main -- previously only exercised through
the CI scaffold-smoke-test job (a real shelled-out `zeython` process, not
pytest) and, indirectly, the `commands`/`command`/`make command`/`db seed`
paths test_console.py and test_seeder.py already cover via the same
CliRunner. This file covers what neither does: `new`, `serve`, `mcp`,
the other `make *` generators, the `db migrate/revision/downgrade` alembic
wrapper, and `main()`.
"""

import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from zeython.cli.main import app as cli_app

runner = CliRunner()


def _fake_subprocess_run(calls: list[list[str]]):
    def fake_run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode=0)

    return fake_run

# -- new --------------------------------------------------------------------------------


def test_new_creates_a_project_at_the_default_slugified_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli_app, ["new", "My Blog"])

    assert result.exit_code == 0
    assert (tmp_path / "my_blog" / "main.py").is_file()
    assert "Created new Zeython project" in result.stdout
    assert "zeython serve" in result.stdout


def test_new_respects_an_explicit_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    destination = tmp_path / "somewhere-else"

    result = runner.invoke(cli_app, ["new", "My Blog", "--path", str(destination)])

    assert result.exit_code == 0
    assert (destination / "main.py").is_file()


def test_new_exits_nonzero_when_the_destination_already_exists_and_is_not_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "my_blog").mkdir()
    (tmp_path / "my_blog" / "some_file.txt").touch()

    result = runner.invoke(cli_app, ["new", "My Blog"])

    assert result.exit_code == 1
    assert "already exists" in result.stdout


# -- serve --------------------------------------------------------------------------------


def test_serve_passes_config_defaults_to_uvicorn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("APP_HOST=0.0.0.0\nAPP_PORT=9001\nAPP_DEBUG=true\n")
    monkeypatch.chdir(tmp_path)

    calls: list[dict] = []
    monkeypatch.setattr("uvicorn.run", lambda app_import, **kwargs: calls.append({"app_import": app_import, **kwargs}))

    result = runner.invoke(cli_app, ["serve"])

    assert result.exit_code == 0
    assert calls == [{"app_import": "main:app", "host": "0.0.0.0", "port": 9001, "reload": True}]


def test_serve_cli_options_override_config_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("APP_HOST=0.0.0.0\nAPP_PORT=9001\nAPP_DEBUG=true\n")
    monkeypatch.chdir(tmp_path)

    calls: list[dict] = []
    monkeypatch.setattr("uvicorn.run", lambda app_import, **kwargs: calls.append({"app_import": app_import, **kwargs}))

    result = runner.invoke(
        cli_app,
        ["serve", "--app", "custom:asgi_app", "--host", "127.0.0.1", "--port", "8888", "--no-reload"],
    )

    assert result.exit_code == 0
    assert calls == [
        {"app_import": "custom:asgi_app", "host": "127.0.0.1", "port": 8888, "reload": False}
    ]


# -- mcp --------------------------------------------------------------------------------


def test_mcp_exits_nonzero_with_an_install_hint_when_the_extra_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # "None" in sys.modules is Python's own signal for "this import was
    # already attempted and failed" -- the standard way to force an
    # ImportError for a module without needing to actually uninstall it.
    monkeypatch.setitem(sys.modules, "zeython.mcp.server", None)

    result = runner.invoke(cli_app, ["mcp"])

    assert result.exit_code == 1
    assert "pip install zeython[mcp]" in result.stdout


def test_mcp_runs_the_server_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("mcp")
    calls = []
    monkeypatch.setattr("zeython.mcp.server.main", lambda: calls.append(True))

    result = runner.invoke(cli_app, ["mcp"])

    assert result.exit_code == 0
    assert calls == [True]


# -- make model / controller / middleware / provider / job ------------------------------


def test_make_model_creates_the_file_and_registers_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "app" / "Models").mkdir(parents=True)
    (tmp_path / "app" / "Models" / "__init__.py").touch()

    result = runner.invoke(cli_app, ["make", "model", "Post"])

    assert result.exit_code == 0
    assert (tmp_path / "app" / "Models" / "post.py").is_file()
    assert "from app.Models.post import Post" in (tmp_path / "app" / "Models" / "__init__.py").read_text()
    assert "Created" in result.stdout


def test_make_controller_creates_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli_app, ["make", "controller", "Post"])

    assert result.exit_code == 0
    assert (tmp_path / "app" / "Controllers" / "post_controller.py").is_file()


def test_make_middleware_creates_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli_app, ["make", "middleware", "RequestLogger"])

    assert result.exit_code == 0
    assert (tmp_path / "app" / "Middleware" / "request_logger.py").is_file()


def test_make_provider_creates_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli_app, ["make", "provider", "Payment"])

    assert result.exit_code == 0
    assert (tmp_path / "app" / "Providers" / "payment_service_provider.py").is_file()


def test_make_job_creates_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli_app, ["make", "job", "SendWelcomeEmail"])

    assert result.exit_code == 0
    assert (tmp_path / "app" / "Jobs" / "send_welcome_email_job.py").is_file()


# -- db migrate / revision / downgrade (the alembic subprocess wrapper) -----------------


def test_db_migrate_reports_missing_alembic_ini(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli_app, ["db", "migrate"])

    assert result.exit_code == 1
    assert "No alembic.ini found" in result.stdout


def test_db_migrate_invokes_alembic_upgrade_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "alembic.ini").touch()

    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run(calls))

    result = runner.invoke(cli_app, ["db", "migrate"])

    assert result.exit_code == 0
    assert calls == [[sys.executable, "-m", "alembic", "upgrade", "head"]]


def test_db_revision_invokes_alembic_autogenerate_with_the_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "alembic.ini").touch()

    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run(calls))

    result = runner.invoke(cli_app, ["db", "revision", "-m", "add posts table"])

    assert result.exit_code == 0
    assert calls == [[sys.executable, "-m", "alembic", "revision", "--autogenerate", "-m", "add posts table"]]


def test_db_downgrade_defaults_to_one_step_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "alembic.ini").touch()

    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run(calls))

    result = runner.invoke(cli_app, ["db", "downgrade"])

    assert result.exit_code == 0
    assert calls == [[sys.executable, "-m", "alembic", "downgrade", "-1"]]


def test_db_downgrade_accepts_an_explicit_revision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "alembic.ini").touch()

    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run(calls))

    result = runner.invoke(cli_app, ["db", "downgrade", "abc123"])

    assert result.exit_code == 0
    assert calls == [[sys.executable, "-m", "alembic", "downgrade", "abc123"]]


def test_db_migrate_exit_code_matches_the_alembic_subprocesss_returncode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "alembic.ini").touch()
    monkeypatch.setattr(subprocess, "run", lambda cmd, cwd: subprocess.CompletedProcess(cmd, returncode=3))

    result = runner.invoke(cli_app, ["db", "migrate"])

    assert result.exit_code == 3


# -- main() -------------------------------------------------------------------------------


def test_main_delegates_to_the_typer_app(monkeypatch: pytest.MonkeyPatch) -> None:
    import zeython.cli.main as cli_main_module

    calls = []
    monkeypatch.setattr(cli_main_module, "app", lambda: calls.append(True))

    cli_main_module.main()

    assert calls == [True]

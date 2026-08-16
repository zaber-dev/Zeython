from pathlib import Path

import pytest
from typer.testing import CliRunner

from zeython.application import Application
from zeython.cli.main import app as cli_app
from zeython.config import Config
from zeython.console import Command, discover_commands

runner = CliRunner()

# -- Command / discover_commands (no CLI) ----------------------------------------------


def test_command_init_exposes_app_container_and_config(tmp_path: Path) -> None:
    class NoOpCommand(Command):
        async def handle(self, *args: str) -> None: ...

    app = Application(Config.load(tmp_path))
    command = NoOpCommand(app)

    assert command.app is app
    assert command.container is app.container
    assert command.config is app.config


def _write_command(commands_dir: Path, filename: str, source: str) -> None:
    commands_dir.mkdir(parents=True, exist_ok=True)
    (commands_dir / "__init__.py").touch(exist_ok=True)
    (commands_dir.parent / "__init__.py").touch(exist_ok=True)
    (commands_dir.parent.parent / "__init__.py").touch(exist_ok=True)
    (commands_dir / filename).write_text(source)


def test_discover_commands_returns_empty_dict_when_no_commands_dir(tmp_path: Path) -> None:
    assert discover_commands(tmp_path) == {}


def test_discover_commands_defaults_name_to_the_snake_case_filename(tmp_path: Path) -> None:
    _write_command(
        tmp_path / "app" / "Console" / "Commands",
        "send_report.py",
        "from zeython.console import Command\n\n"
        "class SendReportCommand(Command):\n"
        "    async def handle(self, *args): ...\n",
    )

    commands = discover_commands(tmp_path)

    assert set(commands) == {"send-report"}
    assert commands["send-report"].__name__ == "SendReportCommand"


def test_discover_commands_strips_a_command_suffix_from_the_filename(tmp_path: Path) -> None:
    # Matches `zeython make command`'s own file-naming convention
    # (`say_hi_command.py`) -- the default CLI name should be `say-hi`,
    # not the un-stripped `say-hi-command`.
    _write_command(
        tmp_path / "app" / "Console" / "Commands",
        "say_hi_command.py",
        "from zeython.console import Command\n\n"
        "class SayHiCommand(Command):\n"
        "    async def handle(self, *args): ...\n",
    )

    commands = discover_commands(tmp_path)

    assert set(commands) == {"say-hi"}


def test_discover_commands_respects_an_explicit_name_override(tmp_path: Path) -> None:
    _write_command(
        tmp_path / "app" / "Console" / "Commands",
        "send_report.py",
        "from zeython.console import Command\n\n"
        "class SendReportCommand(Command):\n"
        "    name = 'reports:send'\n"
        "    async def handle(self, *args): ...\n",
    )

    commands = discover_commands(tmp_path)

    assert set(commands) == {"reports:send"}


def test_discover_commands_skips_init_and_non_command_classes(tmp_path: Path) -> None:
    commands_dir = tmp_path / "app" / "Console" / "Commands"
    _write_command(
        commands_dir,
        "greet.py",
        "from zeython.console import Command\n\n"
        "class NotACommandHelper:\n"
        "    pass\n\n"
        "class GreetCommand(Command):\n"
        "    async def handle(self, *args): ...\n",
    )

    commands = discover_commands(tmp_path)

    assert set(commands) == {"greet"}


def test_discover_commands_reports_help_text(tmp_path: Path) -> None:
    _write_command(
        tmp_path / "app" / "Console" / "Commands",
        "greet.py",
        "from zeython.console import Command\n\n"
        "class GreetCommand(Command):\n"
        "    help = 'Says hello.'\n"
        "    async def handle(self, *args): ...\n",
    )

    commands = discover_commands(tmp_path)

    assert commands["greet"].help == "Says hello."


# -- CLI: `zeython commands` / `zeython command <name>` --------------------------------


@pytest.fixture
def project(tmp_path: Path) -> Path:
    # Deliberately NOT the full new_project() scaffold: that imports
    # app.Models.user/post, and Model.registry/Model.metadata are
    # process-global -- a second scaffold in the same pytest session
    # (test_mcp.py's module-scoped one already claims "users"/"posts")
    # would collide on table redefinition. This is a minimal project with
    # no models at all, which is all `zeython commands`/`zeython command`
    # actually need to be exercised. The real generated demo command
    # (app/Console/Commands/prune_old_posts.py) is verified separately,
    # end-to-end, against a real installed wheel -- see the framework's
    # own verification notes, not duplicated here via import.
    destination = tmp_path / "console_test_app"
    commands_dir = destination / "app" / "Console" / "Commands"
    commands_dir.mkdir(parents=True)
    (destination / "app" / "__init__.py").touch()
    (destination / "app" / "Console" / "__init__.py").touch()
    (commands_dir / "__init__.py").touch()
    (destination / ".env").write_text("APP_NAME=Console Test App\nAPP_SECRET_KEY=test-secret\n")
    (destination / "main.py").write_text("from zeython import Application\n\napp = Application()\n")
    (commands_dir / "greet.py").write_text(
        "from zeython import Command\n\n"
        "class GreetCommand(Command):\n"
        "    help = 'Prints a greeting.'\n"
        "    async def handle(self, *args: str) -> None:\n"
        "        print('hello')\n"
    )
    return destination


def test_zeython_commands_lists_a_discovered_command(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(project)
    result = runner.invoke(cli_app, ["commands"])

    assert result.exit_code == 0
    assert "greet" in result.stdout
    assert "Prints a greeting." in result.stdout


def test_zeython_commands_reports_none_found_with_no_commands_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_app, ["commands"])

    assert result.exit_code == 0
    assert "No custom commands found" in result.stdout


def test_zeython_command_runs_a_discovered_command_and_passes_args_through(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "app" / "Console" / "Commands" / "echo_args.py").write_text(
        "from zeython import Command\n\n"
        "class EchoArgsCommand(Command):\n"
        "    async def handle(self, *args: str) -> None:\n"
        "        print('got:', list(args))\n"
    )
    monkeypatch.chdir(project)

    result = runner.invoke(cli_app, ["command", "echo-args", "foo", "--bar=baz"])

    assert result.exit_code == 0
    assert "got: ['foo', '--bar=baz']" in result.stdout


def test_zeython_command_unknown_name_exits_nonzero_and_lists_available(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(project)

    result = runner.invoke(cli_app, ["command", "does-not-exist"])

    assert result.exit_code == 1
    assert "greet" in result.stdout


def test_make_command_scaffolds_a_command_runnable_immediately(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(project)

    make_result = runner.invoke(cli_app, ["make", "command", "SayHi"])
    assert make_result.exit_code == 0
    # The filename keeps the full "_command" suffix (matching make_job's
    # "_job.py" convention); only the CLI-facing name strips it, for a
    # clean `zeython command say-hi` instead of `zeython command say-hi-command`.
    assert (project / "app" / "Console" / "Commands" / "say_hi_command.py").is_file()

    list_result = runner.invoke(cli_app, ["commands"])
    assert "  say-hi  " in list_result.stdout
    assert "say-hi-command" not in list_result.stdout

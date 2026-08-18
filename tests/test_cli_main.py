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

#: Captured once, before any test in this file starts calling load_app()
#: (via `queue work`/`db migrate`/`db seed`/`schedule run`/`schedule list`)
#: and accumulating sys.path entries -- see _isolate_loader_global_state.
_PRISTINE_SYS_PATH = list(sys.path)


@pytest.fixture(autouse=True)
def _isolate_loader_global_state(monkeypatch: pytest.MonkeyPatch) -> None:
    # cli.loader._import_main() caches the "main" module by name and
    # reloads it (from its *original* file path) on a second call rather
    # than re-importing -- across many different tmp_path projects in this
    # file, a later test's load_app() would otherwise silently re-execute
    # an *earlier* test's main.py instead of its own. Same root cause as
    # test_cli_loader.py's identical fixture; masked here until a test's
    # main.py/schedule.py content actually differed enough to expose it.
    import zeython.cli.loader as loader_module

    monkeypatch.setattr(loader_module, "_current_project_root", None)
    monkeypatch.delitem(sys.modules, "main", raising=False)
    # "schedule" isn't one of sync_project_modules()'s tracked packages
    # (only "app"/"database" are) -- it's imported by plain module name via
    # ScheduleServiceProvider, same caching risk as "main" itself.
    monkeypatch.delitem(sys.modules, "schedule", raising=False)
    monkeypatch.setattr(sys, "path", list(_PRISTINE_SYS_PATH))


def _simulate_a_fresh_process() -> None:
    # `zeython schedule run` is always a brand-new OS process in real usage
    # (cron, or a `while true; zeython schedule run; sleep 60` sidecar loop)
    # -- sys.modules is empty every time. Two runner.invoke() calls within
    # one test share a process/sys.modules that a real double-invocation
    # never would, so tests exercising "two separate invocations" reset the
    # same state _isolate_loader_global_state resets between tests, but
    # mid-test, between the two invoke() calls.
    import zeython.cli.loader as loader_module

    loader_module._current_project_root = None
    sys.modules.pop("main", None)
    sys.modules.pop("schedule", None)


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


# -- queue work ---------------------------------------------------------------------------


def _minimal_project(tmp_path: Path, *, extra_env: str = "") -> Path:
    (tmp_path / ".env").write_text(f"APP_SECRET_KEY=test\n{extra_env}")
    (tmp_path / "main.py").write_text(
        "from zeython import Application, QueueServiceProvider\n\n"
        "app = Application()\n"
        "app.register(QueueServiceProvider)\n"
    )
    return tmp_path


def test_queue_work_rejects_the_default_in_memory_driver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(_minimal_project(tmp_path))

    result = runner.invoke(cli_app, ["queue", "work"])

    assert result.exit_code == 1
    assert "QUEUE_DRIVER=redis" in result.stdout


def test_queue_work_runs_the_worker_for_a_redis_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("redis")
    import os

    redis_url = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
    monkeypatch.chdir(_minimal_project(tmp_path, extra_env=f"QUEUE_DRIVER=redis\nREDIS_URL={redis_url}\n"))

    from zeython.queue import RedisQueue

    calls = []

    async def fake_run_worker(self, **kwargs):  # noqa: ANN001, ANN003
        calls.append(True)
        raise KeyboardInterrupt  # simulates Ctrl+C stopping the worker

    monkeypatch.setattr(RedisQueue, "run_worker", fake_run_worker)

    result = runner.invoke(cli_app, ["queue", "work"])

    assert result.exit_code == 0
    assert calls == [True]
    assert "Working queue 'default'" in result.stdout
    assert "Stopped." in result.stdout


# -- schedule run / schedule list ----------------------------------------------------------


def _project_with_schedule(tmp_path: Path, schedule_body: str) -> Path:
    (tmp_path / ".env").write_text("APP_SECRET_KEY=test\n")
    (tmp_path / "main.py").write_text(
        "from zeython import Application, ScheduleServiceProvider\n\n"
        "app = Application()\n"
        "app.register(ScheduleServiceProvider(app))\n"
    )
    (tmp_path / "schedule.py").write_text(schedule_body)
    return tmp_path


def test_schedule_list_reports_no_tasks_when_none_are_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(_project_with_schedule(tmp_path, "from main import app  # no events registered\n"))

    result = runner.invoke(cli_app, ["schedule", "list"])

    assert result.exit_code == 0
    assert "No scheduled tasks registered" in result.stdout


def test_schedule_list_shows_each_registered_events_cron_expression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(
        _project_with_schedule(
            tmp_path,
            "from main import app\n"
            "from zeython import Schedule\n\n"
            "schedule = app.container.make(Schedule)\n\n"
            "async def send_report() -> None:\n"
            "    pass\n\n"
            "schedule.call(send_report).daily_at('09:00')\n",
        )
    )

    result = runner.invoke(cli_app, ["schedule", "list"])

    assert result.exit_code == 0
    assert "send_report" in result.stdout
    assert "0 9 * * *" in result.stdout


def test_schedule_run_runs_a_due_task_and_reports_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    marker = tmp_path / "ran.txt"
    monkeypatch.chdir(
        _project_with_schedule(
            tmp_path,
            "from pathlib import Path\n"
            "from main import app\n"
            "from zeython import Schedule\n\n"
            "schedule = app.container.make(Schedule)\n\n"
            "async def write_marker() -> None:\n"
            f"    Path({str(marker)!r}).write_text('ran')\n\n"
            "schedule.call(write_marker).every_minute()\n",
        )
    )

    result = runner.invoke(cli_app, ["schedule", "run"])

    assert result.exit_code == 0
    assert "Ran 1 due event(s): write_marker" in result.stdout
    assert marker.read_text() == "ran"


def test_schedule_run_reports_nothing_when_no_task_is_due(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(
        _project_with_schedule(
            tmp_path,
            "from main import app\n"
            "from zeython import Schedule\n\n"
            "schedule = app.container.make(Schedule)\n\n"
            "async def never_runs() -> None:\n"
            "    pass\n\n"
            # Impossible day-of-month -- never due.
            "schedule.call(never_runs).cron('0 0 31 2 *')\n",
        )
    )

    result = runner.invoke(cli_app, ["schedule", "run"])

    assert result.exit_code == 0
    assert result.stdout.strip() == ""


def test_schedule_run_without_overlapping_needs_a_shared_rate_limiter_to_do_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression/documentation test for a real finding from E2E testing:
    # `zeython schedule run` is a fresh process on every invocation (that's
    # the whole design -- cron/a sidecar loop shell out to it repeatedly),
    # so without_overlapping()'s default InMemoryRateLimiter -- whose lock
    # lives in that one process's memory -- can never see a lock set by an
    # *earlier* invocation. Confirms the counter increments on every call.
    counter = tmp_path / "counter.txt"
    monkeypatch.chdir(
        _project_with_schedule(
            tmp_path,
            "from pathlib import Path\n"
            "from main import app\n"
            "from zeython import Schedule\n\n"
            "schedule = app.container.make(Schedule)\n\n"
            "async def bump() -> None:\n"
            f"    counter = Path({str(counter)!r})\n"
            "    n = int(counter.read_text()) if counter.exists() else 0\n"
            "    counter.write_text(str(n + 1))\n\n"
            "schedule.call(bump, name='bump').every_minute().without_overlapping(for_seconds=3600)\n",
        )
    )

    runner.invoke(cli_app, ["schedule", "run"])
    _simulate_a_fresh_process()
    runner.invoke(cli_app, ["schedule", "run"])

    assert counter.read_text() == "2"  # not "1" -- without_overlapping() had no effect


def test_schedule_run_without_overlapping_works_across_invocations_with_redis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The fix for the above: bind RedisRateLimiter (a real shared backend,
    # not process memory) and without_overlapping() actually blocks the
    # second invocation's run.
    pytest.importorskip("redis")
    import os

    redis_url = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
    counter = tmp_path / "counter.txt"
    (tmp_path / ".env").write_text("APP_SECRET_KEY=test\n")
    (tmp_path / "main.py").write_text(
        "from zeython import Application, RateLimiter, RedisRateLimiter, ScheduleServiceProvider\n\n"
        "app = Application()\n"
        f"app.container.singleton(RateLimiter, lambda: RedisRateLimiter({redis_url!r}, prefix='zeython-test:sched-lock:'))\n"
        "app.register(ScheduleServiceProvider(app))\n"
    )
    (tmp_path / "schedule.py").write_text(
        "from pathlib import Path\n"
        "from main import app\n"
        "from zeython import Schedule\n\n"
        "schedule = app.container.make(Schedule)\n\n"
        "async def bump() -> None:\n"
        f"    counter = Path({str(counter)!r})\n"
        "    n = int(counter.read_text()) if counter.exists() else 0\n"
        "    counter.write_text(str(n + 1))\n\n"
        "schedule.call(bump, name='bump').every_minute().without_overlapping(for_seconds=3600)\n"
    )
    monkeypatch.chdir(tmp_path)

    from redis.asyncio import Redis

    async def _clear_lock() -> None:
        client = Redis.from_url(redis_url)
        await client.delete("zeython-test:sched-lock:zeython:schedule:lock:bump")
        await client.aclose()

    import asyncio as _asyncio

    _asyncio.run(_clear_lock())

    runner.invoke(cli_app, ["schedule", "run"])
    _simulate_a_fresh_process()
    runner.invoke(cli_app, ["schedule", "run"])

    assert counter.read_text() == "1"  # the second invocation was blocked by the shared lock

    _asyncio.run(_clear_lock())


# -- main() -------------------------------------------------------------------------------


def test_main_delegates_to_the_typer_app(monkeypatch: pytest.MonkeyPatch) -> None:
    import zeython.cli.main as cli_main_module

    calls = []
    monkeypatch.setattr(cli_main_module, "app", lambda: calls.append(True))

    cli_main_module.main()

    assert calls == [True]

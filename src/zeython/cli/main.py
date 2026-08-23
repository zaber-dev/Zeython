"""The `zeython` command-line interface."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import typer

from zeython.cli import scaffold
from zeython.cli.loader import load_app

app = typer.Typer(
    name="zeython",
    help="Zeython: an async-first, batteries-included MVC framework for Python.",
    no_args_is_help=True,
)
make_app = typer.Typer(help="Generate application building blocks.", no_args_is_help=True)
db_app = typer.Typer(help="Database migration and seeding commands.", no_args_is_help=True)
queue_app = typer.Typer(help="Background job queue commands.", no_args_is_help=True)
schedule_app = typer.Typer(help="Scheduled/recurring task commands.", no_args_is_help=True)
app.add_typer(make_app, name="make")
app.add_typer(db_app, name="db")
app.add_typer(queue_app, name="queue")
app.add_typer(schedule_app, name="schedule")


@app.command()
def new(
    name: str = typer.Argument(..., help="Project name, e.g. 'My Blog'"),
    path: str | None = typer.Option(None, "--path", help="Target directory (defaults to a slug of the name)"),
) -> None:
    """Scaffold a new Zeython project."""
    destination = Path(path) if path else Path.cwd() / (scaffold.to_snake_case(name) or "app")
    try:
        scaffold.new_project(name, destination)
    except FileExistsError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.secho(f"Created new Zeython project at {destination}", fg=typer.colors.GREEN)
    typer.echo("\nNext steps:")
    typer.echo(f"  cd {destination}")
    typer.echo("  python -m venv .venv && source .venv/bin/activate")
    typer.echo("  pip install -e .")
    typer.echo("  cp .env.example .env")
    typer.echo("  zeython serve")


@app.command()
def serve(
    app_import: str = typer.Option("main:app", "--app", help="Import path to the ASGI app"),
    host: str | None = typer.Option(None, help="Defaults to APP_HOST from .env"),
    port: int | None = typer.Option(None, help="Defaults to APP_PORT from .env"),
    reload: bool | None = typer.Option(None, help="Defaults to APP_DEBUG from .env"),
) -> None:
    """Run the development server with uvicorn."""
    import uvicorn

    from zeython.config import Config

    config = Config.load()
    uvicorn.run(
        app_import,
        host=host or config.host,
        port=port or config.port,
        reload=reload if reload is not None else config.debug,
    )


@app.command()
def down(
    message: str = typer.Option("Be right back.", "--message", "-m", help="Message shown to visitors"),
    retry: int | None = typer.Option(None, "--retry", help="Retry-After header, in seconds"),
    allow: list[str] | None = typer.Option(None, "--allow", help="IP address to still allow through (repeatable)"),
    secret: str | None = typer.Option(None, "--secret", help="Bypass token; auto-generated if omitted"),
) -> None:
    """Put the application into maintenance mode -- every request gets a 503
    until `zeython up`. Requires MaintenanceModeServiceProvider to be
    registered (see docs/maintenance-mode.md). Run from a project root."""
    from zeython.config import Config
    from zeython.maintenance import enable_maintenance_mode, maintenance_store_path

    allowed_ips = list(allow or [])
    config = Config.load(Path.cwd())
    store_path = maintenance_store_path(Path.cwd(), config.get("maintenance.store_path"))
    actual_secret = enable_maintenance_mode(
        store_path, message=message, retry=retry, allowed_ips=allowed_ips, secret=secret
    )

    typer.secho("Application is now in maintenance mode.", fg=typer.colors.YELLOW)
    typer.echo(f"  Bypass URL: /{actual_secret}  (visiting it once sets a cookie for this browser)")
    if allowed_ips:
        typer.echo(f"  Allowed IPs: {', '.join(allowed_ips)}")


@app.command()
def up() -> None:
    """Bring the application out of maintenance mode."""
    from zeython.config import Config
    from zeython.maintenance import disable_maintenance_mode, maintenance_store_path

    config = Config.load(Path.cwd())
    store_path = maintenance_store_path(Path.cwd(), config.get("maintenance.store_path"))
    if disable_maintenance_mode(store_path):
        typer.secho("Application is now live.", fg=typer.colors.GREEN)
    else:
        typer.echo("Application was not in maintenance mode.")


@app.command()
def mcp() -> None:
    """Start the MCP server (stdio) for AI coding agents. Requires the `mcp` extra -- see docs/ai-agents.md."""
    try:
        from zeython.mcp.server import main as run_mcp_server
    except ImportError as exc:
        typer.secho(
            "The MCP server requires the `mcp` extra. Install it with: pip install zeython[mcp]",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1) from exc

    run_mcp_server()


@make_app.command("model")
def make_model(name: str = typer.Argument(..., help="Model name, e.g. Post")) -> None:
    """Generate a new database model in app/Models/."""
    path = scaffold.make_model(name, Path.cwd())
    typer.secho(f"Created {path}", fg=typer.colors.GREEN)


@make_app.command("controller")
def make_controller(name: str = typer.Argument(..., help="Controller name, e.g. Post or PostController")) -> None:
    """Generate a new controller in app/Controllers/."""
    path = scaffold.make_controller(name, Path.cwd())
    typer.secho(f"Created {path}", fg=typer.colors.GREEN)


@make_app.command("middleware")
def make_middleware(name: str = typer.Argument(..., help="Middleware name, e.g. RequestLogger")) -> None:
    """Generate a new ASGI middleware class in app/Middleware/."""
    path = scaffold.make_middleware(name, Path.cwd())
    typer.secho(f"Created {path}", fg=typer.colors.GREEN)


@make_app.command("provider")
def make_provider(name: str = typer.Argument(..., help="Service provider name, e.g. Payment")) -> None:
    """Generate a new service provider in app/Providers/."""
    path = scaffold.make_provider(name, Path.cwd())
    typer.secho(f"Created {path}", fg=typer.colors.GREEN)


@make_app.command("job")
def make_job(name: str = typer.Argument(..., help="Job name, e.g. SendWelcomeEmail")) -> None:
    """Generate a new background job in app/Jobs/."""
    path = scaffold.make_job(name, Path.cwd())
    typer.secho(f"Created {path}", fg=typer.colors.GREEN)


@make_app.command("command")
def make_command(name: str = typer.Argument(..., help="Command name, e.g. PruneOldPosts")) -> None:
    """Generate a new custom CLI command in app/Console/Commands/."""
    path = scaffold.make_command(name, Path.cwd())
    typer.secho(f"Created {path}", fg=typer.colors.GREEN)


@make_app.command("factory")
def make_factory(name: str = typer.Argument(..., help="Model name, e.g. Post or PostFactory")) -> None:
    """Generate a new model factory in database/factories/."""
    path = scaffold.make_factory(name, Path.cwd())
    typer.secho(f"Created {path}", fg=typer.colors.GREEN)


@make_app.command("seeder")
def make_seeder(name: str = typer.Argument(..., help="Seeder name, e.g. User or UserSeeder")) -> None:
    """Generate a new database seeder in database/seeders/."""
    path = scaffold.make_seeder(name, Path.cwd())
    typer.secho(f"Created {path}", fg=typer.colors.GREEN)


@make_app.command("policy")
def make_policy(name: str = typer.Argument(..., help="Model name, e.g. Post or PostPolicy")) -> None:
    """Generate a new authorization policy in app/Policies/."""
    path = scaffold.make_policy(name, Path.cwd())
    typer.secho(f"Created {path}", fg=typer.colors.GREEN)


@make_app.command("notification")
def make_notification(
    name: str = typer.Argument(..., help="Notification name, e.g. InvoicePaid or InvoicePaidNotification"),
) -> None:
    """Generate a new notification in app/Notifications/."""
    path = scaffold.make_notification(name, Path.cwd())
    typer.secho(f"Created {path}", fg=typer.colors.GREEN)


@app.command()
def routes() -> None:
    """List every HTTP route registered in the current project."""
    # zeython.mcp.introspect has no dependency on the `mcp` extra itself
    # (only zeython.mcp.server does, for the MCP protocol layer) -- reusing
    # it here means route listing reflects exactly what the MCP server's
    # list_routes tool would report, from one implementation.
    from zeython.mcp import introspect

    application = introspect.load_app(Path.cwd())
    discovered = introspect.describe_routes(application)
    if not discovered:
        typer.echo("No routes registered.")
        return

    for route in discovered:
        methods = route["methods"] or "WS"
        name = f"  ({route['name']})" if route["name"] else ""
        typer.echo(f"  {methods:<20} {route['path']}{name}")


@app.command()
def features() -> None:
    """List every registered feature flag and its current global resolution
    (context=None -- a per-user flag may still resolve differently for a
    real user). See docs/feature-flags.md."""
    from zeython.feature_flags import FeatureManager
    from zeython.mcp import introspect

    application = introspect.load_app(Path.cwd())
    # Flags are defined in a FeatureServiceProvider subclass's boot() (the
    # same pattern AppEventServiceProvider uses), not register() -- and
    # boot() only runs lazily, on the app's first real request otherwise.
    # load_app() alone (what `routes`/`about` get away without) isn't
    # enough here.
    application.boot()
    if not application.container.has(FeatureManager):
        typer.echo("No FeatureServiceProvider registered.")
        return

    manager = application.container.make(FeatureManager)
    names = manager.names()
    if not names:
        typer.echo("No feature flags defined.")
        return

    for name in names:
        active = asyncio.run(manager.active(name))
        typer.echo(f"  {name:<30} {'ON' if active else 'off'}")


@app.command()
def tinker() -> None:
    """Interactive REPL with the application, its models, and a database
    session already loaded -- mirrors Laravel's `artisan tinker`.

    Every Model subclass in app/Models/ is available by name. Wrap an
    async call in `run(...)` to execute it, e.g. `run(Post.all())` or
    `run(Post.create(title="Hi"))` -- each one commits immediately on
    success (and rolls back on an exception), same as a real request.
    """
    import code
    from typing import Any

    from zeython.db import Database
    from zeython.db.session import _current_session

    project_root = Path.cwd()
    application = load_app(project_root)
    database = application.container.make(Database)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # A plain `async with database.session():` won't do here: it sets
    # `_current_session` from *inside* the coroutine that `run_until_complete`
    # wraps in a Task, and a Task's context is a private copy taken at
    # creation time -- a set() inside one Task is invisible to the next.
    # Setting it here instead, synchronously in this REPL's own (non-Task)
    # context, means every subsequent run_until_complete() call copies a
    # context that already has it, since each Task's copy is taken fresh
    # from this frame at the moment it's created.
    session = database.session_factory()
    token = _current_session.set(session)

    def run(coro: Any) -> Any:
        """Run an async expression against this REPL's database session,
        committing on success or rolling back on an exception."""
        try:
            result = loop.run_until_complete(coro)
        except Exception:
            loop.run_until_complete(session.rollback())
            raise
        loop.run_until_complete(session.commit())
        return result

    models = _discover_models(project_root)
    namespace: dict[str, Any] = {
        "app": application,
        "container": application.container,
        "config": application.config,
        "run": run,
        **models,
    }

    banner = f"Zeython tinker -- {project_root.name}\nWrap async calls in run(...), e.g. run(Post.all())."
    if models:
        banner += "\nModels: " + ", ".join(sorted(models))

    try:
        code.interact(banner=banner, local=namespace, exitmsg="")
    finally:
        _current_session.reset(token)
        loop.run_until_complete(session.close())
        loop.run_until_complete(database.dispose())
        loop.close()


def _discover_models(project_root: Path) -> dict[str, type]:
    """Every :class:`~zeython.db.Model` subclass in ``app/Models/*.py``, keyed by class name."""
    import importlib
    import inspect

    from zeython.db import Model

    models_dir = project_root / "app" / "Models"
    models: dict[str, type] = {}
    if not models_dir.is_dir():
        return models

    root_str = str(project_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    for path in sorted(models_dir.glob("*.py")):
        if path.stem == "__init__":
            continue
        module = importlib.import_module(f"app.Models.{path.stem}")
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if obj is Model or not issubclass(obj, Model):
                continue
            if obj.__module__ != module.__name__:
                continue  # e.g. `from zeython import Model` itself, not a real model
            models[name] = obj
    return models


@app.command()
def about() -> None:
    """Show basic info about the current project: app name, environment, debug flag,
    installed Zeython version, and registered service providers."""
    from zeython.mcp import introspect

    application = introspect.load_app(Path.cwd())
    info = introspect.describe_app(application)

    typer.echo(f"  App name ........ {info['app_name']}")
    typer.echo(f"  Environment ...... {info['environment']}")
    typer.echo(f"  Debug ............ {info['debug']}")
    typer.echo(f"  Zeython version .. {info['zeython_version']}")
    typer.echo("  Providers:")
    for provider_name in info["providers"]:
        typer.echo(f"    - {provider_name}")


@app.command(name="commands")
def list_commands() -> None:
    """List custom commands defined in app/Console/Commands/."""
    from zeython.console import discover_commands

    discovered = discover_commands(Path.cwd())
    if not discovered:
        typer.echo("No custom commands found in app/Console/Commands/.")
        return

    for name in sorted(discovered):
        help_text = discovered[name].help
        typer.echo(f"  {name}" + (f"  -  {help_text}" if help_text else ""))


@app.command(
    name="command",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run_command(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Custom command name -- see: zeython commands"),
) -> None:
    """Run a custom command defined in app/Console/Commands/."""
    from zeython.console import discover_commands

    project_root = Path.cwd()
    discovered = discover_commands(project_root)
    command_cls = discovered.get(name)
    if command_cls is None:
        available = ", ".join(sorted(discovered)) or "(none found -- see app/Console/Commands/)"
        typer.secho(f"Unknown command '{name}'. Available: {available}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    application = load_app(project_root)
    command_instance = command_cls(application)
    asyncio.run(command_instance.handle(*ctx.args))


def _run_alembic(*args: str) -> None:
    if not (Path.cwd() / "alembic.ini").exists():
        typer.secho(
            "No alembic.ini found in the current directory. Run this from a Zeython project root.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=Path.cwd())
    raise typer.Exit(code=result.returncode)


@db_app.command("migrate")
def db_migrate() -> None:
    """Apply all pending migrations (alembic upgrade head)."""
    _run_alembic("upgrade", "head")


@db_app.command("revision")
def db_revision(message: str = typer.Option(..., "-m", "--message", help="Migration message")) -> None:
    """Autogenerate a new migration from model changes."""
    _run_alembic("revision", "--autogenerate", "-m", message)


@db_app.command("downgrade")
def db_downgrade(revision: str = typer.Argument("-1", help="Target revision, defaults to one step back")) -> None:
    """Revert the most recent migration(s)."""
    _run_alembic("downgrade", revision)


@db_app.command("seed")
def db_seed(
    seeder_class: str = typer.Option(
        "DatabaseSeeder", "--class", help="Seeder class to run -- see: database/seeders/"
    ),
) -> None:
    """Run a database seeder (DatabaseSeeder by default)."""
    from zeython.database.seeder import discover_seeders
    from zeython.db import Database

    project_root = Path.cwd()
    discovered = discover_seeders(project_root)
    seeder_cls = discovered.get(seeder_class)
    if seeder_cls is None:
        available = ", ".join(sorted(discovered)) or "(none found -- see database/seeders/)"
        typer.secho(f"Unknown seeder '{seeder_class}'. Available: {available}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    application = load_app(project_root)

    async def _seed() -> None:
        database = application.container.make(Database)
        try:
            async with database.session():
                await seeder_cls(application).run()
        finally:
            # A one-shot CLI process exits right after this anyway, but
            # disposing explicitly avoids leaving an open aiosqlite
            # connection (and its background thread) for the process to
            # clean up on its way out.
            await database.dispose()

    asyncio.run(_seed())
    typer.secho(f"Seeded using {seeder_class}.", fg=typer.colors.GREEN)


@queue_app.command("work")
def queue_work() -> None:
    """Run a worker that processes jobs from a durable queue (QUEUE_DRIVER=redis).

    The default in-memory queue already runs its own background worker
    inside your app's own process -- this command is for RedisQueue, whose
    whole point is a separate, restartable process. See docs/queues.md.
    """
    from zeython.queue import Queue, RedisQueue

    project_root = Path.cwd()
    application = load_app(project_root)
    queue = application.container.make(Queue)

    if not isinstance(queue, RedisQueue):
        typer.secho(
            "zeython queue work requires QUEUE_DRIVER=redis in .env -- the default in-memory "
            "queue already runs its own background worker inside your app process, and has "
            "nothing for a separate worker process to pull from. See docs/queues.md.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    typer.secho(f"Working queue '{queue.queue_name}'... (Ctrl+C to stop)", fg=typer.colors.GREEN)
    try:
        asyncio.run(queue.run_worker())
    except KeyboardInterrupt:
        typer.echo("Stopped.")


@schedule_app.command("run")
def schedule_run() -> None:
    """Run every scheduled task that's due this minute.

    Meant to be invoked once a minute, by a single cron entry (or sidecar
    loop container) -- not run continuously itself. See docs/scheduling.md.
    """
    from zeython.schedule import Schedule

    project_root = Path.cwd()
    application = load_app(project_root)
    schedule = application.container.make(Schedule)

    due = asyncio.run(schedule.run_due())
    if due:
        typer.secho(f"Ran {len(due)} due event(s): {', '.join(event.name for event in due)}", fg=typer.colors.GREEN)


@schedule_app.command("list")
def schedule_list() -> None:
    """List every registered scheduled task and its cron expression."""
    from zeython.schedule import Schedule

    project_root = Path.cwd()
    application = load_app(project_root)
    schedule = application.container.make(Schedule)

    if len(schedule) == 0:
        typer.echo(
            "No scheduled tasks registered. Define one in schedule.py and register "
            "ScheduleServiceProvider in main.py -- see docs/scheduling.md."
        )
        return

    for event in schedule:
        typer.echo(f"  {event.name:<30}  {event.cron_expression}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()

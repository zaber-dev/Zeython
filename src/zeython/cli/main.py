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
app.add_typer(make_app, name="make")
app.add_typer(db_app, name="db")
app.add_typer(queue_app, name="queue")


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


def main() -> None:
    app()


if __name__ == "__main__":
    main()

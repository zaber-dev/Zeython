"""Code-generation helpers backing `zeython new` and `zeython make:*`."""

from __future__ import annotations

import keyword
import re
import secrets
from pathlib import Path

_TEMPLATES_DIR = Path(__file__).parent / "templates" / "starter"
_TOKEN_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def to_snake_case(name: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", name)
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s)
    return s.strip("_").lower()


def to_pascal_case(name: str) -> str:
    parts = re.split(r"[^0-9a-zA-Z]+", name)
    return "".join(part[:1].upper() + part[1:] for part in parts if part)


def _require_identifier(name: str, *, what: str) -> str:
    """Raise ``ValueError`` unless ``name`` is a real, non-keyword Python identifier.

    Every ``make_*`` generator below embeds a name derived from user input
    (via :func:`to_pascal_case`/:func:`to_snake_case`) directly into
    generated source -- a class name, a parameter name, or a module-path
    segment in an import line. Neither helper rejects input that doesn't
    survive as a valid identifier: a name with no letters at all (e.g.
    ``"???"``) collapses to an empty string, and one that's *only* digits
    (e.g. ``"123"``) survives unchanged, both syntactically invalid as a
    Python name. Without this check, ``make_model`` in particular doesn't
    just write one broken file -- it also appends the same invalid name
    to the shared ``app/Models/__init__.py``, breaking every model import
    in the project, not only the new one.
    """
    if not name.isidentifier() or keyword.iskeyword(name):
        raise ValueError(
            f"'{name}' is not usable as a Python {what} -- it must start with a letter or "
            "underscore and contain only letters, digits, and underscores, and can't be a "
            "reserved keyword. Try a different name."
        )
    return name


def _render(text: str, context: dict[str, str]) -> str:
    return _TOKEN_RE.sub(lambda m: context.get(m.group(1), m.group(0)), text)


def new_project(name: str, destination: Path) -> Path:
    """Copy the starter template to ``destination``, rendering placeholders."""
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"{destination} already exists and is not empty")

    context = {
        "project_name": name,
        "project_slug": to_snake_case(name) or "app",
        "secret_key": secrets.token_hex(32),
    }

    destination.mkdir(parents=True, exist_ok=True)

    for source_path in _TEMPLATES_DIR.rglob("*"):
        if "__pycache__" in source_path.parts:
            # `pip install` bytecode-compiles every .py file it installs, including
            # these template sources, leaving .pyc caches alongside them. Skip them.
            continue

        relative = source_path.relative_to(_TEMPLATES_DIR)
        target_path = destination / relative

        if source_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
            continue

        target_path.parent.mkdir(parents=True, exist_ok=True)
        content = source_path.read_text()
        target_path.write_text(_render(content, context))

    return destination


MODEL_TEMPLATE = '''from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from zeython import Model


class {class_name}(Model):
    __tablename__ = "{table_name}"

    name: Mapped[str] = mapped_column(String(255))
'''

CONTROLLER_TEMPLATE = '''from starlette.responses import JSONResponse

from zeython import Controller


class {class_name}(Controller):
    async def index(self, request):
        return JSONResponse({{"message": "{class_name} works!"}})
'''

MIDDLEWARE_TEMPLATE = '''class {class_name}:
    """ASGI middleware."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        await self.app(scope, receive, send)
'''

PROVIDER_TEMPLATE = '''from zeython import ServiceProvider


class {class_name}(ServiceProvider):
    def register(self) -> None:
        """Bind services into the container."""

    def boot(self) -> None:
        """Run once every provider has registered."""
'''

JOB_TEMPLATE = '''from dataclasses import dataclass

from zeython import Job


@dataclass
class {class_name}(Job):
    async def handle(self) -> None:
        """Do the background work. Dispatch with: await dispatch(request, {class_name}(...))"""
'''

COMMAND_TEMPLATE = '''from zeython import Command


class {class_name}(Command):
    """Run with: zeython command {command_name}"""

    help = "TODO: describe what this command does."

    async def handle(self, *args: str) -> None:
        ...
'''


FACTORY_TEMPLATE = '''from zeython import Factory

from app.Models.{model_slug} import {model_class_name}


class {class_name}(Factory[{model_class_name}]):
    model = {model_class_name}

    def definition(self, sequence: int) -> dict:
        return {{
            # TODO: default attributes for {model_class_name}, e.g.:
            # "name": f"{model_class_name} {{sequence}}",
        }}
'''

SEEDER_TEMPLATE = '''from zeython import Seeder


class {class_name}(Seeder):
    async def run(self) -> None:
        ...
'''

NOTIFICATION_TEMPLATE = '''from typing import Any

from zeython import Notification


class {class_name}(Notification):
    """Dispatch with: await notify(request, some_user, {class_name}(...))

    See docs/notifications.md.
    """

    def via(self, notifiable: Any) -> list[str]:
        return ["database"]

    # def to_mail(self, notifiable: Any):
    #     from zeython import Message
    #     return Message(to=notifiable.email, subject="TODO", body="TODO")

    def to_database(self, notifiable: Any) -> dict:
        return {{
            # TODO: whatever this notification's UI needs to render it.
        }}
'''

POLICY_TEMPLATE = '''class {class_name}:
    """Authorization policy for {model_class_name}.

    Register it against the model in a service provider's ``boot()``:
    ``gate.policy({model_class_name}, {class_name})``. See docs/authorization.md.
    """

    def view(self, user, {model_var}) -> bool:
        return True

    def create(self, user) -> bool:
        return True

    def update(self, user, {model_var}) -> bool:
        return False

    def delete(self, user, {model_var}) -> bool:
        return False
'''


def _write_new_file(path: Path, content: str) -> None:
    if path.exists():
        raise FileExistsError(f"{path} already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def make_model(name: str, cwd: Path) -> Path:
    class_name = _require_identifier(to_pascal_case(name), what="class name")
    slug = _require_identifier(to_snake_case(name), what="module name")
    path = cwd / "app" / "Models" / f"{slug}.py"
    _write_new_file(path, MODEL_TEMPLATE.format(class_name=class_name, table_name=f"{slug}s"))

    init_file = cwd / "app" / "Models" / "__init__.py"
    if init_file.exists():
        import_line = f"from app.Models.{slug} import {class_name}  # noqa: F401"
        existing = init_file.read_text()
        if import_line not in existing:
            separator = "" if existing.endswith("\n\n") else "\n" if existing.endswith("\n") else "\n\n"
            init_file.write_text(f"{existing}{separator}{import_line}\n")

    return path


def make_controller(name: str, cwd: Path) -> Path:
    if not name.endswith("Controller"):
        name = f"{name}Controller"
    class_name = _require_identifier(to_pascal_case(name), what="class name")
    slug = to_snake_case(name)
    path = cwd / "app" / "Controllers" / f"{slug}.py"
    _write_new_file(path, CONTROLLER_TEMPLATE.format(class_name=class_name))
    return path


def make_middleware(name: str, cwd: Path) -> Path:
    class_name = _require_identifier(to_pascal_case(name), what="class name")
    slug = to_snake_case(name)
    path = cwd / "app" / "Middleware" / f"{slug}.py"
    _write_new_file(path, MIDDLEWARE_TEMPLATE.format(class_name=class_name))
    return path


def make_provider(name: str, cwd: Path) -> Path:
    if not name.endswith("ServiceProvider") and not name.endswith("Provider"):
        name = f"{name}ServiceProvider"
    class_name = _require_identifier(to_pascal_case(name), what="class name")
    slug = to_snake_case(name)
    path = cwd / "app" / "Providers" / f"{slug}.py"
    _write_new_file(path, PROVIDER_TEMPLATE.format(class_name=class_name))
    return path


def make_job(name: str, cwd: Path) -> Path:
    if not name.endswith("Job"):
        name = f"{name}Job"
    class_name = _require_identifier(to_pascal_case(name), what="class name")
    slug = to_snake_case(name)
    path = cwd / "app" / "Jobs" / f"{slug}.py"
    _write_new_file(path, JOB_TEMPLATE.format(class_name=class_name))
    return path


def make_command(name: str, cwd: Path) -> Path:
    if not name.endswith("Command"):
        name = f"{name}Command"
    class_name = _require_identifier(to_pascal_case(name), what="class name")
    slug = to_snake_case(name)
    command_name = slug.removesuffix("_command").replace("_", "-")
    path = cwd / "app" / "Console" / "Commands" / f"{slug}.py"
    _write_new_file(path, COMMAND_TEMPLATE.format(class_name=class_name, command_name=command_name))
    return path


def make_factory(name: str, cwd: Path) -> Path:
    if not name.endswith("Factory"):
        name = f"{name}Factory"
    class_name = _require_identifier(to_pascal_case(name), what="class name")
    model_class_name = _require_identifier(class_name.removesuffix("Factory"), what="model class name")
    model_slug = _require_identifier(to_snake_case(model_class_name), what="model module name")
    slug = to_snake_case(name)
    path = cwd / "database" / "factories" / f"{slug}.py"
    _write_new_file(
        path,
        FACTORY_TEMPLATE.format(class_name=class_name, model_class_name=model_class_name, model_slug=model_slug),
    )
    return path


def make_seeder(name: str, cwd: Path) -> Path:
    if not name.endswith("Seeder"):
        name = f"{name}Seeder"
    class_name = _require_identifier(to_pascal_case(name), what="class name")
    slug = to_snake_case(name)
    path = cwd / "database" / "seeders" / f"{slug}.py"
    _write_new_file(path, SEEDER_TEMPLATE.format(class_name=class_name))
    return path


def make_policy(name: str, cwd: Path) -> Path:
    if not name.endswith("Policy"):
        name = f"{name}Policy"
    class_name = _require_identifier(to_pascal_case(name), what="class name")
    model_class_name = _require_identifier(class_name.removesuffix("Policy"), what="model class name")
    model_var = _require_identifier(to_snake_case(model_class_name), what="parameter name")
    slug = to_snake_case(name)
    path = cwd / "app" / "Policies" / f"{slug}.py"
    _write_new_file(
        path,
        POLICY_TEMPLATE.format(class_name=class_name, model_class_name=model_class_name, model_var=model_var),
    )
    return path


def make_notification(name: str, cwd: Path) -> Path:
    if not name.endswith("Notification"):
        name = f"{name}Notification"
    class_name = _require_identifier(to_pascal_case(name), what="class name")
    slug = to_snake_case(name)
    path = cwd / "app" / "Notifications" / f"{slug}.py"
    _write_new_file(path, NOTIFICATION_TEMPLATE.format(class_name=class_name))
    return path

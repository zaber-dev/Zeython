"""An auto-generated CRUD admin UI for registered models.

Register a model and get list/create/edit/delete pages for it, generated
from the model's own columns -- no hand-written admin templates, the same
trade-off Django's admin makes. This is a lightweight v1, not a Django-admin
clone: no relationship pickers (a foreign key column is a plain number
input, you type the related row's ID), no search/filtering, no bulk
actions. It's for internal, trusted-staff CRUD over your own models, not a
public-facing UI -- see "What this isn't" below.

Every admin route requires a logged-in user (:func:`~zeython.auth.require_auth`)
*and* an explicit ``guard`` callable you provide -- there is deliberately
no default that lets any authenticated user in. Forcing that choice is the
same reasoning as :class:`~zeython.security_headers.SecurityHeadersServiceProvider`
having no default CSP: guessing a policy for you would be worse than
requiring you to state one.

Pages are plain server-rendered HTML with a small inline script that turns
a form submission into a ``fetch`` carrying the CSRF header
(:mod:`zeython.csrf` reads the token from a header, not a form field --
see docs/csrf.md), not a second Jinja template system -- the admin UI
works whether or not :class:`~zeython.views.ViewServiceProvider` is even
registered.
"""

from __future__ import annotations

import html
import json
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote

from sqlalchemy import Boolean, DateTime, Float, Integer, inspect
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from zeython.auth import require_auth
from zeython.csrf import csrf_token
from zeython.db import Model
from zeython.exceptions import ForbiddenException, NotFoundException, ValidationException
from zeython.providers import ServiceProvider

if TYPE_CHECKING:
    from zeython.application import Application

Guard = Callable[[Any], "bool | Awaitable[bool]"]

#: Columns every Model subclass inherits -- never editable through the
#: generated form (id is server-assigned, the timestamps and soft-delete
#: fields are managed by Model itself).
_BASE_MODEL_FIELDS = frozenset({"id", "created_at", "updated_at", "is_deleted", "deleted_at"})

__all__ = ["AdminServiceProvider"]


def _editable_columns(model: type[Model]) -> list[Any]:
    mapper = inspect(model)
    hidden = set(getattr(model, "__hidden__", ()))
    return [c for c in mapper.columns if c.name not in _BASE_MODEL_FIELDS and c.name not in hidden]


def _list_columns(model: type[Model]) -> list[Any]:
    mapper = inspect(model)
    hidden = set(getattr(model, "__hidden__", ()))
    return [c for c in mapper.columns if c.name not in hidden]


def _input_type(column_type: Any) -> str:
    if isinstance(column_type, Boolean):
        return "checkbox"
    if isinstance(column_type, DateTime):
        return "datetime-local"
    if isinstance(column_type, (Integer, Float)):
        return "number"
    return "text"


def _to_input_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M")
    return str(value)


def _parse_form_value(column_type: Any, raw: Any) -> Any:
    if isinstance(column_type, Boolean):
        return raw is not None  # a checkbox is absent from form data entirely when unchecked
    if raw is None or raw == "":
        return None
    if isinstance(column_type, Integer):
        return int(raw)
    if isinstance(column_type, Float):
        return float(raw)
    if isinstance(column_type, DateTime):
        return datetime.fromisoformat(raw)
    return raw


def _parse_attributes(model: type[Model], form: Any) -> dict[str, Any]:
    """Parse ``form`` into constructor/update kwargs for ``model``'s editable
    columns.

    Raises :class:`~zeython.exceptions.ValidationException` (422, folded
    into the same redirect-with-errors flow a model validation failure
    already takes) for any column whose submitted value doesn't parse as
    its column type -- a non-numeric string in an Integer/Float column, an
    unparseable datetime -- rather than letting the underlying ``ValueError``
    escape :meth:`_parse_form_value` as an unhandled 500. The generated
    ``<input type="number">``/``type="datetime-local"`` steers a browser
    away from sending that, but the request body is client-controlled data
    regardless (curl, a hand-edited form, a modified request) -- the server
    can't rely on a browser's own input validation to protect it.
    """
    attributes: dict[str, Any] = {}
    errors: dict[str, list[str]] = {}
    for column in _editable_columns(model):
        raw = form.get(column.name)
        try:
            attributes[column.name] = _parse_form_value(column.type, raw)
        except (ValueError, TypeError):
            errors[column.name] = [f"{raw!r} is not a valid value for this field."]
    if errors:
        raise ValidationException(errors)
    return attributes


def _encode_errors(errors: dict[str, list[str]]) -> str:
    return f"errors={quote(json.dumps(errors))}"


def _decode_errors(raw: str | None) -> dict[str, list[str]]:
    if not raw:
        return {}
    try:
        decoded = json.loads(unquote(raw))
        return decoded if isinstance(decoded, dict) else {}
    except (ValueError, TypeError):
        return {}


def _parse_page(raw: str | None) -> int:
    # A hand-edited or stale bookmarked ?page= (non-numeric, negative,
    # zero) shouldn't crash the list view -- Model.paginate() itself
    # raises ValueError for anything under 1, and int() raises its own
    # for anything non-numeric. Falling back to page 1 for either keeps
    # the admin list usable instead of a 500 for a bad query string.
    try:
        page = int(raw) if raw is not None else 1
    except (TypeError, ValueError):
        return 1
    return page if page >= 1 else 1


_STYLE = """
<style>
  body { font-family: system-ui, sans-serif; margin: 0; background: #f8fafc; color: #0f172a; }
  header { background: #0f172a; color: #fff; padding: 1rem 1.5rem; }
  header a { color: #fff; text-decoration: none; font-weight: 600; }
  main { max-width: 960px; margin: 2rem auto; padding: 0 1.5rem; }
  table { width: 100%; border-collapse: collapse; background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,.06); }
  th, td { text-align: left; padding: .6rem .8rem; border-bottom: 1px solid #e2e8f0; font-size: .9rem; }
  th { background: #f1f5f9; }
  a.button, button { display: inline-block; background: #4f46e5; color: #fff; border: none; padding: .5rem .9rem;
    border-radius: 6px; text-decoration: none; font-size: .85rem; cursor: pointer; }
  a.button.secondary, button.secondary { background: #64748b; }
  a.button.danger, button.danger { background: #dc2626; }
  .row-actions { display: flex; gap: .4rem; }
  form.field-form label { display: block; margin: .8rem 0 .3rem; font-size: .85rem; font-weight: 600; }
  form.field-form input[type=text], form.field-form input[type=number], form.field-form input[type=datetime-local] {
    width: 100%; padding: .5rem; border: 1px solid #cbd5e1; border-radius: 6px; box-sizing: border-box; }
  .errors { background: #fef2f2; border: 1px solid #fecaca; color: #991b1b; padding: .75rem 1rem;
    border-radius: 6px; margin-bottom: 1rem; font-size: .85rem; }
  .pager { margin-top: 1rem; display: flex; gap: .5rem; }
  .model-list a { display: block; padding: .6rem 0; border-bottom: 1px solid #e2e8f0; color: #4f46e5; }
</style>
"""

_SUBMIT_SCRIPT = """
<script>
  function zeythonAdminCsrfToken() {
    const match = document.cookie.match(/(?:^|; )csrf_token=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : "";
  }
  document.querySelectorAll("form[data-admin-form]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const response = await fetch(form.action, {
        method: form.dataset.method || "POST",
        headers: { "X-CSRF-Token": zeythonAdminCsrfToken() },
        body: new FormData(form),
      });
      window.location.href = response.url;
    });
  });
</script>
"""


def _layout(prefix: str, title: str, body: str) -> str:
    return f"""<!doctype html>
<html>
<head><meta charset="utf-8" /><title>{html.escape(title)}</title>{_STYLE}</head>
<body>
<header><a href="{html.escape(prefix)}">Admin</a> &rsaquo; {html.escape(title)}</header>
<main>{body}</main>
{_SUBMIT_SCRIPT}
</body>
</html>"""


def _render_dashboard(prefix: str, models: Sequence[type[Model]]) -> str:
    links = "".join(
        f'<a href="{html.escape(prefix)}/{html.escape(model.__tablename__)}">{html.escape(model.__name__)} '
        f"({html.escape(model.__tablename__)})</a>"
        for model in models
    )
    body = f'<div class="model-list">{links or "<p>No models registered.</p>"}</div>'
    return _layout(prefix, "Dashboard", body)


def _render_list(prefix: str, model: type[Model], page: Any) -> str:
    columns = _list_columns(model)
    slug = model.__tablename__
    header = "".join(f"<th>{html.escape(c.name)}</th>" for c in columns) + "<th></th>"
    rows = ""
    for item in page.items:
        cells = "".join(f"<td>{html.escape(_to_input_value(getattr(item, c.name)))}</td>" for c in columns)
        rows += (
            f"<tr>{cells}<td class='row-actions'>"
            f'<a class="button secondary" href="{prefix}/{slug}/{item.id}/edit">Edit</a>'
            f'<form data-admin-form data-method="DELETE" action="{prefix}/{slug}/{item.id}" method="post">'
            f'<button class="danger" type="submit">Delete</button></form>'
            "</td></tr>"
        )
    prev_link = (
        f'<a class="button secondary" href="?page={page.page - 1}">Previous</a>' if page.has_prev else ""
    )
    next_link = f'<a class="button secondary" href="?page={page.page + 1}">Next</a>' if page.has_next else ""
    pager = (
        f'<div class="pager">{prev_link}'
        f"<span>Page {page.page} of {max(page.total_pages, 1)} ({page.total} total)</span>"
        f"{next_link}</div>"
    )
    body = (
        f'<p><a class="button" href="{prefix}/{slug}/new">+ New {html.escape(model.__name__)}</a></p>'
        f"<table><thead><tr>{header}</tr></thead><tbody>{rows}</tbody></table>{pager}"
    )
    return _layout(prefix, model.__name__, body)


def _render_form(
    request: Request, prefix: str, model: type[Model], *, instance: Model | None, errors: dict[str, list[str]]
) -> str:
    slug = model.__tablename__
    is_edit = instance is not None
    action = f"{prefix}/{slug}/{instance.id}" if instance is not None else f"{prefix}/{slug}"
    method = "PUT" if is_edit else "POST"

    error_html = ""
    if errors:
        messages = "".join(f"<li>{html.escape(field)}: {html.escape(', '.join(msgs))}</li>" for field, msgs in errors.items())
        error_html = f'<div class="errors"><ul>{messages}</ul></div>'

    fields_html = ""
    for column in _editable_columns(model):
        current = getattr(instance, column.name) if instance is not None else column.default
        input_type = _input_type(column.type)
        if input_type == "checkbox":
            checked = "checked" if current else ""
            field = f'<input type="checkbox" name="{html.escape(column.name)}" {checked} />'
        else:
            value = html.escape(_to_input_value(current) if not callable(current) else "")
            field = f'<input type="{input_type}" name="{html.escape(column.name)}" value="{value}" />'
        fields_html += f"<label>{html.escape(column.name)}</label>{field}"

    csrf = html.escape(csrf_token(request) or "")
    body = (
        f"{error_html}"
        f'<form class="field-form" data-admin-form data-method="{method}" action="{action}" method="post">'
        f'<input type="hidden" name="csrf_token" value="{csrf}" />'
        f"{fields_html}"
        f'<p><button type="submit">{"Save" if is_edit else "Create"}</button> '
        f'<a class="button secondary" href="{prefix}/{slug}">Cancel</a></p>'
        f"</form>"
    )
    return _layout(prefix, f"{'Edit' if is_edit else 'New'} {model.__name__}", body)


class AdminServiceProvider(ServiceProvider):
    """Registers a CRUD admin UI for ``models`` under ``prefix`` (default ``/admin``).

    ``guard`` is required, not optional -- ``lambda user: getattr(user, "is_admin", False)``
    for a boolean flag on your user model, or anything else that returns
    (or awaits to) a bool. Every admin route also requires a logged-in
    user regardless of ``guard`` -- see :func:`~zeython.auth.require_auth`.

    ::

        from zeython import AdminServiceProvider
        from app.Models.post import Post
        from app.Models.user import User

        app.register(AdminServiceProvider(
            app,
            models=[Post, User],
            guard=lambda user: user.is_admin,
        ))

    See docs/admin.md.
    """

    def __init__(
        self,
        app: Application,
        *,
        models: Sequence[type[Model]],
        guard: Guard,
        prefix: str = "/admin",
    ) -> None:
        super().__init__(app)
        self.models = list(models)
        self.guard = guard
        self.prefix = prefix.rstrip("/") or "/admin"

    def boot(self) -> None:
        by_slug = {model.__tablename__: model for model in self.models}
        prefix = self.prefix
        guard = self.guard

        async def _check_access(request: Request) -> Any:
            user = await require_auth(request)
            allowed = guard(user)
            if hasattr(allowed, "__await__"):
                allowed = await allowed  # type: ignore[assignment]
            if not allowed:
                raise ForbiddenException("Admin access required.")
            return user

        def _model_or_404(slug: str) -> type[Model]:
            model = by_slug.get(slug)
            if model is None:
                raise NotFoundException(f"No admin model registered for '{slug}'.")
            return model

        async def dashboard(request: Request) -> HTMLResponse:
            await _check_access(request)
            return HTMLResponse(_render_dashboard(prefix, self.models))

        async def list_view(request: Request) -> HTMLResponse:
            await _check_access(request)
            model = _model_or_404(request.path_params["model"])
            page_number = _parse_page(request.query_params.get("page"))
            page = await model.paginate(page=page_number, per_page=20)
            return HTMLResponse(_render_list(prefix, model, page))

        async def new_form(request: Request) -> HTMLResponse:
            await _check_access(request)
            model = _model_or_404(request.path_params["model"])
            errors = _decode_errors(request.query_params.get("errors"))
            return HTMLResponse(_render_form(request, prefix, model, instance=None, errors=errors))

        async def create(request: Request) -> Response:
            await _check_access(request)
            model = _model_or_404(request.path_params["model"])
            form = await request.form()
            try:
                attributes = _parse_attributes(model, form)
                await model.create(**attributes)
            except (ValidationException, ValueError) as exc:
                errors = exc.errors if isinstance(exc, ValidationException) else {"__all__": [str(exc)]}
                return RedirectResponse(f"{prefix}/{model.__tablename__}/new?{_encode_errors(errors)}", status_code=303)
            return RedirectResponse(f"{prefix}/{model.__tablename__}", status_code=303)

        async def edit_form(request: Request) -> HTMLResponse:
            await _check_access(request)
            model = _model_or_404(request.path_params["model"])
            instance = await model.find(request.path_params["id"])
            if instance is None:
                raise NotFoundException("Record not found.")
            errors = _decode_errors(request.query_params.get("errors"))
            return HTMLResponse(_render_form(request, prefix, model, instance=instance, errors=errors))

        async def update(request: Request) -> Response:
            await _check_access(request)
            model = _model_or_404(request.path_params["model"])
            instance = await model.find(request.path_params["id"])
            if instance is None:
                raise NotFoundException("Record not found.")
            form = await request.form()
            try:
                attributes = _parse_attributes(model, form)
                await instance.update(**attributes)
            except (ValidationException, ValueError) as exc:
                errors = exc.errors if isinstance(exc, ValidationException) else {"__all__": [str(exc)]}
                return RedirectResponse(
                    f"{prefix}/{model.__tablename__}/{instance.id}/edit?{_encode_errors(errors)}", status_code=303
                )
            return RedirectResponse(f"{prefix}/{model.__tablename__}", status_code=303)

        async def destroy(request: Request) -> Response:
            await _check_access(request)
            model = _model_or_404(request.path_params["model"])
            instance = await model.find(request.path_params["id"])
            if instance is None:
                raise NotFoundException("Record not found.")
            await instance.delete()
            return RedirectResponse(f"{prefix}/{model.__tablename__}", status_code=303)

        self.app.get(prefix, name="admin.dashboard")(dashboard)
        self.app.get(f"{prefix}/{{model}}", name="admin.index")(list_view)
        self.app.get(f"{prefix}/{{model}}/new", name="admin.new")(new_form)
        self.app.post(f"{prefix}/{{model}}", name="admin.store")(create)
        self.app.get(f"{prefix}/{{model}}/{{id:int}}/edit", name="admin.edit")(edit_form)
        self.app.put(f"{prefix}/{{model}}/{{id:int}}", name="admin.update")(update)
        self.app.delete(f"{prefix}/{{model}}/{{id:int}}", name="admin.destroy")(destroy)

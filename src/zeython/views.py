"""Server-rendered HTML views, by convention read from ``resources/views/``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.templating import Jinja2Templates


class Views:
    """Thin wrapper around Starlette's Jinja2 integration.

    Bound into the container by :class:`~zeython.providers.ViewServiceProvider`
    under the ``resources/views`` directory by default. Use the module-level
    :func:`render` helper from inside a controller/handler for Flask-style
    ergonomics.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self._templates = Jinja2Templates(directory=str(self.directory))

    @property
    def environment(self):
        return self._templates.env

    def render(
        self,
        request: Request,
        name: str,
        context: dict[str, Any] | None = None,
        *,
        status_code: int = 200,
    ) -> HTMLResponse:
        return self._templates.TemplateResponse(request, name, context or {}, status_code=status_code)


def render(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    *,
    status_code: int = 200,
) -> HTMLResponse:
    """Render ``name`` using the application's registered :class:`Views` instance.

    Usage inside a controller::

        from zeython.views import render

        async def show(self, request):
            return render(request, "posts/show.html", {"post": post})
    """
    from zeython.container import Container

    container: Container = request.app.state.container
    views = container.make(Views)
    return views.render(request, name, context, status_code=status_code)

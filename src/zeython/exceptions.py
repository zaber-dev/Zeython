"""HTTP-aware exception hierarchy with a default JSON error handler."""

from __future__ import annotations

import html
import linecache
import traceback
from http import HTTPStatus
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from zeython.error_monitoring import report_exception
from zeython.request_id import request_id


class HTTPException(Exception):
    """Base class for exceptions that should be rendered as HTTP responses.

    Only works as intended when ``raise``\\ d from *inside routing* -- a
    route handler, or code it calls. Starlette's own ``ExceptionMiddleware``
    (which owns the per-class handlers :func:`default_exception_handlers`
    registers for this hierarchy) sits *inside* every ``add_middleware()``
    layer, wrapping only the router. Raising an ``HTTPException`` directly
    from a custom pure-ASGI middleware's ``__call__`` -- rather than a
    route handler -- skips that layer entirely: the exception propagates
    to ``ServerErrorMiddleware`` instead (outside everything), which has
    no per-class handler for it, so it's treated as a genuine unhandled
    error -- the intended status code and ``headers=`` are lost, and the
    caller gets a generic 500 instead. Call the handler directly and
    return/send its response instead of raising -- :class:`~zeython.csrf.CsrfMiddleware`
    does exactly this (see its ``__call__``) specifically to avoid this trap.
    """

    status_code: int = 500
    default_detail: str = "An unexpected error occurred."

    def __init__(self, detail: str | None = None, *, headers: dict[str, str] | None = None) -> None:
        self.detail = detail or self.default_detail
        self.headers = headers or {}
        super().__init__(self.detail)


class BadRequestException(HTTPException):
    status_code = 400
    default_detail = "The request could not be understood."


class UnauthorizedException(HTTPException):
    status_code = 401
    default_detail = "Authentication is required."


class ForbiddenException(HTTPException):
    status_code = 403
    default_detail = "You do not have permission to perform this action."


class NotFoundException(HTTPException):
    status_code = 404
    default_detail = "The requested resource was not found."


class MethodNotAllowedException(HTTPException):
    status_code = 405
    default_detail = "This HTTP method is not allowed for this route."


class ConflictException(HTTPException):
    status_code = 409
    default_detail = "The request conflicts with the current state of the resource."


class ValidationException(HTTPException):
    status_code = 422
    default_detail = "The given data was invalid."

    def __init__(self, errors: dict[str, list[str]] | None = None, detail: str | None = None) -> None:
        self.errors = errors or {}
        super().__init__(detail)


class TooManyRequestsException(HTTPException):
    status_code = 429
    default_detail = "Too many requests. Please try again later."


def _wants_problem_json(request: Request | None) -> bool:
    """Whether ``API_PROBLEM_JSON=true`` is set -- checked per-request
    (rather than once at startup) because ``http_exception_handler`` is
    also called directly, request-less, in tests. See docs/api-standards.md.
    """
    if request is None:
        return False
    config = getattr(getattr(request, "app", None), "state", None)
    config = getattr(config, "config", None) if config is not None else None
    return bool(config.get("api.problem_json", False)) if config is not None else False


def _format_traceback(exc: BaseException) -> list[str]:
    """One string per frame, newline-terminated -- ``traceback.format_exception``'s
    native shape, easier for a client to render line-by-line than one giant
    string with embedded newlines.
    """
    return traceback.format_exception(type(exc), exc, exc.__traceback__)


def _debug_queries(exc: BaseException | None = None) -> list[Any]:
    """The crashed request's executed SQL queries (see
    :mod:`zeython.profiler`), or ``[]`` if that provider isn't registered.

    Prefers queries stashed directly on ``exc`` (by
    ``RequestProfilerMiddleware``'s ``except`` clause) over the
    :mod:`zeython.profiler` contextvar: by the time a crash reaches this
    handler, the middleware has already reset that contextvar, since
    leaving it bound past the request that crashed -- purely so this
    function could read it -- would leak a stale query list into
    whatever else shares the same asyncio Task afterward (harmless under
    a real server's one-Task-per-connection model, but not under
    ``zeython.testing.client()``'s inline ASGI calls, which reuse one
    Task across many requests in the same test). Falls back to the
    contextvar for the handful of callers with no exception object to
    hand in (e.g. an HTML debug page rendered outside a crash).

    A lazy, in-function import rather than a module-level one: this module
    is foundational (``zeython.db.model`` imports ``ValidationException``
    from it), so importing ``zeython.profiler`` -- which imports
    ``zeython.db.session``, which importing the ``zeython.db`` package
    first triggers -- at module load time would be a real circular
    import, not just an unnecessary dependency. By the time this actually
    runs (inside a request), every module involved has already finished
    loading, so the same import here is completely safe.
    """
    if exc is not None:
        stashed = getattr(exc, "_zeython_profiler_queries", None)
        if stashed is not None:
            return list(stashed)
    try:
        from zeython.profiler import current_queries
    except ImportError:
        return []
    return list(current_queries())


def _debug_queries_for_json(exc: BaseException | None = None) -> list[dict[str, Any]] | None:
    queries = _debug_queries(exc)
    if not queries:
        return None
    return [{"sql": " ".join(query.statement.split()), "duration_ms": query.duration_ms} for query in queries]


def _wants_html(request: Request | None) -> bool:
    """Whether this looks like a browser navigating directly to a broken page,
    rather than an API/fetch client -- decides whether debug mode's
    unhandled-exception page renders as a browsable HTML page (with a real
    stack trace and source snippets) instead of JSON. A browser's default
    ``Accept`` header lists ``text/html``; a JSON API client's typically
    doesn't. ``getattr``-guarded the same way the rest of this module is,
    since these handlers are also called directly against minimal request
    doubles in tests.
    """
    headers = getattr(request, "headers", None)
    accept = headers.get("accept", "") if headers is not None else ""
    return "text/html" in accept


_DEBUG_PAGE_CONTEXT_LINES = 5


def _frame_snippet(filename: str, lineno: int) -> list[tuple[int, str, bool]]:
    """Up to ``2 * _DEBUG_PAGE_CONTEXT_LINES + 1`` source lines around
    ``lineno``, as ``(line_number, text, is_culprit_line)`` -- empty if the
    source isn't readable (e.g. a file that no longer exists).
    """
    start = max(lineno - _DEBUG_PAGE_CONTEXT_LINES, 1)
    end = lineno + _DEBUG_PAGE_CONTEXT_LINES
    lines = []
    for n in range(start, end + 1):
        text = linecache.getline(filename, n)
        if not text:
            continue
        lines.append((n, text.rstrip("\n"), n == lineno))
    return lines


_DEBUG_PAGE_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; background: #1b1e23; color: #d5d8dc;
  font: 14px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif;
}
header {
  padding: 28px 32px; background: #23272e; border-bottom: 1px solid #33383f;
}
header h1 {
  margin: 0 0 6px; font-size: 22px; color: #ff6b6b;
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
header .message { margin: 0 0 4px; font-size: 15px; color: #f0f2f4; }
header .request-line {
  margin: 0; color: #8a919c; font-family: ui-monospace, monospace; font-size: 13px;
}
main { padding: 20px 32px 60px; }
.frame {
  border: 1px solid #33383f; border-radius: 6px; margin-bottom: 10px; overflow: hidden;
}
.frame-header {
  padding: 10px 14px; background: #23272e; cursor: default;
  display: flex; gap: 10px; align-items: baseline; font-size: 13px; flex-wrap: wrap;
}
.frame-index { color: #6b7280; font-family: ui-monospace, monospace; }
.frame-location {
  color: #7dd3fc; font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
.frame-func { color: #9aa1ac; }
.frame-func strong { color: #d5d8dc; }
.frame-code {
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  font-size: 12.5px; background: #17191d;
}
.frame-code .line { display: flex; white-space: pre; }
.frame-code .lineno {
  flex: 0 0 48px; text-align: right; padding: 1px 12px 1px 0;
  color: #565d68; user-select: none; border-right: 1px solid #262a31;
}
.frame-code .code { padding: 1px 14px; white-space: pre-wrap; word-break: break-all; }
.frame-code .line.culprit { background: #3a1f24; }
.frame-code .line.culprit .lineno { color: #ff8f8f; }
.queries {
  border: 1px solid #33383f; border-radius: 6px; margin-bottom: 20px; overflow: hidden;
}
.queries h2 {
  margin: 0; padding: 10px 14px; background: #23272e; font-size: 13px;
  font-weight: 600; color: #d5d8dc;
}
.query-row {
  display: flex; gap: 14px; padding: 8px 14px; border-top: 1px solid #262a31;
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 12.5px;
}
.query-time { flex: 0 0 70px; color: #7dd3fc; }
.query-sql { color: #d5d8dc; white-space: pre-wrap; word-break: break-all; }
footer {
  padding: 16px 32px; color: #6b7280; font-size: 12px;
  border-top: 1px solid #33383f;
}
"""


def _render_debug_html(request: Request, exc: BaseException) -> str:
    """A Laravel/Django-style debug page: exception, request line, and every
    stack frame with a source-code snippet around the culprit line -- shown
    only when ``APP_DEBUG=true`` *and* the request looks like a browser
    navigation (see :func:`_wants_html`), never to an API client.
    """
    frames = traceback.extract_tb(exc.__traceback__)
    method = getattr(request, "method", "")
    path = getattr(getattr(request, "url", None), "path", "")

    queries = _debug_queries(exc)
    queries_section = ""
    if queries:
        rows = "".join(
            f'<div class="query-row"><span class="query-time">{query.duration_ms:.2f} ms</span>'
            f'<span class="query-sql">{html.escape(" ".join(query.statement.split()))}</span></div>'
            for query in queries
        )
        total_ms = sum(query.duration_ms for query in queries)
        label = "query" if len(queries) == 1 else "queries"
        queries_section = f"""<section class="queries">
  <h2>{len(queries)} {label} ({total_ms:.2f} ms total)</h2>
  {rows}
</section>"""

    frame_sections = []
    for i, frame in enumerate(reversed(frames)):
        snippet = _frame_snippet(frame.filename, frame.lineno or 0)
        snippet_html = "".join(
            f'<div class="line{" culprit" if is_culprit else ""}">'
            f'<span class="lineno">{n}</span><span class="code">{html.escape(text)}</span></div>'
            for n, text, is_culprit in snippet
        )
        frame_sections.append(
            f"""<div class="frame">
  <div class="frame-header">
    <span class="frame-index">#{len(frames) - i}</span>
    <span class="frame-location">{html.escape(frame.filename)}:{frame.lineno}</span>
    <span class="frame-func">in <strong>{html.escape(frame.name)}</strong></span>
  </div>
  <div class="frame-code">{snippet_html}</div>
</div>"""
        )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{html.escape(type(exc).__name__)} — Zeython Debug</title>
<style>{_DEBUG_PAGE_CSS}</style>
</head>
<body>
<header>
  <h1>{html.escape(type(exc).__name__)}</h1>
  <p class="message">{html.escape(str(exc))}</p>
  <p class="request-line">{html.escape(method)} {html.escape(path)}</p>
</header>
<main>{queries_section}{"".join(frame_sections)}</main>
<footer>This page is only shown because APP_DEBUG=true. Turn it off in production.</footer>
</body>
</html>"""


def _problem_response(
    status_code: int,
    detail: str,
    *,
    errors: dict[str, list[str]] | None = None,
    exception: str | None = None,
    exc_traceback: list[str] | None = None,
    queries: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """RFC 7807 (``application/problem+json``) shaped error body -- ``type``
    is ``"about:blank"`` (RFC 7807's own fallback for "no more specific
    problem type than the HTTP status code itself"), since this framework
    doesn't maintain a registry of per-error-type URIs. ``errors``/``exception``/
    ``queries`` are nonstandard extension members, same field names/shapes
    the framework's default error format already uses -- RFC 7807
    explicitly permits extending the problem object this way.
    """
    payload: dict[str, Any] = {
        "type": "about:blank",
        "title": HTTPStatus(status_code).phrase,
        "status": status_code,
        "detail": detail,
    }
    if errors:
        payload["errors"] = errors
    if exception:
        payload["exception"] = exception
    if exc_traceback:
        payload["traceback"] = exc_traceback
    if queries:
        payload["queries"] = queries
    return JSONResponse(payload, status_code=status_code, headers=headers, media_type="application/problem+json")


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    errors = exc.errors if isinstance(exc, ValidationException) and exc.errors else None
    if _wants_problem_json(request):
        return _problem_response(exc.status_code, exc.detail, errors=errors, headers=exc.headers)

    payload: dict[str, Any] = {"error": exc.detail, "status": exc.status_code}
    if errors:
        payload["errors"] = errors
    return JSONResponse(payload, status_code=exc.status_code, headers=exc.headers)


async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    # A genuine bug, not an expected control-flow exception (those are
    # HTTPException subclasses, handled separately above and never reach
    # here) -- reported to Sentry if zeython.error_monitoring is
    # configured, a no-op otherwise. getattr-guarded: a real Starlette
    # Request always has .url/.method, but this handler is also called
    # directly in tests against minimal request doubles.
    report_exception(
        exc,
        request_id=request_id(),
        path=getattr(getattr(request, "url", None), "path", None),
        method=getattr(request, "method", None),
    )

    state = getattr(getattr(request, "app", None), "state", None)
    debug = getattr(state, "debug", False) if state is not None else False

    if _wants_problem_json(request):
        exception_detail = f"{type(exc).__name__}: {exc}" if debug else None
        exc_traceback = _format_traceback(exc) if debug else None
        queries = _debug_queries_for_json(exc) if debug else None
        return _problem_response(
            500,
            "An unexpected error occurred.",
            exception=exception_detail,
            exc_traceback=exc_traceback,
            queries=queries,
        )

    # A browser hitting a broken page in development gets the full debug
    # page (stack trace + source snippets); an API/fetch client -- even in
    # debug mode -- still gets the plain JSON shape below, so a frontend
    # dev's error handling code doesn't have to special-case HTML bodies.
    if debug and _wants_html(request):
        return HTMLResponse(_render_debug_html(request, exc), status_code=500)

    payload: dict[str, Any] = {"error": "Internal Server Error", "status": 500}
    if debug:
        payload["exception"] = f"{type(exc).__name__}: {exc}"
        payload["traceback"] = _format_traceback(exc)
        queries = _debug_queries_for_json(exc)
        if queries:
            payload["queries"] = queries
    return JSONResponse(payload, status_code=500)


def default_exception_handlers() -> dict[Any, Any]:
    return {
        HTTPException: http_exception_handler,
        Exception: unhandled_exception_handler,
    }

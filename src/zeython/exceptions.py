"""HTTP-aware exception hierarchy with a default JSON error handler."""

from __future__ import annotations

import traceback
from http import HTTPStatus
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from zeython.error_monitoring import report_exception
from zeython.request_id import request_id


class HTTPException(Exception):
    """Base class for exceptions that should be rendered as HTTP responses."""

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


def _problem_response(
    status_code: int,
    detail: str,
    *,
    errors: dict[str, list[str]] | None = None,
    exception: str | None = None,
    exc_traceback: list[str] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """RFC 7807 (``application/problem+json``) shaped error body -- ``type``
    is ``"about:blank"`` (RFC 7807's own fallback for "no more specific
    problem type than the HTTP status code itself"), since this framework
    doesn't maintain a registry of per-error-type URIs. ``errors``/``exception``
    are nonstandard extension members, same field names/shapes the
    framework's default error format already uses -- RFC 7807 explicitly
    permits extending the problem object this way.
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
    return JSONResponse(payload, status_code=status_code, headers=headers, media_type="application/problem+json")


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    errors = exc.errors if isinstance(exc, ValidationException) and exc.errors else None
    if _wants_problem_json(request):
        return _problem_response(exc.status_code, exc.detail, errors=errors, headers=exc.headers)

    payload: dict[str, Any] = {"error": exc.detail, "status": exc.status_code}
    if errors:
        payload["errors"] = errors
    return JSONResponse(payload, status_code=exc.status_code, headers=exc.headers)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
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
        return _problem_response(
            500, "An unexpected error occurred.", exception=exception_detail, exc_traceback=exc_traceback
        )

    payload: dict[str, Any] = {"error": "Internal Server Error", "status": 500}
    if debug:
        payload["exception"] = f"{type(exc).__name__}: {exc}"
        payload["traceback"] = _format_traceback(exc)
    return JSONResponse(payload, status_code=500)


def default_exception_handlers() -> dict[Any, Any]:
    return {
        HTTPException: http_exception_handler,
        Exception: unhandled_exception_handler,
    }

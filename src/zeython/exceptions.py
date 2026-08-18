"""HTTP-aware exception hierarchy with a default JSON error handler."""

from __future__ import annotations

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


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    payload: dict[str, Any] = {"error": exc.detail, "status": exc.status_code}
    if isinstance(exc, ValidationException) and exc.errors:
        payload["errors"] = exc.errors
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

    debug = getattr(request.app.state, "debug", False)
    payload: dict[str, Any] = {"error": "Internal Server Error", "status": 500}
    if debug:
        payload["exception"] = f"{type(exc).__name__}: {exc}"
    return JSONResponse(payload, status_code=500)


def default_exception_handlers() -> dict[Any, Any]:
    return {
        HTTPException: http_exception_handler,
        Exception: unhandled_exception_handler,
    }

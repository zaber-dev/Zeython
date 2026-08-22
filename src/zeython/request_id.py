"""Correlation IDs for tracing one request across a busy log stream.

A single request can produce several log lines -- received, a DB query,
maybe a background job dispatched, the response sent -- and without
something tying them together, reconstructing "what happened for this one
request" from concurrent traffic is guesswork. ``RequestIdMiddleware``
stamps every request/response pair with an ID (the caller's own
``X-Request-ID`` if it sent one, so a request can be traced across
multiple services that all honor the same header, otherwise a fresh
UUID4) and makes it available to every log line emitted while handling
that request.
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.datastructures import MutableHeaders

from zeython.providers import ServiceProvider

DEFAULT_HEADER_NAME = "X-Request-ID"

_current_request_id: ContextVar[str | None] = ContextVar("zeython_request_id", default=None)


def request_id() -> str | None:
    """The current request's correlation ID, or ``None`` outside a request."""
    return _current_request_id.get()


class RequestIdLogFilter(logging.Filter):
    """Adds the current request's ID to every ``LogRecord`` as ``request_id``.

    Installed on the root logger's handlers automatically by
    :class:`RequestIdServiceProvider`, so ``%(request_id)s`` is available to
    any formatter -- ``"-"`` for a log line emitted outside of a request
    (startup, a scheduled job) rather than a missing attribute. Deliberately
    attached to each *handler*, not the logger itself: a ``Logger.filter``
    only runs for records that logger originates directly, never for ones
    propagated up from a child logger (``uvicorn.error``, your own
    ``__name__`` loggers) -- which is most of them.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _current_request_id.get() or "-"
        return True


class RequestIdMiddleware:
    """Pure ASGI middleware: stamps every request/response with a correlation ID.

    Sets the ID as a contextvar for the duration of the request -- readable
    via :func:`request_id` from any code running while handling it,
    including a logging filter -- and echoes it back as a response header
    so a client can correlate its own logs with the server's.
    """

    def __init__(self, app: Any, *, header_name: str = DEFAULT_HEADER_NAME) -> None:
        self.app = app
        self.header_name = header_name
        self._header_key = header_name.lower().encode("latin-1")

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(self._header_key)
        current_id = incoming.decode("latin-1") if incoming else str(uuid.uuid4())

        token = _current_request_id.set(current_id)

        async def send_with_header(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append(self.header_name, current_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        except BaseException:
            # Deliberately no reset here -- see the identical note in
            # zeython.profiler.RequestProfilerMiddleware. Starlette's
            # ServerErrorMiddleware sits *outside* every user-added
            # middleware (including this one), so unhandled_exception_handler
            # (zeython.exceptions) -- which reads request_id() to tag the
            # error report -- only runs after this exception has already
            # propagated past us. Resetting here would blank the request ID
            # right before the one call that most needs it: correlating a
            # crash report back to this request's other log lines.
            raise
        else:
            _current_request_id.reset(token)


class RequestIdServiceProvider(ServiceProvider):
    """Registers :class:`RequestIdMiddleware` and wires up its logging context.

    Registered by default in a generated project -- unlike
    :class:`~zeython.security_headers.SecurityHeadersServiceProvider`, there
    is no application-specific default to get wrong here: it only adds a
    response header and a piece of log context, never changes what a
    request is allowed to do.

    - ``REQUEST_ID_HEADER`` -- default ``X-Request-ID``.
    """

    def boot(self) -> None:
        self.app.add_middleware(
            RequestIdMiddleware,
            header_name=self.config.get("request_id.header", DEFAULT_HEADER_NAME),
        )
        _install_log_filter()


def _install_log_filter() -> None:
    # Best-effort: fold `request_id` into the framework's own default
    # format (zeython.application._configure_default_logging) so it shows
    # up in generated-project logs with no extra setup. Left untouched for
    # any other format -- a user who configured their own formatter opted
    # out of this framework guessing at it, but `record.request_id` is
    # still available to build one intentionally.
    default_format = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    for handler in logging.root.handlers:
        if any(isinstance(existing, RequestIdLogFilter) for existing in handler.filters):
            continue
        handler.addFilter(RequestIdLogFilter())

        formatter = handler.formatter
        if formatter is not None and formatter._fmt == default_format:
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)-8s %(name)s [%(request_id)s]: %(message)s",
                    datefmt=formatter.datefmt,
                )
            )


__all__ = [
    "DEFAULT_HEADER_NAME",
    "RequestIdLogFilter",
    "RequestIdMiddleware",
    "RequestIdServiceProvider",
    "request_id",
]

"""Request/query profiler: an opt-in, dev-only record of every SQL query a
request ran, with duration -- the Laravel Telescope / Django Debug Toolbar
question ("how many queries did this request run, and how long did they
take") answered without a bundled UI, since most of what this framework
serves is a JSON API rather than server-rendered HTML pages a toolbar
overlay could attach to.

Every response gets ``X-Debug-Duration-Ms``/``X-Debug-Query-Count``/
``X-Debug-Query-Time-Ms`` headers instead -- inspectable from any HTTP
client, a browser's network tab, or a test assertion, no special
tooling required. A request that crashes gets the same information baked
into the debug error page/body (see :mod:`zeython.exceptions`).

Deliberately separate from :mod:`zeython.n_plus_one`, which answers a
different, narrower question (the same statement shape repeated
suspiciously many times) and can be registered independently of this.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event

from zeython.db.session import Database
from zeython.providers import ServiceProvider

logger = logging.getLogger("zeython.profiler")

DEFAULT_SLOW_QUERY_MS = 100.0


@dataclass(frozen=True)
class QueryRecord:
    statement: str
    duration_ms: float


_current_queries: ContextVar[list[QueryRecord] | None] = ContextVar("zeython_profiler_queries", default=None)


def _before_cursor_execute(
    conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
) -> None:
    context._zeython_profiler_start = time.perf_counter()


def _after_cursor_execute(
    conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
) -> None:
    queries = _current_queries.get()
    if queries is None:
        return
    start = getattr(context, "_zeython_profiler_start", None)
    duration_ms = (time.perf_counter() - start) * 1000 if start is not None else 0.0
    queries.append(QueryRecord(statement=statement, duration_ms=duration_ms))


def current_queries() -> list[QueryRecord]:
    """The SQL queries executed so far during the current request, in
    order -- empty if :class:`RequestProfilerServiceProvider` isn't
    registered (or ``APP_DEBUG`` is false), or if called outside a
    request/response cycle the middleware wrapped.
    """
    return list(_current_queries.get() or [])


class RequestProfilerMiddleware:
    """Pure ASGI middleware: records this request's queries via a
    :class:`~contextvars.ContextVar` (the same mechanism
    :mod:`zeython.request_id`/:mod:`zeython.n_plus_one` use), stamps
    ``X-Debug-Duration-Ms``/``X-Debug-Query-Count``/``X-Debug-Query-Time-Ms``
    on the response, and logs (``zeython.profiler``, at ``WARNING``) any
    individual query at or past ``slow_query_threshold_ms``.
    """

    def __init__(self, app: Callable[..., Any], *, slow_query_threshold_ms: float = DEFAULT_SLOW_QUERY_MS) -> None:
        self.app = app
        self.slow_query_threshold_ms = slow_query_threshold_ms

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        queries: list[QueryRecord] = []
        token = _current_queries.set(queries)
        start = time.perf_counter()

        async def send_with_debug_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                duration_ms = (time.perf_counter() - start) * 1000
                query_time_ms = sum(query.duration_ms for query in queries)
                headers = list(message.get("headers", []))
                for name, value in (
                    (b"x-debug-duration-ms", f"{duration_ms:.2f}"),
                    (b"x-debug-query-count", str(len(queries))),
                    (b"x-debug-query-time-ms", f"{query_time_ms:.2f}"),
                ):
                    headers.append((name, value.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_debug_headers)
        except BaseException as exc:
            # Starlette's ServerErrorMiddleware sits *outside* every
            # user-added middleware (including this one) -- the registered
            # Exception handler, and the debug page/body it builds (see
            # zeython.exceptions), only runs after this exception has
            # already propagated past us, by which point this middleware's
            # own __call__ frame (and the reset below) has already run. So
            # the query list can't be handed off via the contextvar alone
            # -- it's stashed directly on the exception instead, which
            # zeython.exceptions reads back off `exc` if present. Without
            # this, leaving the contextvar bound past this request (the
            # previous approach) so that handler *could* still read it
            # would leak this crashed request's queries into whatever
            # later code shares this asyncio Task -- harmless under a real
            # server's one-Task-per-connection model, but not under
            # zeython.testing.client()'s inline ASGI calls, which reuse
            # one Task across many requests in the same test.
            exc._zeython_profiler_queries = list(queries)  # type: ignore[attr-defined]  # noqa: SLF001
            raise
        else:
            path = scope.get("path", "?")
            for query in queries:
                if query.duration_ms >= self.slow_query_threshold_ms:
                    logger.warning(
                        "Slow query on %s: %.2f ms -- %s",
                        path,
                        query.duration_ms,
                        " ".join(query.statement.split()),
                    )
        finally:
            _current_queries.reset(token)


class RequestProfilerServiceProvider(ServiceProvider):
    """Hooks the SQLAlchemy engine and registers
    :class:`RequestProfilerMiddleware` -- not registered by default, and a
    no-op in ``boot()`` unless ``APP_DEBUG`` is true, so it's safe to
    always register (including in a production ``main.py``) without
    worrying about the per-query event-listener overhead or leaking query
    text/timing from real traffic::

        # main.py
        app.register(DatabaseServiceProvider)  # must run first -- binds Database
        app.register(RequestProfilerServiceProvider(app))

    Configurable via ``.env``:

    - ``PROFILER_SLOW_QUERY_MS`` -- default 100.
    """

    def boot(self) -> None:
        if not self.config.debug:
            return
        database = self.container.make(Database)
        event.listen(database.engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
        event.listen(database.engine.sync_engine, "after_cursor_execute", _after_cursor_execute)
        threshold = float(self.config.get("profiler.slow_query_ms", DEFAULT_SLOW_QUERY_MS))
        self.app.add_middleware(RequestProfilerMiddleware, slow_query_threshold_ms=threshold)


__all__ = [
    "QueryRecord",
    "current_queries",
    "RequestProfilerMiddleware",
    "RequestProfilerServiceProvider",
]

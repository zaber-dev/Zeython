"""N+1 query detection: an opt-in, dev-only warning when a single request
fires the exact same SQL statement shape suspiciously many times -- the
classic symptom of fetching each row's related object one at a time in a
loop instead of eager-loading with ``include=(...)`` (see
docs/relationships.md).

Hooks SQLAlchemy's ``before_cursor_execute`` event on the engine and
counts statements (bound parameters aside -- the same query with
different parameter *values* still produces an identical parameterized
statement string, so ``SELECT ... WHERE id = ?`` run once per row in a
loop groups together as one entry with a high count) per request, via a
:class:`contextvars.ContextVar`, the same mechanism
:mod:`zeython.request_id` uses.
"""

from __future__ import annotations

import logging
from collections import Counter
from contextvars import ContextVar
from typing import Any

from sqlalchemy import event

from zeython.db.session import Database
from zeython.providers import ServiceProvider

logger = logging.getLogger("zeython.n_plus_one")

DEFAULT_THRESHOLD = 10

_current_counter: ContextVar[Counter[str] | None] = ContextVar("zeython_n1_counter", default=None)


def _before_cursor_execute(
    conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
) -> None:
    counter = _current_counter.get()
    if counter is None:
        return
    # Only SELECTs -- a repeated INSERT/UPDATE (a legitimate bulk-write
    # loop) isn't the "fetch a relationship one row at a time" pattern
    # this exists to catch, and "eager-load it instead" would be
    # nonsensical advice for one.
    if statement.lstrip()[:6].upper() == "SELECT":
        counter[statement] += 1


class N1QueryDetectionMiddleware:
    """Pure ASGI middleware: counts SQL statements per request, warning
    (``zeython.n_plus_one``, at ``WARNING``) for any statement shape that
    ran more than ``threshold`` times in the same request.
    """

    def __init__(self, app: Any, *, threshold: int = DEFAULT_THRESHOLD) -> None:
        self.app = app
        self.threshold = threshold

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        counter: Counter[str] = Counter()
        token = _current_counter.set(counter)
        try:
            await self.app(scope, receive, send)
        finally:
            _current_counter.reset(token)
            path = scope.get("path", "?")
            for statement, count in counter.items():
                if count > self.threshold:
                    logger.warning(
                        "Possible N+1 query on %s: the same statement ran %d times in one "
                        "request. Eager-load the relationship instead (include=(...), see "
                        "docs/relationships.md). Query: %s",
                        path,
                        count,
                        " ".join(statement.split()),
                    )


class N1QueryDetectionServiceProvider(ServiceProvider):
    """Hooks the SQLAlchemy engine and registers
    :class:`N1QueryDetectionMiddleware` -- not registered by default, and a
    no-op in ``boot()`` unless ``APP_DEBUG`` is true, so it's safe to
    always register (including in a production ``main.py``) without
    worrying about the per-query event-listener overhead or leaking query
    text/counts from real traffic into production logs::

        # main.py
        app.register(DatabaseServiceProvider)  # must run first -- binds Database
        app.register(N1QueryDetectionServiceProvider(app))

    Configurable via ``.env``:

    - ``N1_QUERY_THRESHOLD`` -- default 10.
    """

    def boot(self) -> None:
        if not self.config.debug:
            return
        database = self.container.make(Database)
        event.listen(database.engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
        threshold = int(self.config.get("n1_query.threshold", DEFAULT_THRESHOLD))
        self.app.add_middleware(N1QueryDetectionMiddleware, threshold=threshold)


__all__ = ["N1QueryDetectionMiddleware", "N1QueryDetectionServiceProvider"]

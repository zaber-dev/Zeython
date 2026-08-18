"""In-app task scheduling: recurring jobs defined in code (and therefore
version-controlled, reviewed, and deployed alongside the app) instead of
scattered across a server's crontab where nobody remembers what runs and
why.

``Schedule`` holds a list of ``ScheduledEvent``s; ``zeython schedule run``
-- meant to be invoked once a minute by a single cron entry (or a sidecar
loop container, see docs/scheduling.md) -- checks which are due this
minute and runs them. Nothing here polls or sleeps on its own: the actual
"once a minute" cadence is still driven by whatever calls ``zeython
schedule run``, the same way Laravel's own ``schedule:run`` works.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING

from zeython.container import Container
from zeython.error_monitoring import report_exception
from zeython.providers import ServiceProvider

if TYPE_CHECKING:
    from zeython.application import Application

logger = logging.getLogger("zeython.schedule")


def _field_matches(value: int, field: str) -> bool:
    if field == "*":
        return True
    for part in field.split(","):
        if "/" in part:
            base, _, step_str = part.partition("/")
            step = int(step_str)
            if base == "*":
                if value % step == 0:
                    return True
                continue
            lo_str, _, hi_str = base.partition("-")
            lo, hi = int(lo_str), int(hi_str) if hi_str else int(lo_str)
            if lo <= value <= hi and (value - lo) % step == 0:
                return True
        elif "-" in part:
            lo_str, hi_str = part.split("-")
            if int(lo_str) <= value <= int(hi_str):
                return True
        elif int(part) == value:
            return True
    return False


def cron_matches(expression: str, at: datetime) -> bool:
    """Whether a standard 5-field cron expression (``minute hour day month
    weekday``) matches ``at``. Supports ``*``, single values, comma lists
    (``1,3,5``), ranges (``1-5``), and step values (``*/15``, ``1-10/2``).

    The weekday field is ``0``-``6`` (``0`` = Sunday) only -- unlike some
    cron implementations, ``7`` is not accepted as an alias for Sunday.
    """
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError(f"Invalid cron expression (expected 5 space-separated fields): {expression!r}")
    minute, hour, day, month, weekday = fields
    cron_weekday = (at.weekday() + 1) % 7  # Python: Monday=0..Sunday=6 -> cron: Sunday=0..Saturday=6
    return (
        _field_matches(at.minute, minute)
        and _field_matches(at.hour, hour)
        and _field_matches(at.day, day)
        and _field_matches(at.month, month)
        and _field_matches(cron_weekday, weekday)
    )


class ScheduledEvent:
    """One recurring task: a callback plus a cron expression saying when
    it's due. Built fluently off :meth:`Schedule.call`; every builder
    method returns ``self`` so calls chain::

        schedule.call(send_daily_digest).daily_at("07:00")
    """

    def __init__(
        self,
        name: str,
        callback: Callable[..., Awaitable[None]],
        *,
        container: Container | None = None,
    ) -> None:
        self.name = name
        self.callback = callback
        self.container = container
        self.cron_expression = "* * * * *"
        self._overlap_window: float | None = None

    def cron(self, expression: str) -> ScheduledEvent:
        """Any 5-field cron expression -- see :func:`cron_matches`."""
        self.cron_expression = expression
        return self

    def every_minute(self) -> ScheduledEvent:
        return self.cron("* * * * *")

    def every_five_minutes(self) -> ScheduledEvent:
        return self.cron("*/5 * * * *")

    def every_fifteen_minutes(self) -> ScheduledEvent:
        return self.cron("*/15 * * * *")

    def hourly(self) -> ScheduledEvent:
        return self.cron("0 * * * *")

    def daily(self) -> ScheduledEvent:
        return self.cron("0 0 * * *")

    def daily_at(self, time: str) -> ScheduledEvent:
        """``"HH:MM"``, 24-hour, e.g. ``daily_at("07:30")``."""
        hour_str, minute_str = time.split(":")
        return self.cron(f"{int(minute_str)} {int(hour_str)} * * *")

    def weekly(self) -> ScheduledEvent:
        """Sunday at midnight."""
        return self.cron("0 0 * * 0")

    def monthly(self) -> ScheduledEvent:
        """The 1st of the month at midnight."""
        return self.cron("0 0 1 * *")

    def without_overlapping(self, *, for_seconds: float = 3600) -> ScheduledEvent:
        """Skip a run if a previous one started within the last
        ``for_seconds`` -- for a task that occasionally runs longer than
        its own interval, or one you never want two copies of running
        against each other.

        Implemented via the container's bound ``RateLimiter`` as a "run at
        most once per window" gate, keyed by this event's name -- a
        time-based window, same trade-off Laravel's own
        ``withoutOverlapping()`` makes: the lock expires after
        ``for_seconds`` regardless of whether the previous run actually
        finished, it doesn't track "is it still running" directly.

        **Requires a shared ``RateLimiter`` backend (``RedisRateLimiter``)
        to do anything in the normal case.** ``zeython schedule run`` is a
        fresh process every time cron invokes it -- the default
        ``InMemoryRateLimiter``'s lock lives in that process's memory and
        is gone the instant it exits, so back-to-back CLI invocations never
        see each other's lock at all. See docs/scheduling.md.
        """
        self._overlap_window = for_seconds
        return self

    def is_due(self, at: datetime) -> bool:
        return cron_matches(self.cron_expression, at)

    async def run(self) -> None:
        if self._overlap_window is not None and self.container is not None:
            from zeython.rate_limit import RateLimiter

            try:
                limiter = self.container.make(RateLimiter)
            except Exception:
                limiter = None
            if limiter is not None:
                result = await limiter.hit(
                    f"zeython:schedule:lock:{self.name}", limit=1, window=self._overlap_window
                )
                if not result.allowed:
                    logger.info(
                        "Skipping scheduled event %s -- a previous run started within the last %ds",
                        self.name,
                        int(self._overlap_window),
                    )
                    return

        if self.container is not None:
            await self.container.call(self.callback)
        else:
            await self.callback()


class Schedule:
    """The registry ``schedule.py`` builds against: ``schedule.call(fn).daily()``."""

    def __init__(self, *, container: Container | None = None) -> None:
        self.container = container
        self._events: list[ScheduledEvent] = []

    def call(self, callback: Callable[..., Awaitable[None]], *, name: str | None = None) -> ScheduledEvent:
        """Register ``callback`` (any async function; type-hinted params
        beyond the ones you pass are autowired from the container, same as
        a ``Job``'s ``handle()``) and return the :class:`ScheduledEvent` to
        set its frequency on."""
        event_name: str = name if name is not None else getattr(callback, "__name__", repr(callback))
        event = ScheduledEvent(
            name=event_name,
            callback=callback,
            container=self.container,
        )
        self._events.append(event)
        return event

    def __iter__(self):
        return iter(self._events)

    def __len__(self) -> int:
        return len(self._events)

    async def run_due(self, *, at: datetime | None = None) -> list[ScheduledEvent]:
        """Run every event due at ``at`` (default: now), returning the
        ones that were due. An event that raises is logged and doesn't
        stop the rest from running -- what ``zeython schedule run`` calls.
        """
        now = at or datetime.now()
        due = [event for event in self._events if event.is_due(now)]
        for event in due:
            try:
                await event.run()
            except Exception as exc:
                logger.exception("Scheduled event %s raised", event.name)
                # No retry concept for a scheduled task -- every failure
                # here is already final, unlike a queued job's retries.
                report_exception(exc, scheduled_event=event.name)
        return due


class ScheduleServiceProvider(ServiceProvider):
    """Binds a process-wide :class:`Schedule` singleton and imports
    ``schedule.py`` from the project root for its side effect of
    registering events on it -- the same convention
    :class:`~zeython.providers.RouteServiceProvider` uses for
    ``routes/web.py``.

    Not registered by default -- add it once you have scheduled tasks to
    define::

        # main.py
        app.register(ScheduleServiceProvider(app))
    """

    def __init__(self, app: Application, modules: tuple[str, ...] = ("schedule",)) -> None:
        super().__init__(app)
        self.modules = modules

    def register(self) -> None:
        import importlib

        schedule = Schedule(container=self.container)
        self.container.singleton(Schedule, lambda: schedule)

        for module_name in self.modules:
            importlib.import_module(module_name)


__all__ = ["Schedule", "ScheduledEvent", "ScheduleServiceProvider", "cron_matches"]

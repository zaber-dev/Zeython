from datetime import datetime
from pathlib import Path

import pytest

from zeython.application import Application
from zeython.config import Config
from zeython.container import Container
from zeython.rate_limit import InMemoryRateLimiter, RateLimiter
from zeython.schedule import Schedule, ScheduledEvent, ScheduleServiceProvider, cron_matches

# -- cron_matches -------------------------------------------------------------------------


def test_star_matches_everything() -> None:
    assert cron_matches("* * * * *", datetime(2026, 8, 18, 13, 37))


def test_exact_minute_matches_only_that_minute() -> None:
    assert cron_matches("30 * * * *", datetime(2026, 8, 18, 13, 30))
    assert not cron_matches("30 * * * *", datetime(2026, 8, 18, 13, 31))


def test_comma_list_matches_any_listed_value() -> None:
    assert cron_matches("0,15,30,45 * * * *", datetime(2026, 8, 18, 13, 15))
    assert not cron_matches("0,15,30,45 * * * *", datetime(2026, 8, 18, 13, 20))


def test_range_matches_within_bounds() -> None:
    assert cron_matches("* 9-17 * * *", datetime(2026, 8, 18, 12, 0))
    assert not cron_matches("* 9-17 * * *", datetime(2026, 8, 18, 8, 0))
    assert not cron_matches("* 9-17 * * *", datetime(2026, 8, 18, 18, 0))


def test_step_matches_every_nth_value() -> None:
    assert cron_matches("*/15 * * * *", datetime(2026, 8, 18, 13, 0))
    assert cron_matches("*/15 * * * *", datetime(2026, 8, 18, 13, 15))
    assert not cron_matches("*/15 * * * *", datetime(2026, 8, 18, 13, 20))


def test_step_within_a_range() -> None:
    assert cron_matches("0-10/2 * * * *", datetime(2026, 8, 18, 13, 4))
    assert not cron_matches("0-10/2 * * * *", datetime(2026, 8, 18, 13, 5))


def test_all_fields_must_match() -> None:
    # 2026-08-18 is a Tuesday.
    assert cron_matches("0 9 18 8 *", datetime(2026, 8, 18, 9, 0))
    assert not cron_matches("0 9 18 8 *", datetime(2026, 8, 19, 9, 0))


def test_weekday_field_sunday_is_zero() -> None:
    # 2026-08-16 is a Sunday, 2026-08-17 is a Monday.
    assert cron_matches("0 0 * * 0", datetime(2026, 8, 16, 0, 0))
    assert not cron_matches("0 0 * * 0", datetime(2026, 8, 17, 0, 0))
    assert cron_matches("0 0 * * 1", datetime(2026, 8, 17, 0, 0))


def test_day_and_weekday_combine_with_or_when_both_restricted() -> None:
    # Regression guard: standard cron treats day-of-month and weekday as
    # cumulative (OR'd) once *both* are restricted (neither is "*") --
    # "0 0 1 * 1" means "midnight on the 1st of the month, or every
    # Monday", not "only when the 1st happens to be a Monday". This used
    # to AND every field unconditionally, so it silently matched far less
    # often than a real crontab entry using this pattern expects.
    monday_not_the_first = datetime(2025, 11, 10, 0, 0)  # a Monday
    the_first_not_a_monday = datetime(2025, 11, 1, 0, 0)  # a Saturday
    neither = datetime(2025, 11, 11, 0, 0)  # a Tuesday, not the 1st

    assert cron_matches("0 0 1 * 1", monday_not_the_first)
    assert cron_matches("0 0 1 * 1", the_first_not_a_monday)
    assert not cron_matches("0 0 1 * 1", neither)


def test_day_and_weekday_and_together_when_only_one_is_restricted() -> None:
    # With only one of the two restricted, that field alone decides --
    # the OR-combination rule only kicks in once *both* are restricted.
    monday_not_the_first = datetime(2025, 11, 10, 0, 0)  # a Monday
    the_first_not_a_monday = datetime(2025, 11, 1, 0, 0)  # a Saturday

    assert cron_matches("0 0 * * 1", monday_not_the_first)  # weekday only
    assert not cron_matches("0 0 * * 1", the_first_not_a_monday)
    assert cron_matches("0 0 1 * *", the_first_not_a_monday)  # day only
    assert not cron_matches("0 0 1 * *", monday_not_the_first)


def test_invalid_expression_raises_value_error() -> None:
    with pytest.raises(ValueError, match="5 space-separated fields"):
        cron_matches("* * * *", datetime.now())


# -- ScheduledEvent: fluent frequency builders -------------------------------------------


def _event() -> ScheduledEvent:
    async def noop() -> None:
        pass

    return ScheduledEvent("noop", noop)


def test_every_minute() -> None:
    assert _event().every_minute().cron_expression == "* * * * *"


def test_every_five_minutes() -> None:
    assert _event().every_five_minutes().cron_expression == "*/5 * * * *"


def test_every_fifteen_minutes() -> None:
    assert _event().every_fifteen_minutes().cron_expression == "*/15 * * * *"


def test_hourly() -> None:
    assert _event().hourly().cron_expression == "0 * * * *"


def test_daily() -> None:
    assert _event().daily().cron_expression == "0 0 * * *"


def test_daily_at() -> None:
    assert _event().daily_at("07:30").cron_expression == "30 7 * * *"


def test_weekly() -> None:
    assert _event().weekly().cron_expression == "0 0 * * 0"


def test_monthly() -> None:
    assert _event().monthly().cron_expression == "0 0 1 * *"


def test_cron_sets_a_raw_expression() -> None:
    assert _event().cron("*/10 8-17 * * 1-5").cron_expression == "*/10 8-17 * * 1-5"


def test_builder_methods_return_self_for_chaining() -> None:
    event = _event()
    assert event.every_minute() is event


def test_is_due_delegates_to_cron_matches() -> None:
    event = _event().daily_at("09:00")
    assert event.is_due(datetime(2026, 8, 18, 9, 0))
    assert not event.is_due(datetime(2026, 8, 18, 9, 1))


# -- ScheduledEvent.run() ------------------------------------------------------------------


async def test_run_calls_the_callback() -> None:
    calls: list[str] = []

    async def record() -> None:
        calls.append("ran")

    await ScheduledEvent("record", record).run()
    assert calls == ["ran"]


async def test_run_autowires_typed_params_from_the_container() -> None:
    class Greeter:
        def greeting(self) -> str:
            return "hello from the container"

    container = Container()
    container.singleton(Greeter)
    calls: list[str] = []

    async def greet(greeter: Greeter) -> None:
        calls.append(greeter.greeting())

    await ScheduledEvent("greet", greet, container=container).run()
    assert calls == ["hello from the container"]


async def test_run_without_overlapping_skips_a_second_run_within_the_window() -> None:
    container = Container()
    limiter = InMemoryRateLimiter()
    container.singleton(RateLimiter, lambda: limiter)
    calls: list[str] = []

    async def record() -> None:
        calls.append("ran")

    event = ScheduledEvent("record", record, container=container).without_overlapping(for_seconds=3600)

    await event.run()
    await event.run()

    assert calls == ["ran"]  # second run was skipped


async def test_run_without_overlapping_allows_a_different_events_name_through() -> None:
    container = Container()
    limiter = InMemoryRateLimiter()
    container.singleton(RateLimiter, lambda: limiter)
    calls: list[str] = []

    async def record() -> None:
        calls.append("ran")

    a = ScheduledEvent("event-a", record, container=container).without_overlapping(for_seconds=3600)
    b = ScheduledEvent("event-b", record, container=container).without_overlapping(for_seconds=3600)

    await a.run()
    await b.run()

    assert calls == ["ran", "ran"]  # different lock keys -- neither blocks the other


async def test_run_without_overlapping_with_no_rate_limiter_bound_still_runs() -> None:
    # No RateLimiter registered in the container -- without_overlapping()
    # degrades to "always run" rather than raising.
    container = Container()
    calls: list[str] = []

    async def record() -> None:
        calls.append("ran")

    event = ScheduledEvent("record", record, container=container).without_overlapping()
    await event.run()
    assert calls == ["ran"]


# -- Schedule -------------------------------------------------------------------------------


async def test_call_registers_an_event() -> None:
    schedule = Schedule()

    async def noop() -> None:
        pass

    schedule.call(noop)
    assert len(schedule) == 1


async def test_call_defaults_the_name_to_the_function_name() -> None:
    schedule = Schedule()

    async def send_report() -> None:
        pass

    event = schedule.call(send_report)
    assert event.name == "send_report"


async def test_call_accepts_an_explicit_name() -> None:
    schedule = Schedule()

    async def noop() -> None:
        pass

    event = schedule.call(noop, name="custom-name")
    assert event.name == "custom-name"


async def test_run_due_only_runs_events_due_at_the_given_time() -> None:
    schedule = Schedule()
    calls: list[str] = []

    async def hourly_task() -> None:
        calls.append("hourly")

    async def daily_task() -> None:
        calls.append("daily")

    schedule.call(hourly_task).hourly()
    schedule.call(daily_task).daily()

    due = await schedule.run_due(at=datetime(2026, 8, 18, 13, 0))  # on the hour, not midnight

    assert calls == ["hourly"]
    assert [event.name for event in due] == ["hourly_task"]


async def test_run_due_defaults_to_now_when_at_is_omitted() -> None:
    schedule = Schedule()
    calls: list[str] = []

    async def always() -> None:
        calls.append("ran")

    schedule.call(always).every_minute()
    await schedule.run_due()

    assert calls == ["ran"]


async def test_run_due_continues_past_a_raising_event() -> None:
    schedule = Schedule()
    calls: list[str] = []

    async def boom() -> None:
        raise RuntimeError("scheduled task blew up")

    async def fine() -> None:
        calls.append("fine")

    schedule.call(boom).every_minute()
    schedule.call(fine).every_minute()

    due = await schedule.run_due()

    assert calls == ["fine"]
    assert len(due) == 2  # both were due -- boom's exception didn't stop fine from running


async def test_run_due_reports_a_raising_event_to_error_monitoring(monkeypatch: pytest.MonkeyPatch) -> None:
    import zeython.schedule as schedule_module

    reported: list[BaseException] = []
    monkeypatch.setattr(schedule_module, "report_exception", lambda exc, **tags: reported.append(exc))

    schedule = Schedule()

    async def boom() -> None:
        raise RuntimeError("scheduled task blew up")

    schedule.call(boom, name="boom").every_minute()

    await schedule.run_due()

    assert len(reported) == 1
    assert str(reported[0]) == "scheduled task blew up"


def test_iterating_a_schedule_yields_its_events() -> None:
    schedule = Schedule()

    async def noop() -> None:
        pass

    schedule.call(noop, name="a")
    schedule.call(noop, name="b")

    assert [event.name for event in schedule] == ["a", "b"]


# -- ScheduleServiceProvider -----------------------------------------------------------------


def test_service_provider_binds_a_schedule_singleton(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    (tmp_path / "e2e_schedule_module.py").write_text("SCHEDULE_MODULE_IMPORTED = True\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        app = Application(Config.load(tmp_path))
        app.register(ScheduleServiceProvider(app, modules=("e2e_schedule_module",)))

        assert app.container.make(Schedule) is app.container.make(Schedule)
        assert sys.modules["e2e_schedule_module"].SCHEDULE_MODULE_IMPORTED is True
    finally:
        sys.modules.pop("e2e_schedule_module", None)


def test_service_provider_raises_if_the_schedule_module_is_missing(tmp_path: Path) -> None:
    app = Application(Config.load(tmp_path))
    with pytest.raises(ModuleNotFoundError):
        app.register(ScheduleServiceProvider(app, modules=("no_such_schedule_module",)))

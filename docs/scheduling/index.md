# Scheduling

Every project ends up with recurring tasks: prune old records nightly, send a digest email every Monday, refresh a cache every five minutes. Pointing `cron` straight at a shell command works, but the schedule itself then lives outside the app — on a server, in nobody's memory, never reviewed with the code it runs, drifting out of sync with what's actually deployed. `zeython.schedule` keeps it in code instead: one cron entry, total, regardless of how many tasks you actually schedule.

## Defining a schedule

```python
# schedule.py
from main import app
from zeython import Schedule

schedule: Schedule = app.container.make(Schedule)


@schedule.call
async def send_daily_digest() -> None:
    ...


schedule.call(send_daily_digest).daily_at("07:00")
```

`schedule.py` lives at the project root, imported for its side effect of registering events — the same convention `routes/web.py` uses for routes. `schedule.call(callback)` returns a `ScheduledEvent`; chain a frequency method to set when it's due:

```python
schedule.call(send_reminder).every_minute()
schedule.call(sync_inventory).every_five_minutes()
schedule.call(refresh_cache).hourly()
schedule.call(send_digest).daily()
schedule.call(send_digest).daily_at("07:00")
schedule.call(weekly_report).weekly()          # Sunday at midnight
schedule.call(monthly_invoice).monthly()       # 1st of the month at midnight
schedule.call(custom).cron("*/10 8-17 * * 1-5")  # any raw 5-field expression
```

`cron()` supports `*`, single values, comma lists (`1,3,5`), ranges (`1-5`), and step values (`*/15`, `1-10/2`) across all five fields (`minute hour day month weekday`). The weekday field is `0`-`6` (`0` = Sunday) — unlike some cron implementations, `7` isn't accepted as an alias for Sunday.

Day-of-month and weekday follow standard cron's one special-case rule: restrict *both* (neither is `*`) and a match on **either** is enough -- `cron("0 0 1 * 1")` runs at midnight on the 1st of the month, *or* every Monday, not only when the 1st happens to land on a Monday. Restrict just one of the two and it alone decides, same as every other field.

## Setup

```python
# main.py
from zeython import Application, ScheduleServiceProvider

app = Application()
app.register(ScheduleServiceProvider(app))
```

Not registered by default. `ScheduleServiceProvider` binds a `Schedule` singleton into the container and imports `schedule.py` for its side effect — register it once you actually have recurring tasks to define.

## Running it

```bash
zeython schedule run
```

Checks every registered event against the current minute and runs the ones that are due — that's it, no daemon, no loop. Wire it up to fire once a minute:

```text
# crontab -e
* * * * * cd /path/to/project && /path/to/.venv/bin/zeython schedule run >> /var/log/schedule.log 2>&1
```

This is the entire point: **one** cron entry, ever, regardless of how many tasks `schedule.py` grows to define — add a new recurring task by adding a line to `schedule.py`, not by editing a crontab on a server somewhere.

In a container deployment without host cron, run a sidecar loop instead — see [Docker](https://zeython.zaber.dev/docs/docker/#scheduled-tasks).

```bash
zeython schedule list    # every registered task and its cron expression
```

## Dependency injection

A scheduled callback works exactly like a `Job`'s `handle()`: beyond the arguments you pass, any type-hinted parameter is autowired from the container.

```python
@schedule.call
async def send_daily_digest(mailer: Mailer) -> None:
    await mailer.send(...)
```

## Preventing overlapping runs

A task that occasionally runs longer than its own interval (a report that usually takes seconds but sometimes minutes, scheduled every minute) can end up with two copies running against each other. `without_overlapping()` guards against that:

```python
schedule.call(generate_report).every_minute().without_overlapping(for_seconds=300)
```

Implemented via the container's bound `RateLimiter` as a "run at most once per window" gate, keyed by the event's name — a time-based lock, same trade-off Laravel's own `withoutOverlapping()` makes: it expires after `for_seconds` regardless of whether the previous run actually finished, rather than tracking "is it still running" directly.

**Bind `RedisRateLimiter` (see [Redis](https://zeython.zaber.dev/docs/redis/index.md)) for this to do anything at all in the normal case.** `zeython schedule run` is a fresh CLI process every time cron (or the sidecar loop) invokes it — the default `InMemoryRateLimiter`'s lock lives in that process's memory and is gone the moment it exits, so back-to-back invocations never see each other's lock and `without_overlapping()` silently has zero effect. Verified by running `zeython schedule run` twice in a row against the in-memory default: the "overlapping" task ran both times. It only helps in-process (two events racing within one `run_due()` call, or a custom long-lived runner that doesn't shell out per invocation) without a shared backend.

## Handling failures

An event that raises is logged (`zeython.schedule`, at `ERROR`, with the full traceback) and doesn't stop the rest of that run's due events from executing. There's no retry — a scheduled task either ran (successfully or not) this minute, or it'll be due again next time its cron expression matches; build retry logic into the callback itself if a task needs it.

## Testing

`Schedule` and `ScheduledEvent` are plain objects — test a callback directly, or exercise the cron matching with a fixed time:

```python
from datetime import datetime
from zeython.schedule import cron_matches

def test_runs_at_seven_am() -> None:
    assert cron_matches("0 7 * * *", datetime(2026, 1, 1, 7, 0))
    assert not cron_matches("0 7 * * *", datetime(2026, 1, 1, 7, 1))
```

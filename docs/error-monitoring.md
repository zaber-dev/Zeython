# Error Monitoring

An unhandled exception in production is either logged to a file nobody
tails, or it's in front of you the moment it happens. `zeython.error_monitoring`
is the second option: an opt-in [Sentry](https://sentry.io) integration that
reports unhandled request exceptions, jobs that exhaust their retries, and
scheduled tasks that raise -- the same three places `docs/observability.md`,
`docs/queues.md`, and `docs/scheduling.md` already log to, now also sent
somewhere you get paged for.

Requires the `sentry` extra: `pip install zeython[sentry]`.

## Setup

```bash
# .env
SENTRY_DSN=https://examplePublicKey@o0.ingest.sentry.io/0
```

```python
# main.py
from zeython import Application, ErrorMonitoringServiceProvider

app = Application()
app.register(ErrorMonitoringServiceProvider(app))
```

Not registered by default. `ErrorMonitoringServiceProvider.register()` is a
no-op if `SENTRY_DSN` isn't set -- safe to always register, including in
dev/test environments that never configure one.

Configurable via `.env`:

- `SENTRY_DSN` -- required to do anything at all.
- `SENTRY_TRACES_SAMPLE_RATE` -- default `0.0` (errors only, no
  performance tracing).
- `SENTRY_RELEASE` -- optional; `APP_ENV`/`app.env` is passed through as
  the Sentry `environment` automatically.

## What gets reported

- **Unhandled request exceptions** -- anything that reaches
  `unhandled_exception_handler` (a genuine bug, not an `HTTPException`
  subclass like `NotFoundException` -- those are expected control flow,
  handled separately, and never reported). Tagged with `request_id`,
  `path`, and `method`.
- **A queued job that exhausts its retries** (`InMemoryQueue`/`RedisQueue`,
  see [Background Jobs](queues.md)) -- only the final, exhausted attempt,
  not every individual retry. A transient failure a retry then fixes isn't
  worth an alert. Tagged with `job`.
- **A scheduled task that raises** (see [Scheduling](scheduling.md)) --
  every failure, since a scheduled task has no retry concept to begin
  with. Tagged with `scheduled_event`.

## Reporting your own exceptions

`report_exception()` is the same function the framework calls internally
-- use it anywhere you catch and handle an exception yourself but still
want it visible:

```python
from zeython import report_exception

try:
    await risky_operation()
except SomeExpectedError as exc:
    report_exception(exc, operation="risky_operation")
    # handle it and continue -- still worth knowing it happened
```

Always safe to call, whether or not `ErrorMonitoringServiceProvider` is
registered or `sentry-sdk` is even installed -- a no-op in both cases,
never a crash from calling it in an app that hasn't configured error
monitoring.

## Testing

`ErrorMonitoringServiceProvider` and `report_exception()` are both plain,
mockable Python -- monkeypatch `report_exception` where it's imported to
assert it was called, without a real Sentry DSN or network call:

```python
import zeython.queue as queue_module

def test_exhausted_job_is_reported(monkeypatch):
    reported = []
    monkeypatch.setattr(queue_module, "report_exception", lambda exc, **tags: reported.append(exc))
    ...
    assert len(reported) == 1
```

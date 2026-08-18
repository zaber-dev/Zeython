"""Optional error monitoring (Sentry): unhandled request exceptions, jobs
that exhaust their retries, and scheduled tasks that raise all get
reported automatically once configured -- not just logged and forgotten
in a file nobody tails. Requires the ``sentry`` extra: ``pip install
zeython[sentry]``. See docs/error-monitoring.md.

Deliberately not a hard dependency: every call in this module is a no-op
if ``sentry_sdk`` isn't installed or :func:`init_sentry` was never called,
so :func:`report_exception` is always safe to call unconditionally from
framework code (:mod:`zeython.exceptions`, :mod:`zeython.queue`,
:mod:`zeython.schedule`) without those modules taking on a hard
dependency on an optional extra.
"""

from __future__ import annotations

from typing import Any

from zeython.providers import ServiceProvider

_initialized = False


def init_sentry(
    dsn: str,
    *,
    environment: str | None = None,
    release: str | None = None,
    traces_sample_rate: float = 0.0,
) -> None:
    """Initialize the Sentry SDK. Raises ``ImportError`` with an install
    hint if ``sentry_sdk`` isn't installed -- unlike :func:`report_exception`,
    this is only ever called once you've explicitly opted in (a non-empty
    ``SENTRY_DSN``), so failing loudly here is correct: a typo'd DSN with a
    silently-absent SDK would otherwise look like "no errors happened."
    """
    global _initialized
    try:
        import sentry_sdk
    except ImportError as exc:
        raise ImportError(
            "Sentry error monitoring requires sentry-sdk. Install it with: pip install zeython[sentry]"
        ) from exc

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        traces_sample_rate=traces_sample_rate,
    )
    _initialized = True


def report_exception(exc: BaseException, **tags: Any) -> None:
    """Report ``exc`` to Sentry, tagged with ``tags`` -- a no-op if
    :func:`init_sentry` was never called (including if ``sentry_sdk`` isn't
    installed at all), so every call site here is safe regardless of
    whether error monitoring is configured.
    """
    if not _initialized:
        return
    import sentry_sdk

    with sentry_sdk.new_scope() as scope:
        for key, value in tags.items():
            if value is not None:
                scope.set_tag(key, value)
        sentry_sdk.capture_exception(exc)


class ErrorMonitoringServiceProvider(ServiceProvider):
    """Initializes Sentry from ``SENTRY_DSN`` -- not registered by default,
    and a no-op ``register()`` if ``SENTRY_DSN`` isn't set, so it's safe to
    always register even in dev/test environments that don't have one::

        # main.py
        app.register(ErrorMonitoringServiceProvider(app))

    Configurable via ``.env``:

    - ``SENTRY_DSN`` -- required to do anything at all.
    - ``SENTRY_TRACES_SAMPLE_RATE`` -- default ``0.0`` (errors only, no
      performance tracing).
    - ``APP_ENV``/``app.env`` and a git-derived or manually-set release are
      passed through as ``environment``/``release`` if you set
      ``SENTRY_RELEASE``.
    """

    def register(self) -> None:
        dsn = self.config.get("sentry.dsn")
        if not dsn:
            return
        init_sentry(
            dsn,
            environment=self.config.environment,
            release=self.config.get("sentry.release"),
            traces_sample_rate=float(self.config.get("sentry.traces_sample_rate", 0.0)),
        )


__all__ = [
    "ErrorMonitoringServiceProvider",
    "init_sentry",
    "report_exception",
]

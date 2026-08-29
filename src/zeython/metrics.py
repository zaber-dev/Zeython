"""Prometheus-compatible metrics: HTTP request counts, latency histograms,
and custom counters/gauges/histograms your own code defines, all exposed
at ``/metrics`` in the Prometheus text exposition format -- scraped
directly by Prometheus itself, or anything speaking the same format
(Grafana Agent, VictoriaMetrics, Datadog's OpenMetrics ingestion).

No new dependency -- the exposition format is a small, stable, documented
text format (see
https://github.com/prometheus/docs/blob/main/content/docs/instrumenting/exposition_formats.md),
and implementing it directly avoids pulling in the full ``prometheus_client``
package for what's fundamentally a handful of counters this framework
already knows how to compute from the request/response objects it sees.
For distributed tracing (spans, not counters), see :mod:`zeython.tracing`
instead -- correctly implementing *that* wire protocol is not something
worth re-deriving from scratch, unlike this one.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from starlette.requests import Request
from starlette.responses import PlainTextResponse

from zeython.providers import ServiceProvider

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

#: Prometheus client libraries' own default histogram buckets (seconds) --
#: a reasonable spread for HTTP request latency without any tuning.
DEFAULT_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.25,
    0.5,
    0.75,
    1.0,
    2.5,
    5.0,
    7.5,
    10.0,
)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_value(value: float) -> str:
    return str(int(value)) if value == int(value) else repr(float(value))


def _format_labels(labelnames: tuple[str, ...], label_values: tuple[str, ...], extra: list[tuple[str, str]] | None = None) -> str:
    pairs = list(zip(labelnames, label_values, strict=True))
    if extra:
        pairs.extend(extra)
    if not pairs:
        return ""
    inner = ",".join(f'{name}="{_escape(value)}"' for name, value in pairs)
    return "{" + inner + "}"


class Counter:
    """A value that only ever goes up -- request counts, jobs processed,
    errors seen. Construct via :meth:`MetricsRegistry.counter`, not directly.
    """

    metric_type = "counter"

    def __init__(self, name: str, help: str, *, labelnames: Iterable[str] = ()) -> None:
        self.name = name
        self.help = help
        self.labelnames = tuple(labelnames)
        self._values: dict[tuple[str, ...], float] = defaultdict(float)

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        if amount < 0:
            raise ValueError("Counter.inc() amount must not be negative -- use a Gauge if the value can decrease.")
        self._values[self._key(labels)] += amount

    def _key(self, labels: dict[str, str]) -> tuple[str, ...]:
        return tuple(str(labels.get(name, "")) for name in self.labelnames)

    def render_samples(self) -> list[str]:
        return [
            f"{self.name}{_format_labels(self.labelnames, key)} {_format_value(value)}"
            for key, value in self._values.items()
        ]


class Gauge:
    """A value that can go up or down -- in-flight requests, queue depth,
    connections open right now. Construct via :meth:`MetricsRegistry.gauge`.
    """

    metric_type = "gauge"

    def __init__(self, name: str, help: str, *, labelnames: Iterable[str] = ()) -> None:
        self.name = name
        self.help = help
        self.labelnames = tuple(labelnames)
        self._values: dict[tuple[str, ...], float] = defaultdict(float)

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        self._values[self._key(labels)] += amount

    def dec(self, amount: float = 1.0, **labels: str) -> None:
        self._values[self._key(labels)] -= amount

    def set(self, value: float, **labels: str) -> None:
        self._values[self._key(labels)] = value

    def _key(self, labels: dict[str, str]) -> tuple[str, ...]:
        return tuple(str(labels.get(name, "")) for name in self.labelnames)

    def render_samples(self) -> list[str]:
        return [
            f"{self.name}{_format_labels(self.labelnames, key)} {_format_value(value)}"
            for key, value in self._values.items()
        ]


class Histogram:
    """A distribution of observed values, bucketed by upper bound -- request
    durations, payload sizes. Construct via :meth:`MetricsRegistry.histogram`.

    Renders as Prometheus expects: one cumulative ``_bucket`` sample per
    bound (each includes every observation at or below it, plus a final
    ``le="+Inf"`` bucket equal to the total count), plus ``_sum``/``_count``.
    """

    metric_type = "histogram"

    def __init__(self, name: str, help: str, *, buckets: Iterable[float] = DEFAULT_BUCKETS, labelnames: Iterable[str] = ()) -> None:
        self.name = name
        self.help = help
        self.buckets: tuple[float, ...] = (*sorted(buckets), float("inf"))
        self.labelnames = tuple(labelnames)
        self._bucket_counts: dict[tuple[str, ...], list[int]] = {}
        self._sums: dict[tuple[str, ...], float] = defaultdict(float)
        self._counts: dict[tuple[str, ...], int] = defaultdict(int)

    def observe(self, value: float, **labels: str) -> None:
        key = self._key(labels)
        counts = self._bucket_counts.setdefault(key, [0] * len(self.buckets))
        for i, bound in enumerate(self.buckets):
            if value <= bound:
                counts[i] += 1
        self._sums[key] += value
        self._counts[key] += 1

    def _key(self, labels: dict[str, str]) -> tuple[str, ...]:
        return tuple(str(labels.get(name, "")) for name in self.labelnames)

    def render_samples(self) -> list[str]:
        lines = []
        for key, counts in self._bucket_counts.items():
            for bound, count in zip(self.buckets, counts, strict=True):
                le = "+Inf" if bound == float("inf") else _format_value(bound)
                labels = _format_labels(self.labelnames, key, extra=[("le", le)])
                lines.append(f"{self.name}_bucket{labels} {count}")
            base_labels = _format_labels(self.labelnames, key)
            lines.append(f"{self.name}_sum{base_labels} {_format_value(self._sums[key])}")
            lines.append(f"{self.name}_count{base_labels} {self._counts[key]}")
        return lines


Metric = Counter | Gauge | Histogram


class MetricsRegistry:
    """Owns every metric an app defines and renders them all to the
    Prometheus text format. Bound in the container by
    :class:`MetricsServiceProvider` -- resolve it to define your own
    metrics alongside the built-in HTTP ones::

        registry: MetricsRegistry = request.app.state.container.make(MetricsRegistry)
        ORDERS_PLACED = registry.counter("orders_placed_total", "Orders placed.")
        ORDERS_PLACED.inc()

    ``counter``/``gauge``/``histogram`` are idempotent by name: calling one
    again with the same name returns the *same* metric object rather than
    registering a duplicate (which would otherwise render as two conflicting
    blocks under one name -- invalid Prometheus output) -- safe to call from
    inside a request handler on every request rather than only once at
    startup, though defining it once at module level and reusing the object
    is both more efficient and how these are conventionally used.
    """

    def __init__(self) -> None:
        self._metrics: list[Metric] = []
        self._by_name: dict[str, Metric] = {}

    def _get_or_create(self, name: str, factory: Any) -> Any:
        existing = self._by_name.get(name)
        if existing is not None:
            return existing
        metric = factory()
        self._by_name[name] = metric
        self._metrics.append(metric)
        return metric

    def counter(self, name: str, help: str, *, labelnames: Iterable[str] = ()) -> Counter:
        metric = self._get_or_create(name, lambda: Counter(name, help, labelnames=labelnames))
        if not isinstance(metric, Counter):
            raise ValueError(f"{name!r} is already registered as a {metric.metric_type}, not a counter.")
        return metric

    def gauge(self, name: str, help: str, *, labelnames: Iterable[str] = ()) -> Gauge:
        metric = self._get_or_create(name, lambda: Gauge(name, help, labelnames=labelnames))
        if not isinstance(metric, Gauge):
            raise ValueError(f"{name!r} is already registered as a {metric.metric_type}, not a gauge.")
        return metric

    def histogram(
        self, name: str, help: str, *, buckets: Iterable[float] = DEFAULT_BUCKETS, labelnames: Iterable[str] = ()
    ) -> Histogram:
        metric = self._get_or_create(name, lambda: Histogram(name, help, buckets=buckets, labelnames=labelnames))
        if not isinstance(metric, Histogram):
            raise ValueError(f"{name!r} is already registered as a {metric.metric_type}, not a histogram.")
        return metric

    def render(self) -> str:
        """Every registered metric, in the Prometheus text exposition
        format -- what :class:`MetricsServiceProvider`'s ``/metrics``
        endpoint returns verbatim.
        """
        lines: list[str] = []
        for metric in self._metrics:
            lines.append(f"# HELP {metric.name} {metric.help}")
            lines.append(f"# TYPE {metric.name} {metric.metric_type}")
            lines.extend(metric.render_samples())
        return ("\n".join(lines) + "\n") if lines else ""


def _build_path_map(app: Any) -> dict[Any, str]:
    mapping: dict[Any, str] = {}
    for route in getattr(app, "routes", ()):
        endpoint = getattr(route, "endpoint", None)
        path = getattr(route, "path", None)
        if endpoint is not None and path is not None:
            mapping[endpoint] = path
    return mapping


class MetricsMiddleware:
    """Pure ASGI middleware: records ``http_requests_total``,
    ``http_request_duration_seconds``, and ``http_requests_in_progress``
    for every request, grouped by the route's own path *template*
    (``/posts/{id}``, not ``/posts/42``) rather than the literal URL --
    a per-ID label would mean an ever-growing, unbounded set of label
    combinations for anything with a numeric or UUID path parameter.
    A request that matched no route at all (a 404, or a probing bot) is
    grouped under ``"unmatched"`` for the same reason.
    """

    def __init__(self, app: Any, *, registry: MetricsRegistry, exclude_path: str | None = None) -> None:
        self.app = app
        self.exclude_path = exclude_path
        self._path_by_endpoint: dict[Any, str] | None = None
        self.requests_total = registry.counter(
            "http_requests_total", "Total HTTP requests.", labelnames=("method", "path", "status")
        )
        self.request_duration = registry.histogram(
            "http_request_duration_seconds", "HTTP request duration in seconds.", labelnames=("method", "path")
        )
        self.requests_in_progress = registry.gauge(
            "http_requests_in_progress", "HTTP requests currently being processed.", labelnames=("method",)
        )

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("path") == self.exclude_path:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        self.requests_in_progress.inc(method=method)
        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - start
            if self._path_by_endpoint is None:
                self._path_by_endpoint = _build_path_map(scope.get("app"))
            path = self._path_by_endpoint.get(scope.get("endpoint"), "unmatched")
            self.requests_total.inc(method=method, path=path, status=str(status_code))
            self.request_duration.observe(duration, method=method, path=path)
            self.requests_in_progress.dec(method=method)


class MetricsServiceProvider(ServiceProvider):
    """Binds a :class:`MetricsRegistry` into the container, instruments
    every request via :class:`MetricsMiddleware`, and serves the result at
    ``/metrics`` (Prometheus text format)::

        app.register(MetricsServiceProvider(app))

    Zero-config and safe to always register -- the built-in HTTP metrics
    have no cardinality risk (see :class:`MetricsMiddleware`) and add a
    single dict lookup and a few increments per request. Configurable via
    ``.env``:

    - ``METRICS_ENABLED`` -- default ``true``.
    - ``METRICS_PATH`` -- default ``/metrics``.
    """

    def register(self) -> None:
        self.container.singleton(MetricsRegistry, MetricsRegistry)

    def boot(self) -> None:
        if not bool(self.config.get("metrics.enabled", True)):
            return
        path = self.config.get("metrics.path", "/metrics")
        registry = self.container.make(MetricsRegistry)

        self.app.add_middleware(MetricsMiddleware, registry=registry, exclude_path=path)

        async def metrics(request: Request) -> PlainTextResponse:
            return PlainTextResponse(registry.render(), media_type=CONTENT_TYPE)

        self.app.get(path, name="metrics")(metrics)


__all__ = [
    "CONTENT_TYPE",
    "DEFAULT_BUCKETS",
    "Counter",
    "Gauge",
    "Histogram",
    "MetricsMiddleware",
    "MetricsRegistry",
    "MetricsServiceProvider",
]

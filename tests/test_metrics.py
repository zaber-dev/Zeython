"""Tests for zeython.metrics -- Prometheus-compatible counters, gauges,
histograms, and the HTTP instrumentation middleware/provider built on them.
"""

from pathlib import Path

import pytest
from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsMiddleware,
    MetricsRegistry,
    MetricsServiceProvider,
)
from zeython.testing import client

# -- Counter --------------------------------------------------------------------


def test_counter_increments_by_one_by_default() -> None:
    counter = Counter("jobs_processed_total", "Jobs processed.")
    counter.inc()
    counter.inc()
    assert counter.render_samples() == ["jobs_processed_total 2"]


def test_counter_increments_by_a_given_amount() -> None:
    counter = Counter("bytes_sent_total", "Bytes sent.")
    counter.inc(5)
    counter.inc(2.5)
    assert counter.render_samples() == ["bytes_sent_total 7.5"]


def test_counter_rejects_negative_increments() -> None:
    counter = Counter("jobs_processed_total", "Jobs processed.")
    with pytest.raises(ValueError, match="must not be negative"):
        counter.inc(-1)


def test_counter_tracks_separate_totals_per_label_combination() -> None:
    counter = Counter("http_requests_total", "HTTP requests.", labelnames=("method", "status"))
    counter.inc(method="GET", status="200")
    counter.inc(method="GET", status="200")
    counter.inc(method="POST", status="500")

    samples = set(counter.render_samples())
    assert samples == {
        'http_requests_total{method="GET",status="200"} 2',
        'http_requests_total{method="POST",status="500"} 1',
    }


# -- Gauge ------------------------------------------------------------------------


def test_gauge_inc_dec_and_set() -> None:
    gauge = Gauge("connections_open", "Open connections.")
    gauge.inc()
    gauge.inc(2)
    gauge.dec()
    assert gauge.render_samples() == ["connections_open 2"]

    gauge.set(10)
    assert gauge.render_samples() == ["connections_open 10"]


# -- Histogram --------------------------------------------------------------------


def test_histogram_renders_cumulative_buckets_plus_inf_sum_and_count() -> None:
    histogram = Histogram("request_size_bytes", "Request size.", buckets=(1.0, 5.0))
    histogram.observe(0.5)
    histogram.observe(3.0)
    histogram.observe(10.0)

    lines = histogram.render_samples()
    as_dict = {line.split(" ")[0]: line.split(" ")[1] for line in lines}

    assert as_dict['request_size_bytes_bucket{le="1"}'] == "1"
    assert as_dict['request_size_bytes_bucket{le="5"}'] == "2"
    assert as_dict['request_size_bytes_bucket{le="+Inf"}'] == "3"
    assert as_dict["request_size_bytes_sum"] == "13.5"
    assert as_dict["request_size_bytes_count"] == "3"


def test_histogram_tracks_separate_buckets_per_label_combination() -> None:
    histogram = Histogram("latency_seconds", "Latency.", buckets=(1.0,), labelnames=("route",))
    histogram.observe(0.1, route="/a")
    histogram.observe(2.0, route="/b")

    lines = histogram.render_samples()
    assert 'latency_seconds_bucket{route="/a",le="1"} 1' in lines
    assert 'latency_seconds_bucket{route="/a",le="+Inf"} 1' in lines
    assert 'latency_seconds_bucket{route="/b",le="1"} 0' in lines
    assert 'latency_seconds_bucket{route="/b",le="+Inf"} 1' in lines


# -- Label escaping -----------------------------------------------------------------


def test_label_values_are_escaped() -> None:
    counter = Counter("errors_total", "Errors.", labelnames=("message",))
    counter.inc(message='a "quoted"\nvalue')
    assert counter.render_samples() == [r'errors_total{message="a \"quoted\"\nvalue"} 1']


# -- MetricsRegistry ----------------------------------------------------------------


def test_registry_counter_is_idempotent_by_name() -> None:
    registry = MetricsRegistry()
    a = registry.counter("orders_total", "Orders.")
    b = registry.counter("orders_total", "Orders.")
    assert a is b


def test_registry_raises_on_type_mismatch_for_the_same_name() -> None:
    registry = MetricsRegistry()
    registry.counter("thing_total", "A thing.")
    with pytest.raises(ValueError, match="already registered as a counter"):
        registry.gauge("thing_total", "A thing.")


def test_registry_raises_when_requesting_a_counter_for_a_gauge_name() -> None:
    registry = MetricsRegistry()
    registry.gauge("thing_open", "A thing.")
    with pytest.raises(ValueError, match="already registered as a gauge"):
        registry.counter("thing_open", "A thing.")


def test_registry_raises_when_requesting_a_histogram_for_a_counter_name() -> None:
    registry = MetricsRegistry()
    registry.counter("thing_total", "A thing.")
    with pytest.raises(ValueError, match="already registered as a counter"):
        registry.histogram("thing_total", "A thing.")


def test_registry_render_includes_help_and_type_lines() -> None:
    registry = MetricsRegistry()
    counter = registry.counter("widgets_total", "Widgets made.")
    counter.inc()

    output = registry.render()
    assert "# HELP widgets_total Widgets made." in output
    assert "# TYPE widgets_total counter" in output
    assert "widgets_total 1" in output


def test_registry_render_is_empty_string_with_no_metrics() -> None:
    assert MetricsRegistry().render() == ""


# -- MetricsMiddleware / MetricsServiceProvider --------------------------------------


async def _make_app(tmp_path: Path) -> Application:
    (tmp_path / ".env").write_text("APP_SECRET_KEY=test\n")
    app = Application(Config.load(tmp_path))
    app.register(MetricsServiceProvider(app))
    return app


async def test_metrics_endpoint_reports_instrumented_requests(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    @app.get("/widgets/{id}")
    async def widget(request):
        return JSONResponse({"id": request.path_params["id"]})

    async with client(app) as http:
        await http.get("/widgets/1")
        await http.get("/widgets/2")
        metrics_response = await http.get("/metrics")

    assert metrics_response.status_code == 200
    assert metrics_response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"
    body = metrics_response.text

    # Grouped by path *template*, not the literal /widgets/1 vs /widgets/2 URL.
    assert 'http_requests_total{method="GET",path="/widgets/{id}",status="200"} 2' in body
    assert "http_request_duration_seconds_count" in body
    assert 'http_requests_in_progress{method="GET"} 0' in body


async def test_unmatched_requests_are_grouped_under_unmatched(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        await http.get("/does-not-exist")
        metrics_response = await http.get("/metrics")

    assert 'http_requests_total{method="GET",path="unmatched",status="404"} 1' in metrics_response.text


async def test_metrics_endpoint_itself_is_excluded_from_its_own_counts(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)

    async with client(app) as http:
        first = await http.get("/metrics")
        second = await http.get("/metrics")

    assert "/metrics" not in first.text
    assert "/metrics" not in second.text


async def test_metrics_path_is_configurable(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("APP_SECRET_KEY=test\nMETRICS_PATH=/internal/metrics\n")
    app = Application(Config.load(tmp_path))
    app.register(MetricsServiceProvider(app))

    async with client(app) as http:
        default_path = await http.get("/metrics")
        configured_path = await http.get("/internal/metrics")

    assert default_path.status_code == 404
    assert configured_path.status_code == 200


async def test_provider_is_a_no_op_when_metrics_disabled(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("APP_SECRET_KEY=test\nMETRICS_ENABLED=false\n")
    app = Application(Config.load(tmp_path))
    app.register(MetricsServiceProvider(app))

    async with client(app) as http:
        response = await http.get("/metrics")

    assert response.status_code == 404


async def test_middleware_records_a_custom_metric_defined_by_application_code(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    registry = app.container.make(MetricsRegistry)
    orders_placed = registry.counter("orders_placed_total", "Orders placed.")

    @app.post("/orders")
    async def create_order(request):
        orders_placed.inc()
        return JSONResponse({}, status_code=201)

    async with client(app) as http:
        await http.post("/orders")
        await http.post("/orders")
        metrics_response = await http.get("/metrics")

    assert "orders_placed_total 2" in metrics_response.text


def test_middleware_can_be_constructed_directly_with_a_registry() -> None:
    registry = MetricsRegistry()
    middleware = MetricsMiddleware(app=object(), registry=registry, exclude_path="/metrics")
    assert middleware.requests_total is registry.counter(
        "http_requests_total", "HTTP requests.", labelnames=("method", "path", "status")
    )

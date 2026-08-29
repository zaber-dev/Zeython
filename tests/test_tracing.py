"""Tests for zeython.tracing -- optional OpenTelemetry request tracing.

Success-path tests run against the real ``opentelemetry-sdk`` (a dev
dependency) using its own ``InMemorySpanExporter``, purpose-built for
tests like these -- there's no reason to fake OpenTelemetry's own SDK.
Only the "extra not installed" path fakes the import, the same way
test_error_monitoring.py does for the analogous Sentry extra.
"""

from pathlib import Path
from typing import Any

import pytest
from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.testing import client
from zeython.tracing import TracingServiceProvider, init_tracing


@pytest.fixture(autouse=True)
def _reset_global_tracer_provider() -> None:
    # The OpenTelemetry API only allows the global tracer provider to be
    # set once per process -- reset its private "set once" guard between
    # tests so each test's init_tracing() call actually takes effect
    # instead of silently keeping whatever an earlier test installed.
    from opentelemetry import trace

    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE = trace.Once()


# -- init_tracing() -----------------------------------------------------------------


def test_init_tracing_raises_a_clear_import_error_without_the_extra_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _fake_import(name: str, *args: object, **kwargs: object):
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            raise ImportError("no module named opentelemetry")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    with pytest.raises(ImportError, match=r"pip install zeython\[otel\]"):
        init_tracing(service_name="test-app")


async def test_middleware_passes_non_http_scopes_through_untouched() -> None:
    from zeython.tracing import TracingMiddleware

    calls = []

    async def app(scope: dict, receive: Any, send: Any) -> None:
        calls.append(scope["type"])

    middleware = TracingMiddleware(app)
    await middleware({"type": "lifespan"}, None, None)

    assert calls == ["lifespan"]


def test_init_tracing_returns_a_tracer_provider_and_sets_it_globally() -> None:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    provider = init_tracing(service_name="test-app", exporter=InMemorySpanExporter())

    assert isinstance(provider, TracerProvider)
    assert trace.get_tracer_provider() is provider


# -- sampling -------------------------------------------------------------------------


def test_sample_ratio_is_wrapped_in_parent_based() -> None:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    provider = init_tracing(service_name="test-app", exporter=InMemorySpanExporter(), sample_ratio=0.25)

    assert isinstance(provider.sampler, ParentBased)
    assert isinstance(provider.sampler._root, TraceIdRatioBased)
    assert provider.sampler._root._rate == 0.25


@pytest.mark.parametrize("bad_ratio", [-0.1, 1.1, 2.0])
def test_init_tracing_rejects_an_out_of_range_sample_ratio(bad_ratio: float) -> None:
    with pytest.raises(ValueError, match="sample_ratio must be between 0.0 and 1.0"):
        init_tracing(service_name="test-app", sample_ratio=bad_ratio)


def test_an_explicit_sampler_takes_precedence_over_sample_ratio() -> None:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.sdk.trace.sampling import ALWAYS_OFF

    provider = init_tracing(
        service_name="test-app", exporter=InMemorySpanExporter(), sample_ratio=1.0, sampler=ALWAYS_OFF
    )

    assert provider.sampler is ALWAYS_OFF


# -- TracingMiddleware / TracingServiceProvider --------------------------------------


async def _make_app(tmp_path: Path):
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    (tmp_path / ".env").write_text("APP_SECRET_KEY=test\n")
    app = Application(Config.load(tmp_path))
    exporter = InMemorySpanExporter()
    app.register(TracingServiceProvider(app, service_name="test-app", exporter=exporter))
    return app, exporter


async def test_a_request_produces_a_server_span_with_http_attributes(tmp_path: Path) -> None:
    app, exporter = await _make_app(tmp_path)

    @app.get("/widgets/{id}")
    async def widget(request):
        return JSONResponse({"id": request.path_params["id"]})

    async with client(app) as http:
        response = await http.get("/widgets/1")

    assert response.status_code == 200

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    provider.force_flush()

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "GET /widgets/1"
    assert span.attributes["http.method"] == "GET"
    assert span.attributes["http.target"] == "/widgets/1"
    assert span.attributes["http.status_code"] == 200


async def test_an_unhandled_exception_is_recorded_on_the_span(tmp_path: Path) -> None:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.trace import StatusCode

    app, exporter = await _make_app(tmp_path)

    @app.get("/boom")
    async def boom(request):
        raise RuntimeError("kaboom")

    async with client(app) as http:
        with pytest.raises(RuntimeError):
            await http.get("/boom")

    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    provider.force_flush()

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.ERROR
    assert any(event.name == "exception" for event in span.events)


# -- baggage / inject_headers ----------------------------------------------------------


def test_current_baggage_returns_none_when_unset() -> None:
    from zeython.tracing import current_baggage

    assert current_baggage("tenant_id") is None


async def test_set_baggage_is_readable_within_the_same_request(tmp_path: Path) -> None:
    from zeython.tracing import current_baggage, set_baggage

    app, _ = await _make_app(tmp_path)
    seen = {}

    @app.get("/whoami")
    async def whoami(request):
        set_baggage("tenant_id", "42")
        seen["tenant_id"] = current_baggage("tenant_id")
        return JSONResponse({"tenant_id": seen["tenant_id"]})

    async with client(app) as http:
        response = await http.get("/whoami")

    assert response.json() == {"tenant_id": "42"}
    assert seen["tenant_id"] == "42"


async def test_incoming_baggage_header_is_readable_via_current_baggage(tmp_path: Path) -> None:
    from zeython.tracing import current_baggage

    app, _ = await _make_app(tmp_path)
    seen = {}

    @app.get("/whoami")
    async def whoami(request):
        seen["tenant_id"] = current_baggage("tenant_id")
        return JSONResponse({})

    async with client(app) as http:
        await http.get("/whoami", headers={"baggage": "tenant_id=99"})

    assert seen["tenant_id"] == "99"


async def test_baggage_does_not_leak_across_requests(tmp_path: Path) -> None:
    from zeython.tracing import current_baggage, set_baggage

    app, _ = await _make_app(tmp_path)
    seen = []

    @app.get("/set")
    async def set_it(request):
        set_baggage("tenant_id", "42")
        return JSONResponse({})

    @app.get("/read")
    async def read_it(request):
        seen.append(current_baggage("tenant_id"))
        return JSONResponse({})

    async with client(app) as http:
        await http.get("/set")
        await http.get("/read")

    assert seen == [None]


async def test_inject_headers_includes_traceparent_and_baggage(tmp_path: Path) -> None:
    from zeython.tracing import inject_headers, set_baggage

    app, _ = await _make_app(tmp_path)
    seen = {}

    @app.get("/call-downstream")
    async def call_downstream(request):
        set_baggage("tenant_id", "42")
        seen["headers"] = inject_headers({"Authorization": "Bearer secret"})
        return JSONResponse({})

    async with client(app) as http:
        await http.get("/call-downstream")

    headers = seen["headers"]
    assert "traceparent" in headers
    assert headers["baggage"] == "tenant_id=42"
    assert headers["Authorization"] == "Bearer secret"  # merged in, not clobbered


def test_inject_headers_works_outside_a_request_too() -> None:
    from zeython.tracing import inject_headers

    # No active span at all -- still returns a dict (an empty/default
    # traceparent for "no trace in progress"), never raises.
    headers = inject_headers()
    assert isinstance(headers, dict)

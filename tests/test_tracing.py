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

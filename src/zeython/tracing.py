"""Optional distributed tracing (OpenTelemetry): one span per request,
W3C ``traceparent`` propagation across service calls, and exception
recording on the active span -- exported wherever you point it (a local
console for development, or a real collector like Jaeger, Tempo, or an
OTLP-speaking vendor backend in production). Requires the ``otel`` extra:
``pip install zeython[otel]``. See docs/tracing.md.

For request counts and latency histograms (metrics, not spans), see
:mod:`zeython.metrics` instead -- the two are complementary and commonly
run together, but answer different questions ("how many/how slow, in
aggregate" vs. "what exactly happened on this one request").

Deliberately not a hard dependency, and deliberately does not depend on
any specific exporter package: :func:`init_tracing` takes any
``SpanExporter`` you already have configured (an OTLP exporter, a
vendor's own, or the SDK's own ``ConsoleSpanExporter`` if you pass none),
so the required ``otel`` extra is just the API + SDK, never a specific
backend's client library.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from zeython.providers import ServiceProvider

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SpanExporter

_tracer_provider: Any = None


def init_tracing(*, service_name: str, exporter: SpanExporter | None = None) -> TracerProvider:
    """Initialize the OpenTelemetry SDK with a single ``BatchSpanProcessor``
    exporting to ``exporter`` (a ``ConsoleSpanExporter`` -- printing spans to
    stdout -- if none is given, so tracing is inspectable with zero
    configuration before you've wired up a real collector). Raises
    ``ImportError`` with an install hint if the ``otel`` extra isn't
    installed.

    Registers the returned provider as the global tracer provider, so
    application code can also do ``from opentelemetry import trace;
    trace.get_tracer(__name__)`` directly rather than going through this
    module.
    """
    global _tracer_provider
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    except ImportError as exc:
        raise ImportError(
            "Tracing requires the OpenTelemetry SDK. Install it with: pip install zeython[otel]"
        ) from exc

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(exporter or ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _tracer_provider = provider
    return provider


class TracingMiddleware:
    """Pure ASGI middleware: wraps every HTTP request in a server span named
    ``"{method} {path}"``, extracting any incoming W3C ``traceparent``
    header so a span started upstream (another service, a load balancer)
    continues as this request's parent rather than starting a new trace.

    Sets the conventional ``http.method``/``http.target``/
    ``http.status_code`` span attributes, and on an unhandled exception
    records it on the span and marks the span's status as an error before
    re-raising -- the exception still propagates to Zeython's own error
    handling unchanged, this only annotates the trace.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from opentelemetry import trace
        from opentelemetry.propagate import extract
        from opentelemetry.trace import SpanKind, Status, StatusCode

        headers = {key.decode("latin-1"): value.decode("latin-1") for key, value in scope.get("headers", [])}
        context = extract(headers)
        method = scope.get("method", "GET")
        path = scope.get("path", "")
        tracer = trace.get_tracer("zeython")
        status_code = 500

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        with tracer.start_as_current_span(f"{method} {path}", context=context, kind=SpanKind.SERVER) as span:
            span.set_attribute("http.method", method)
            span.set_attribute("http.target", path)
            try:
                await self.app(scope, receive, send_wrapper)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR))
                raise
            finally:
                span.set_attribute("http.status_code", status_code)


class TracingServiceProvider(ServiceProvider):
    """Initializes OpenTelemetry tracing and instruments every request via
    :class:`TracingMiddleware`::

        app.register(TracingServiceProvider(app, service_name="my-blog"))

    Pass ``exporter`` for a real backend (an OTLP exporter you've installed
    and configured separately); without one, spans print to the console --
    useful for confirming tracing is wired up before you've picked a
    backend. Requires the ``otel`` extra: ``pip install zeython[otel]``.
    """

    def __init__(self, app: Any, *, service_name: str, exporter: SpanExporter | None = None) -> None:
        super().__init__(app)
        self.service_name = service_name
        self.exporter = exporter

    def boot(self) -> None:
        init_tracing(service_name=self.service_name, exporter=self.exporter)
        self.app.add_middleware(TracingMiddleware)


__all__ = [
    "TracingMiddleware",
    "TracingServiceProvider",
    "init_tracing",
]

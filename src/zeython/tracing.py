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
    from opentelemetry.sdk.trace.sampling import Sampler

_tracer_provider: Any = None


def init_tracing(
    *,
    service_name: str,
    exporter: SpanExporter | None = None,
    sample_ratio: float | None = None,
    sampler: Sampler | None = None,
) -> TracerProvider:
    """Initialize the OpenTelemetry SDK with a single ``BatchSpanProcessor``
    exporting to ``exporter`` (a ``ConsoleSpanExporter`` -- printing spans to
    stdout -- if none is given, so tracing is inspectable with zero
    configuration before you've wired up a real collector). Raises
    ``ImportError`` with an install hint if the ``otel`` extra isn't
    installed.

    By default every request is traced (the SDK's own default sampler,
    ``ParentBased(ALWAYS_ON)``) -- fine for moderate traffic, and the
    right choice while you're still confirming tracing works at all.
    Pass ``sample_ratio`` (0.0-1.0) once request volume makes tracing
    *everything* too expensive to export/store -- ``0.1`` traces roughly
    10% of requests. It's wrapped in ``ParentBased`` automatically, so a
    trace already sampled by an upstream service (its decision arrives via
    the incoming ``traceparent`` header) is always continued regardless of
    this service's own ratio -- a distributed trace should never have a
    gap in the middle because one hop in the chain independently decided
    not to sample. Pass ``sampler`` instead for anything else (a rate-limiting
    sampler, one driven by your own config) -- it takes precedence over
    ``sample_ratio`` if both are given.

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
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    except ImportError as exc:
        raise ImportError(
            "Tracing requires the OpenTelemetry SDK. Install it with: pip install zeython[otel]"
        ) from exc

    if sampler is None and sample_ratio is not None:
        if not 0.0 <= sample_ratio <= 1.0:
            raise ValueError(f"sample_ratio must be between 0.0 and 1.0, got {sample_ratio!r}")
        sampler = ParentBased(TraceIdRatioBased(sample_ratio))

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}), sampler=sampler)
    provider.add_span_processor(BatchSpanProcessor(exporter or ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _tracer_provider = provider
    return provider


def current_baggage(key: str) -> str | None:
    """The value of baggage member ``key`` on the current request, or
    ``None`` if unset -- baggage set by this service via :func:`set_baggage`,
    or received from an upstream service's own W3C ``baggage`` header
    (extracted automatically by :class:`TracingMiddleware`, the same way
    it extracts ``traceparent``).

    Unlike a span attribute, baggage travels *with* the trace across
    service boundaries -- set once, readable by every downstream service
    the request reaches, not just visible in this one span. Don't put
    anything sensitive in it: it rides in plain-text request headers.
    """
    from opentelemetry import baggage

    value = baggage.get_baggage(key)
    return None if value is None else str(value)


def set_baggage(key: str, value: str) -> None:
    """Attach a baggage member to the current request's trace context, for
    the rest of the request -- visible to :func:`current_baggage` calls
    later in the same request, to child spans, and (via
    :func:`inject_headers`) to any downstream service this request calls::

        set_baggage("tenant_id", str(tenant.id))

    Scoped to the current request the same way a span is: the ASGI
    middleware's own context is detached automatically when the request
    finishes, so this never leaks into a later, unrelated request.
    """
    from opentelemetry import baggage
    from opentelemetry import context as otel_context

    otel_context.attach(baggage.set_baggage(key, value))


def inject_headers(headers: dict[str, str] | None = None) -> dict[str, str]:
    """The current trace context (and any baggage) encoded as W3C
    ``traceparent``/``baggage`` headers, merged into ``headers`` -- pass
    the result to whatever HTTP client you use for an outbound call, so
    the trace continues in the service you're calling instead of starting
    a new, disconnected one there::

        response = await http.get(url, headers=inject_headers())
        response = await http.post(url, headers=inject_headers({"Authorization": f"Bearer {token}"}))
    """
    from opentelemetry.propagate import inject

    carrier = dict(headers) if headers else {}
    inject(carrier)
    return carrier


class TracingMiddleware:
    """Pure ASGI middleware: wraps every HTTP request in a server span named
    ``"{method} {path}"``, extracting any incoming W3C ``traceparent``
    header so a span started upstream (another service, a load balancer)
    continues as this request's parent rather than starting a new trace --
    and, in the same step, any incoming W3C ``baggage`` header, so
    :func:`current_baggage` sees whatever an upstream service attached,
    for the whole lifetime of this request.

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

        from opentelemetry import context as otel_context
        from opentelemetry import trace
        from opentelemetry.propagate import extract
        from opentelemetry.trace import SpanKind, Status, StatusCode

        headers = {key.decode("latin-1"): value.decode("latin-1") for key, value in scope.get("headers", [])}
        method = scope.get("method", "GET")
        path = scope.get("path", "")
        tracer = trace.get_tracer("zeython")
        status_code = 500

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        # Attached explicitly (not just passed as start_as_current_span's
        # own context= argument) so any baggage the extracted context
        # carries becomes part of the *ambient* context for the rest of
        # this request -- start_as_current_span's context= only feeds the
        # new span's parent linkage, it doesn't itself make the passed-in
        # context "current" the way attach() does, so baggage riding in it
        # would otherwise never reach current_baggage() calls made later.
        token = otel_context.attach(extract(headers))
        try:
            with tracer.start_as_current_span(f"{method} {path}", kind=SpanKind.SERVER) as span:
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
        finally:
            otel_context.detach(token)


class TracingServiceProvider(ServiceProvider):
    """Initializes OpenTelemetry tracing and instruments every request via
    :class:`TracingMiddleware`::

        app.register(TracingServiceProvider(app, service_name="my-blog"))

    Pass ``exporter`` for a real backend (an OTLP exporter you've installed
    and configured separately); without one, spans print to the console --
    useful for confirming tracing is wired up before you've picked a
    backend. ``sample_ratio``/``sampler`` are passed straight through to
    :func:`init_tracing` -- see there for what each does. Requires the
    ``otel`` extra: ``pip install zeython[otel]``.
    """

    def __init__(
        self,
        app: Any,
        *,
        service_name: str,
        exporter: SpanExporter | None = None,
        sample_ratio: float | None = None,
        sampler: Sampler | None = None,
    ) -> None:
        super().__init__(app)
        self.service_name = service_name
        self.exporter = exporter
        self.sample_ratio = sample_ratio
        self.sampler = sampler

    def boot(self) -> None:
        init_tracing(
            service_name=self.service_name,
            exporter=self.exporter,
            sample_ratio=self.sample_ratio,
            sampler=self.sampler,
        )
        self.app.add_middleware(TracingMiddleware)


__all__ = [
    "TracingMiddleware",
    "TracingServiceProvider",
    "current_baggage",
    "init_tracing",
    "inject_headers",
    "set_baggage",
]

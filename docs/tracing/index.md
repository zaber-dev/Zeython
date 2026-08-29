# Tracing

Distributed tracing via [OpenTelemetry](https://opentelemetry.io/): one span per request, propagated across service calls via the standard W3C `traceparent` header, exported wherever you point it — a local console for development, or a real collector (Jaeger, Tempo, an OTLP-speaking vendor backend) in production.

For request counts and latency histograms (aggregate numbers, not per-request spans), see [Metrics](https://zeython.zaber.dev/docs/metrics/index.md) instead — the two are complementary and commonly run together, but answer different questions: "how many/how slow, in aggregate" vs. "what exactly happened on this one request, across every service it touched."

Requires the `otel` extra:

```bash
pip install "zeython[otel]"
```

Deliberately not a hard dependency, and deliberately does not depend on any specific exporter package: `init_tracing()` takes any `SpanExporter` you already have configured (an OTLP exporter, a vendor's own, or the SDK's own `ConsoleSpanExporter` if you pass none), so the required `otel` extra is just the OpenTelemetry API + SDK, never a specific backend's client library.

## Setup

```python
# main.py
from zeython import Application, TracingServiceProvider

app = Application()
app.register(TracingServiceProvider(app, service_name=app.config.app_name))
```

Not registered by default — it needs the `otel` extra installed and, usually, a decision about where spans should actually go. Commented out in a generated project's `main.py`, ready to uncomment once you're ready.

Without an `exporter`, spans print to the console — useful for confirming tracing is wired up correctly before you've picked a backend:

```python
app.register(TracingServiceProvider(app, service_name="my-blog"))
```

Pointed at a real collector, pass any `SpanExporter` you've configured separately (this framework doesn't hardcode a dependency on one):

```python
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

app.register(
    TracingServiceProvider(
        app,
        service_name="my-blog",
        exporter=OTLPSpanExporter(endpoint="http://localhost:4317"),
    )
)
```

## What each request's span carries

`TracingMiddleware` wraps every HTTP request in a server span named `"{method} {path}"`, with the conventional attributes:

- `http.method`
- `http.target`
- `http.status_code`

It extracts any incoming W3C `traceparent` header first, so a span started upstream (a gateway, another service in your architecture) continues as this request's parent rather than starting a fresh, disconnected trace — the whole point of *distributed* tracing.

An unhandled exception is recorded on the span (`span.record_exception()`) and the span's status is marked as an error before the exception continues propagating unchanged to Zeython's own error handling — this only annotates the trace, it never changes what the client sees.

## Sampling

Every request is traced by default (`ParentBased(ALWAYS_ON)`, the SDK's own default) — the right choice while you're confirming tracing works, and fine at moderate traffic. Once request volume makes tracing *everything* too expensive to export and store, sample a fraction:

```python
app.register(TracingServiceProvider(app, service_name="my-blog", sample_ratio=0.1))
```

`sample_ratio=0.1` traces roughly 10% of requests. It's wrapped in `ParentBased` automatically: a trace already sampled by an upstream service (its decision arrives on the incoming `traceparent` header) is always continued here regardless of this service's own ratio — a distributed trace should never have a gap in the middle because one hop independently decided not to sample.

Pass a `sampler` instead for anything `sample_ratio` doesn't cover — a rate-limiting sampler, one driven by your own config, `ALWAYS_OFF` for a kill switch:

```python
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF

app.register(TracingServiceProvider(app, service_name="my-blog", sampler=ALWAYS_OFF))
```

`sampler` takes precedence over `sample_ratio` when both are given.

## Baggage: passing context across service calls

[W3C Baggage](https://www.w3.org/TR/baggage/) carries key/value pairs *with* a trace across every service it touches — set once, readable anywhere downstream, unlike a span attribute which only lives on the one span it was set on. `TracingMiddleware` extracts an incoming `baggage` header the same way it extracts `traceparent` — nothing to configure.

```python
from zeython import current_baggage, set_baggage

async def create_order(request):
    set_baggage("tenant_id", str(current_tenant_id()))
    ...

async def somewhere_downstream_in_the_same_request(request):
    tenant_id = current_baggage("tenant_id")  # "42", set upstream in this same request
```

To actually reach another service, inject the current trace context (and any baggage) into the outbound request's headers — whatever HTTP client you use:

```python
from zeython import inject_headers

response = await http.post(
    "https://payments.internal/charge",
    json=payload,
    headers=inject_headers({"Authorization": f"Bearer {service_token}"}),
)
```

`inject_headers()` merges `traceparent`/`baggage` into the headers you pass (or returns a fresh dict if you don't pass any) — the receiving service's own `TracingMiddleware` picks both up automatically, continuing the same trace and seeing the same baggage.

**Don't put anything sensitive in baggage** — it rides across the wire in plain-text headers, visible to every service and any intermediary the request passes through, the same caveat as any other request header.

## Using the tracer directly

`init_tracing()` (called for you by `TracingServiceProvider.boot()`) registers the global tracer provider, so your own code can start additional spans the normal OpenTelemetry way, without going through this module again:

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def process_order(order):
    with tracer.start_as_current_span("process_order") as span:
        span.set_attribute("order.id", order.id)
        ...
```

These nest under whatever request span was already active, giving you a full picture of what a request actually did, not just how long the whole thing took.

## API reference

See [`zeython.tracing`](https://zeython.zaber.dev/docs/reference/operations/index.md) for the full API.

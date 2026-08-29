# Tracing

Distributed tracing via [OpenTelemetry](https://opentelemetry.io/): one
span per request, propagated across service calls via the standard W3C
`traceparent` header, exported wherever you point it — a local console
for development, or a real collector (Jaeger, Tempo, an OTLP-speaking
vendor backend) in production.

For request counts and latency histograms (aggregate numbers, not
per-request spans), see [Metrics](metrics.md) instead — the two are
complementary and commonly run together, but answer different questions:
"how many/how slow, in aggregate" vs. "what exactly happened on this one
request, across every service it touched."

Requires the `otel` extra:

```bash
pip install "zeython[otel]"
```

Deliberately not a hard dependency, and deliberately does not depend on
any specific exporter package: `init_tracing()` takes any `SpanExporter`
you already have configured (an OTLP exporter, a vendor's own, or the
SDK's own `ConsoleSpanExporter` if you pass none), so the required `otel`
extra is just the OpenTelemetry API + SDK, never a specific backend's
client library.

## Setup

```python
# main.py
from zeython import Application, TracingServiceProvider

app = Application()
app.register(TracingServiceProvider(app, service_name=app.config.app_name))
```

Not registered by default — it needs the `otel` extra installed and,
usually, a decision about where spans should actually go. Commented out
in a generated project's `main.py`, ready to uncomment once you're ready.

Without an `exporter`, spans print to the console — useful for confirming
tracing is wired up correctly before you've picked a backend:

```python
app.register(TracingServiceProvider(app, service_name="my-blog"))
```

Pointed at a real collector, pass any `SpanExporter` you've configured
separately (this framework doesn't hardcode a dependency on one):

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

`TracingMiddleware` wraps every HTTP request in a server span named
`"{method} {path}"`, with the conventional attributes:

- `http.method`
- `http.target`
- `http.status_code`

It extracts any incoming W3C `traceparent` header first, so a span
started upstream (a gateway, another service in your architecture)
continues as this request's parent rather than starting a fresh,
disconnected trace — the whole point of *distributed* tracing.

An unhandled exception is recorded on the span (`span.record_exception()`)
and the span's status is marked as an error before the exception
continues propagating unchanged to Zeython's own error handling — this
only annotates the trace, it never changes what the client sees.

## Using the tracer directly

`init_tracing()` (called for you by `TracingServiceProvider.boot()`)
registers the global tracer provider, so your own code can start
additional spans the normal OpenTelemetry way, without going through this
module again:

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def process_order(order):
    with tracer.start_as_current_span("process_order") as span:
        span.set_attribute("order.id", order.id)
        ...
```

These nest under whatever request span was already active, giving you a
full picture of what a request actually did, not just how long the whole
thing took.

## API reference

See [`zeython.tracing`](reference/operations.md) for the full API.

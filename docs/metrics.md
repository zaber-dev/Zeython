# Metrics

Prometheus-compatible metrics — request counts, latency histograms, and
any counters/gauges/histograms your own code defines — all exposed at
`/metrics` in the [Prometheus text exposition
format](https://github.com/prometheus/docs/blob/main/content/docs/instrumenting/exposition_formats.md),
scraped directly by Prometheus itself or anything speaking the same
format (Grafana Agent, VictoriaMetrics, Datadog's OpenMetrics ingestion).

No new dependency: the exposition format is a small, stable, documented
text format, and `zeython.metrics` implements it directly rather than
pulling in the full `prometheus_client` package for what's fundamentally
a handful of counters this framework already knows how to compute from
the request/response objects it sees.

For distributed tracing (spans across a request, not counters), see
[Tracing](tracing.md) instead.

## Setup

```python
# main.py
from zeython import Application, MetricsServiceProvider

app = Application()
app.register(MetricsServiceProvider(app))
```

Registered by default in a generated project — zero-config and safe to
always register, the same way [Health Check](health-check.md) is. The
built-in HTTP metrics have no cardinality risk (see below) and add a
single dict lookup and a few increments per request.

Configurable via `.env`:

- `METRICS_ENABLED` — default `true`.
- `METRICS_PATH` — default `/metrics`.

## What's collected out of the box

Every request is instrumented automatically:

- `http_requests_total{method, path, status}` — a `Counter`.
- `http_request_duration_seconds{method, path}` — a `Histogram`, with
  Prometheus's own default bucket boundaries.
- `http_requests_in_progress{method}` — a `Gauge`.

`path` is the route's own path *template* (`/posts/{id}`), never the
literal URL — grouping by literal URL would mean an ever-growing,
unbounded set of label combinations for anything with a numeric or UUID
path parameter, which is exactly the kind of cardinality explosion that
makes a metrics backend fall over. A request that matched no route at all
(a 404, or a probing bot) is grouped under `path="unmatched"` for the same
reason. The `/metrics` endpoint itself is excluded from these counts.

```bash
curl http://localhost:8000/metrics
```

```
# HELP http_requests_total Total HTTP requests.
# TYPE http_requests_total counter
http_requests_total{method="GET",path="/posts/{id}",status="200"} 42
# HELP http_request_duration_seconds HTTP request duration in seconds.
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds_bucket{method="GET",path="/posts/{id}",le="0.005"} 30
...
http_request_duration_seconds_sum{method="GET",path="/posts/{id}"} 1.284
http_request_duration_seconds_count{method="GET",path="/posts/{id}"} 42
# HELP http_requests_in_progress HTTP requests currently being processed.
# TYPE http_requests_in_progress gauge
http_requests_in_progress{method="GET"} 0
```

## Defining your own metrics

Resolve the `MetricsRegistry` from the container to define a metric
anywhere your own code runs — a controller, a job, a scheduled task:

```python
from zeython.metrics import MetricsRegistry

# Define once, ideally at module or boot level, and reuse the object --
# more efficient than looking it up on every call.
def register_metrics(app):
    registry = app.container.make(MetricsRegistry)
    return registry.counter("orders_placed_total", "Orders placed.")

ORDERS_PLACED = register_metrics(app)

@app.post("/orders")
async def create_order(request):
    ...
    ORDERS_PLACED.inc()
    return JSONResponse(order.to_dict(), status_code=201)
```

`registry.counter()`/`.gauge()`/`.histogram()` are idempotent by name —
calling one again with the same name returns the *same* metric object
rather than registering a duplicate, so it's safe to call from inside a
request handler on every request too, not just once at startup.

### Counter

Only ever goes up — request counts, jobs processed, errors seen:

```python
requests = registry.counter("errors_total", "Errors seen.", labelnames=("kind",))
requests.inc(kind="validation")
```

### Gauge

Can go up or down — in-flight requests, queue depth, connections open
right now:

```python
queue_depth = registry.gauge("queue_depth", "Jobs waiting.")
queue_depth.set(len(pending_jobs))
```

### Histogram

A distribution of observed values, bucketed by upper bound — request
durations, payload sizes:

```python
payload_size = registry.histogram("payload_size_bytes", "Request payload size.")
payload_size.observe(len(body))
```

Pass `buckets=(...)` to override the default bucket boundaries (seconds,
tuned for HTTP latency) with ones that fit whatever you're measuring.

## Scraping it

A minimal Prometheus config:

```yaml
scrape_configs:
  - job_name: my-app
    static_configs:
      - targets: ["my-app:8000"]
    metrics_path: /metrics
```

## API reference

See [`zeython.metrics`](reference/operations.md) for the full API.

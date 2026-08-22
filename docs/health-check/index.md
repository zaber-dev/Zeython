# Health Check

`HealthCheckServiceProvider` registers `/up` -- what a load balancer, a Kubernetes liveness/readiness probe, or an uptime monitor expects to find. It's registered by default in a generated project.

```bash
curl http://localhost:8000/up
```

```json
{"status": "ok", "checks": {"database": "ok"}}
```

A healthy response is a `200` with `"status": "ok"`. If any check fails, the response is a `503` with `"status": "error"` -- the status code is what a load balancer actually acts on to decide whether to route traffic here, so nothing consuming this endpoint needs to parse the body just to know the answer.

## What it checks

Currently just database connectivity -- a real `SELECT 1` over the configured connection, not merely "is a URL configured" -- and only when `Database` is bound in the container (`DatabaseServiceProvider` registered). An app with no database reports `{"status": "ok", "checks": {}}`; there's nothing to check, so nothing is skipped silently or reported as failing.

## Configuration

- `HEALTH_CHECK_ENABLED` -- default `true`. Set `false` to turn the endpoint off entirely, e.g. if you'd rather not expose it publicly and probe something internal-only instead.
- `HEALTH_CHECK_PATH` -- default `/up`. Change it if your infrastructure expects a different convention (`/healthz` is common on Kubernetes).

## Setup

```python
# main.py
from zeython import Application, HealthCheckServiceProvider

app = Application()
app.register(HealthCheckServiceProvider)
```

Register it early -- before `DatabaseServiceProvider` is fine either way, since providers' `register()` phase runs to completion before any `boot()` runs (see [Architecture](https://zeython.zaber.dev/docs/architecture/index.md)), so the database binding is guaranteed to exist by the time the health check route boots, regardless of registration order.

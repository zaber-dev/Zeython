# Observability

## Request/Correlation IDs

A production server handles many requests concurrently; its log stream is every one of them interleaved. Without something tying a group of log lines back to the single request that produced them, "what actually happened for this one request" becomes archaeology — grepping timestamps and hoping nothing else logged in that same window. `RequestIdMiddleware` gives every request a correlation ID and threads it through both the response and the logs.

### What it does

- Reads the caller's own `X-Request-ID` request header, if it sent one — so a request can be traced end-to-end across multiple services that all honor the same header (a gateway, this app, a downstream call it makes).
- Otherwise generates a fresh UUID4.
- Echoes it back as a response header, so the client can correlate its own logs (or just paste the ID back to you) with the server's.
- Makes it available to any code running while handling that request via `request_id()` — and to every log line, via `%(request_id)s` in a formatter.

### Setup

```python
# main.py
from zeython import Application, RequestIdServiceProvider

app = Application()
app.register(RequestIdServiceProvider)
```

Registered by default in a generated project. Unlike [Security Headers](https://zeython.zaber.dev/docs/security-headers/index.md), there's no application-specific default to get wrong here — it only adds a response header and a piece of log context, never changes what a request is allowed to do.

Configurable via `.env`:

- `REQUEST_ID_HEADER` — default `X-Request-ID`.

### Reading it in a handler

```python
from zeython.request_id import request_id

@app.get("/whoami")
async def whoami(request):
    return {"request_id": request_id()}
```

### In your own logging

Registering `RequestIdServiceProvider` also installs a `logging.Filter` on the root logger, so every `LogRecord` gets a `request_id` attribute — `"-"` for anything logged outside of a request (startup, a scheduled job). If your app hasn't customized `logging.basicConfig()` yet (the framework's own default format from `Application.__init__`), the provider folds `%(request_id)s` into it automatically:

```text
2026-08-17 10:22:03 INFO     app.controllers.posts [3f2a9e1c-...]: created post 42
```

Configured your own formatter already? The provider leaves it alone — `record.request_id` is still there to build `%(request_id)s` into it yourself, or to pull directly in a handler:

```python
import logging

logger = logging.getLogger(__name__)

class RequestIdFormatter(logging.Formatter):
    pass  # add %(request_id)s to your own fmt string

logger.info("processing order %s", order.id)  # record.request_id is set automatically
```

### Using the middleware directly

```python
from zeython.request_id import RequestIdMiddleware

app.add_middleware(RequestIdMiddleware, header_name="X-Correlation-ID")
```

### Verifying it

```bash
curl -sI http://localhost:8000/up | grep -i x-request-id
curl -sI http://localhost:8000/up -H "X-Request-ID: my-own-id" | grep -i x-request-id
```

The second call gets back exactly `my-own-id` — the middleware never overwrites a caller-supplied value.

## Structured (JSON) logging

The framework's default log line (`Application.__init__` calls this if nothing else configured `logging` first) is a human-readable text line:

```text
2026-08-17 10:22:03 INFO     app.controllers.posts [3f2a9e1c-...]: created post 42
```

Fine to read in a terminal, painful for a log shipper (Datadog, ELK/Logstash, CloudWatch Logs Insights, Splunk) that wants structured fields to filter and query on rather than a regex over free text. `LOG_FORMAT=json` switches the same default handler to one JSON object per line instead:

```text
{"timestamp": "2026-08-17 10:22:03,041", "level": "INFO", "logger": "app.controllers.posts", "message": "created post 42", "request_id": "3f2a9e1c-..."}
```

### Setup

```bash
# .env
LOG_FORMAT=json
```

Nothing else changes — same loggers, same levels, same `RequestIdServiceProvider` integration (`request_id` is present whenever that provider is registered, `"-"` outside a request, same as the text format). Only takes effect through the framework's own default logging setup: like the text format, it's skipped entirely if the root logger already has a handler (you called `logging.basicConfig()` yourself, or your deployment platform did).

### Fields

Every line carries `timestamp`, `level`, `logger`, `message`, and `request_id` (when `RequestIdServiceProvider` is registered). A record with exception info (`logger.exception(...)`, or `exc_info=True`) additionally gets `exception` — the formatted traceback as a single string. Anything passed via `extra=` is included as its own top-level field:

```python
logger.info("order placed", extra={"order_id": order.id, "total": order.total})
```

```text
{"timestamp": "...", "level": "INFO", "logger": "app.jobs", "message": "order placed", "order_id": 42, "total": 19.99}
```

A field that isn't natively JSON-serializable (a `Decimal`, a `datetime`, a dataclass) degrades to its `str()` rather than raising and losing the whole log line.

### Using it directly

`zeython.logging.JsonFormatter` is a plain `logging.Formatter` — attach it to your own handler if you need something LOG_FORMAT=json's all-or-nothing default doesn't cover (a second handler with a different format, non-default log setup):

```python
import logging
from zeython import JsonFormatter

handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.getLogger("app.audit").addHandler(handler)
```

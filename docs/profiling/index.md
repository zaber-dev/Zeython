# Request & Query Profiling

`zeython.profiler` answers the question Laravel Telescope and Django Debug Toolbar exist for -- "how many queries did this request run, and how long did they take" -- without a bundled UI, since most of what this framework serves is a JSON API rather than server-rendered HTML pages a toolbar overlay could attach to. Every response gets the numbers as headers instead, inspectable from any HTTP client, a browser's network tab, or a test assertion.

Deliberately separate from [N+1 query detection](https://zeython.zaber.dev/docs/relationships/#detecting-n1s-automatically), which answers a narrower question (the same statement shape repeated suspiciously many times) -- register either independently of the other.

## Setup

```python
# main.py
from zeython import Application, DatabaseServiceProvider, RequestProfilerServiceProvider

app = Application()
app.register(DatabaseServiceProvider)             # must run first -- binds Database
app.register(RequestProfilerServiceProvider(app))
```

A generated project already has this registered (see `main.py`) -- unlike `N1QueryDetectionServiceProvider`, there's no application-specific default to get wrong: its `boot()` is a no-op unless `APP_DEBUG` is true, so it's safe to always register, the same reasoning `RequestIdServiceProvider` already relies on.

## Response headers

Every response carries:

| Header                  | Meaning                                |
| ----------------------- | -------------------------------------- |
| `X-Debug-Duration-Ms`   | Total time spent handling the request. |
| `X-Debug-Query-Count`   | Number of SQL queries the request ran. |
| `X-Debug-Query-Time-Ms` | Total time spent inside those queries. |

```bash
curl -sI http://localhost:8000/posts | grep -i x-debug
# X-Debug-Duration-Ms: 12.40
# X-Debug-Query-Count: 3
# X-Debug-Query-Time-Ms: 2.91
```

A large gap between duration and query time points at time spent somewhere else -- template rendering, an outgoing HTTP call, plain Python work -- not the database.

## Slow query logging

Any single query at or past `PROFILER_SLOW_QUERY_MS` (default `100`) logs a warning naming the route and the query:

```text
WARNING zeython.profiler: Slow query on /posts: 340.12 ms -- SELECT posts.*, ...
```

Only logged for a request that completes normally -- see ["Queries on a crashed request"](#queries-on-a-crashed-request) below for why a request that raises doesn't go through this path, and how you still see its queries.

## Inspecting the current request's queries yourself

```python
from zeython.profiler import current_queries

async def some_handler(request):
    ...
    for query in current_queries():
        print(query.statement, query.duration_ms)
```

Empty if `RequestProfilerServiceProvider` isn't registered (or `APP_DEBUG` is false), or called outside a request.

## Queries on a crashed request

The queries a request ran before it crashed show up on the [debug error page/body](https://zeython.zaber.dev/docs/api-standards/#debug-mode-a-browsable-html-error-page) too -- often the fastest way to see *why* it crashed (a query that returned nothing an `include=` expected, one that ran against the wrong table). The HTML debug page gets a "Queries" panel above the stack trace; the JSON/`problem+json` debug bodies get a `queries` array, each entry `{"sql": ..., "duration_ms": ...}`.

This only works because `RequestProfilerMiddleware` deliberately doesn't reset its internal state while an exception is still propagating -- Starlette's own error-handling middleware sits *outside* every user-added middleware (this one included), so the debug page is built after the crash has already unwound past this middleware's own code. A naive cleanup-in-`finally` would erase the query log at exactly the moment it's most useful. Nothing leaks from skipping that cleanup: each request gets a fresh, empty query list the moment it starts, regardless of how the previous one ended.

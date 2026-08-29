# Jobs & Realtime

Background job queues (in-memory, synchronous, and Redis-backed), the in-app scheduler, WebSockets, outgoing mail, multi-channel notifications, and outbound webhooks.

## queue

Background jobs: run work off the request/response cycle.

The default queue is an `asyncio.Queue` living in this process's memory, drained by a worker task that starts lazily on the first job you push — no framework wiring required, and it needs no ASGI lifespan hook to work correctly in tests or under a real server alike.

That also means: a job pushed but not yet run is lost if the process crashes or restarts. Fine for non-critical background work (a welcome email, warming a cache); a real limitation for anything you'd be upset to silently lose (payment capture, anything that must survive a crash). :class:`RedisQueue` is the durable, opt-in alternative — the same trade-off as `RateLimiter` and `Cache`, see docs/queues.md.

### Job

Bases: `ABC`

A unit of background work. Subclass and implement :meth:`handle`.

Jobs are plain Python objects (dataclasses are a natural fit) — the default queue never serializes them, so constructor arguments can be anything, not just JSON-safe values::

```text
@dataclass
class SendWelcomeEmail(Job):
    email: str
    name: str

    async def handle(self) -> None:
        ...
```

`handle()` can also declare type-hinted parameters beyond `self` to have them resolved from the container that dispatched the job (the same autowiring `Container.call` uses everywhere else)::

```text
async def handle(self, mailer: Mailer) -> None:
    await mailer.send(...)
```

### Queue

```python
Queue(*, container: Container | None = None)
```

Bases: `ABC`

Accepts jobs to run in the background.

`container`, if given, is used to autowire any extra type-hinted parameters on a job's `handle()` — see :class:`Job`. Without one, `handle()` is called with no arguments beyond `self`.

Source code in `src/zeython/queue.py`

```python
def __init__(self, *, container: Container | None = None) -> None:
    self.container = container
```

#### push

```python
push(job: Job, *, delay: float = 0.0) -> None
```

Queue `job` to run -- immediately, or after `delay` seconds.

Source code in `src/zeython/queue.py`

```python
@abstractmethod
async def push(self, job: Job, *, delay: float = 0.0) -> None:
    """Queue ``job`` to run -- immediately, or after ``delay`` seconds."""
```

### InMemoryQueue

```python
InMemoryQueue(*, container: Container | None = None)
```

Bases: `Queue`

Runs jobs on a background `asyncio` task in this process.

The worker starts on the first :meth:`push` and keeps running for the life of the event loop. Failed jobs are retried up to `job.max_attempts` times, with each failure logged; :meth:`close` is available for a clean shutdown (mainly useful in tests, to avoid "task was destroyed but it is pending" warnings at interpreter exit). `delay` schedules a job to be enqueued after a wait rather than immediately, via a tracked background task -- also cleaned up by :meth:`close`.

Source code in `src/zeython/queue.py`

```python
def __init__(self, *, container: Container | None = None) -> None:
    super().__init__(container=container)
    self._queue: asyncio.Queue[Job] = asyncio.Queue()
    self._worker_task: asyncio.Task[None] | None = None
    self._delayed_tasks: set[asyncio.Task[None]] = set()
```

#### join

```python
join() -> None
```

Block until every job pushed so far has finished running. Mainly for tests.

Includes a job pushed with `delay` -- `asyncio.Queue.join()` alone only tracks work already `put()` onto the queue, and a delayed push doesn't call `put()` until its wait elapses. This first waits for every currently-pending delayed push's own wait (however long that is) before falling through to the queue's own join, so this genuinely blocks for "as long as it takes", not just however long is already in flight.

Source code in `src/zeython/queue.py`

```python
async def join(self) -> None:
    """Block until every job pushed so far has finished running. Mainly for tests.

    Includes a job pushed with ``delay`` -- ``asyncio.Queue.join()``
    alone only tracks work already ``put()`` onto the queue, and a
    delayed push doesn't call ``put()`` until its wait elapses. This
    first waits for every currently-pending delayed push's own wait
    (however long that is) before falling through to the queue's own
    join, so this genuinely blocks for "as long as it takes", not
    just however long is already in flight.
    """
    delayed = list(self._delayed_tasks)
    if delayed:
        await asyncio.gather(*delayed, return_exceptions=True)
    await self._queue.join()
```

#### close

```python
close() -> None
```

Cancel the background worker task and any pending delayed pushes.

Source code in `src/zeython/queue.py`

```python
async def close(self) -> None:
    """Cancel the background worker task and any pending delayed pushes."""
    for task in list(self._delayed_tasks):
        task.cancel()
    for task in list(self._delayed_tasks):
        with contextlib.suppress(asyncio.CancelledError):
            await task
    self._delayed_tasks.clear()

    if self._worker_task is not None:
        self._worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._worker_task
        self._worker_task = None
```

### SyncQueue

```python
SyncQueue(*, container: Container | None = None)
```

Bases: `Queue`

Runs jobs immediately and synchronously — no background task, no retries.

Meant for tests and local dev: failures raise straight through `push()` instead of being caught and logged, so you see them immediately rather than digging through logs. `delay` is ignored -- a synchronous, immediate-execution queue has nothing to schedule against.

Source code in `src/zeython/queue.py`

```python
def __init__(self, *, container: Container | None = None) -> None:
    self.container = container
```

### RedisQueue

```python
RedisQueue(
    url: str,
    *,
    container: Container | None = None,
    queue_name: str = "default",
    prefix: str = "zeython:queue:",
)
```

Bases: `Queue`

A Redis-backed durable queue: a job pushed here survives a crash or restart of the process that pushed it, and is processed by a separate worker process (`zeython queue work`) rather than a background task inside the web server. Requires the `redis` extra (`pip install zeython[redis]`).

Jobs must be `@dataclass` subclasses of :class:`Job` -- see :func:`_serialize_job`. Failed attempts are retried with capped exponential backoff (2, 4, 8, ... up to 60 seconds between attempts); a job that exhausts `max_attempts` is moved to a **failed-jobs list** instead of being dropped, so nothing that couldn't be processed is silently lost -- see :meth:`failed_jobs`.

All keys are namespaced under `prefix` + `queue_name` (default `"zeython:queue:default:"`) — safe to point at a Redis instance shared with other subsystems (cache, rate limiting, sessions).

Source code in `src/zeython/queue.py`

```python
def __init__(
    self,
    url: str,
    *,
    container: Container | None = None,
    queue_name: str = "default",
    prefix: str = "zeython:queue:",
) -> None:
    try:
        from redis.asyncio import Redis
    except ImportError as exc:
        raise ImportError(
            "RedisQueue requires the redis package. Install it with: pip install zeython[redis]"
        ) from exc

    super().__init__(container=container)
    self._client = Redis.from_url(url)
    self.queue_name = queue_name
    self._base = f"{prefix}{queue_name}:"
```

#### failed_jobs

```python
failed_jobs() -> list[dict[str, Any]]
```

Every job that exhausted its retries, most recently failed first.

Source code in `src/zeython/queue.py`

```python
async def failed_jobs(self) -> list[dict[str, Any]]:
    """Every job that exhausted its retries, most recently failed first."""
    raw_entries = await self._client.lrange(self._failed_key, 0, -1)
    return [json.loads(entry) for entry in raw_entries]
```

#### run_worker

```python
run_worker(
    *,
    poll_interval: float = 1.0,
    shutdown: Event | None = None,
) -> None
```

Block, processing jobs from this queue until `shutdown` is set (or forever, if none is given) -- what `zeython queue work` runs.

Reclaims any delayed/retry jobs whose wait has elapsed on every poll, then blocks (up to `poll_interval` seconds) for the next ready job via Redis's own `BRPOP` rather than busy-polling.

Source code in `src/zeython/queue.py`

```python
async def run_worker(
    self, *, poll_interval: float = 1.0, shutdown: asyncio.Event | None = None
) -> None:
    """Block, processing jobs from this queue until ``shutdown`` is set
    (or forever, if none is given) -- what ``zeython queue work`` runs.

    Reclaims any delayed/retry jobs whose wait has elapsed on every
    poll, then blocks (up to ``poll_interval`` seconds) for the next
    ready job via Redis's own ``BRPOP`` rather than busy-polling.
    """
    while shutdown is None or not shutdown.is_set():
        await self._reclaim_delayed()
        result = await self._client.brpop([self._pending_key], timeout=poll_interval)
        if result is None:
            continue
        _, raw = result
        await self._process(raw.decode() if isinstance(raw, bytes) else raw)
```

### QueueServiceProvider

```python
QueueServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Binds a :class:`Queue` into the container.

`.env`: `QUEUE_DRIVER` —

- `memory` (default) — :class:`InMemoryQueue`, a background task in this process. Jobs are lost on crash/restart.
- `sync` — :class:`SyncQueue`, runs jobs immediately in-line; useful for tests/local dev.
- `redis` — :class:`RedisQueue`, durable, processed by a separate `zeython queue work` process. Requires `REDIS_URL` and the `redis` extra. `QUEUE_NAME` picks the queue (default `default`) -- useful if you want a dedicated worker/priority lane for, say, emails vs. report generation.

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

### dispatch

```python
dispatch(
    request: Request, job: Job, *, delay: float = 0.0
) -> None
```

Queue `job` to run in the background rather than blocking this request.

Uses whichever `Queue` is bound in the container — :class:`InMemoryQueue` by default, :class:`SyncQueue` if `QUEUE_DRIVER=sync`, :class:`RedisQueue` if `QUEUE_DRIVER=redis` (see :class:`QueueServiceProvider`). Pass `delay` to run the job after a wait instead of as soon as a worker is free. Outside of a request, push directly to a resolved queue instead: `await app.container.make(Queue).push(job)`.

Source code in `src/zeython/queue.py`

```python
async def dispatch(request: Request, job: Job, *, delay: float = 0.0) -> None:
    """Queue ``job`` to run in the background rather than blocking this request.

    Uses whichever ``Queue`` is bound in the container — :class:`InMemoryQueue`
    by default, :class:`SyncQueue` if ``QUEUE_DRIVER=sync``, :class:`RedisQueue`
    if ``QUEUE_DRIVER=redis`` (see :class:`QueueServiceProvider`). Pass
    ``delay`` to run the job after a wait instead of as soon as a worker is
    free. Outside of a request, push directly to a resolved queue instead:
    ``await app.container.make(Queue).push(job)``.
    """
    queue: Queue = request.app.state.container.make(Queue)
    await queue.push(job, delay=delay)
```

## schedule

In-app task scheduling: recurring jobs defined in code (and therefore version-controlled, reviewed, and deployed alongside the app) instead of scattered across a server's crontab where nobody remembers what runs and why.

`Schedule` holds a list of `ScheduledEvent`s; `zeython schedule run` -- meant to be invoked once a minute by a single cron entry (or a sidecar loop container, see docs/scheduling.md) -- checks which are due this minute and runs them. Nothing here polls or sleeps on its own: the actual "once a minute" cadence is still driven by whatever calls `zeython schedule run`, the same way Laravel's own `schedule:run` works.

### ScheduledEvent

```python
ScheduledEvent(
    name: str,
    callback: Callable[..., Awaitable[None]],
    *,
    container: Container | None = None,
)
```

One recurring task: a callback plus a cron expression saying when it's due. Built fluently off :meth:`Schedule.call`; every builder method returns `self` so calls chain::

```text
schedule.call(send_daily_digest).daily_at("07:00")
```

Source code in `src/zeython/schedule.py`

```python
def __init__(
    self,
    name: str,
    callback: Callable[..., Awaitable[None]],
    *,
    container: Container | None = None,
) -> None:
    self.name = name
    self.callback = callback
    self.container = container
    self.cron_expression = "* * * * *"
    self._overlap_window: float | None = None
```

#### cron

```python
cron(expression: str) -> ScheduledEvent
```

Any 5-field cron expression -- see :func:`cron_matches`.

Source code in `src/zeython/schedule.py`

```python
def cron(self, expression: str) -> ScheduledEvent:
    """Any 5-field cron expression -- see :func:`cron_matches`."""
    self.cron_expression = expression
    return self
```

#### daily_at

```python
daily_at(time: str) -> ScheduledEvent
```

`"HH:MM"`, 24-hour, e.g. `daily_at("07:30")`.

Source code in `src/zeython/schedule.py`

```python
def daily_at(self, time: str) -> ScheduledEvent:
    """``"HH:MM"``, 24-hour, e.g. ``daily_at("07:30")``."""
    hour_str, minute_str = time.split(":")
    return self.cron(f"{int(minute_str)} {int(hour_str)} * * *")
```

#### weekly

```python
weekly() -> ScheduledEvent
```

Sunday at midnight.

Source code in `src/zeython/schedule.py`

```python
def weekly(self) -> ScheduledEvent:
    """Sunday at midnight."""
    return self.cron("0 0 * * 0")
```

#### monthly

```python
monthly() -> ScheduledEvent
```

The 1st of the month at midnight.

Source code in `src/zeython/schedule.py`

```python
def monthly(self) -> ScheduledEvent:
    """The 1st of the month at midnight."""
    return self.cron("0 0 1 * *")
```

#### without_overlapping

```python
without_overlapping(
    *, for_seconds: float = 3600
) -> ScheduledEvent
```

Skip a run if a previous one started within the last `for_seconds` -- for a task that occasionally runs longer than its own interval, or one you never want two copies of running against each other.

Implemented via the container's bound `RateLimiter` as a "run at most once per window" gate, keyed by this event's name -- a time-based window, same trade-off Laravel's own `withoutOverlapping()` makes: the lock expires after `for_seconds` regardless of whether the previous run actually finished, it doesn't track "is it still running" directly.

**Requires a shared `RateLimiter` backend (`RedisRateLimiter`) to do anything in the normal case.** `zeython schedule run` is a fresh process every time cron invokes it -- the default `InMemoryRateLimiter`'s lock lives in that process's memory and is gone the instant it exits, so back-to-back CLI invocations never see each other's lock at all. See docs/scheduling.md.

Source code in `src/zeython/schedule.py`

```python
def without_overlapping(self, *, for_seconds: float = 3600) -> ScheduledEvent:
    """Skip a run if a previous one started within the last
    ``for_seconds`` -- for a task that occasionally runs longer than
    its own interval, or one you never want two copies of running
    against each other.

    Implemented via the container's bound ``RateLimiter`` as a "run at
    most once per window" gate, keyed by this event's name -- a
    time-based window, same trade-off Laravel's own
    ``withoutOverlapping()`` makes: the lock expires after
    ``for_seconds`` regardless of whether the previous run actually
    finished, it doesn't track "is it still running" directly.

    **Requires a shared ``RateLimiter`` backend (``RedisRateLimiter``)
    to do anything in the normal case.** ``zeython schedule run`` is a
    fresh process every time cron invokes it -- the default
    ``InMemoryRateLimiter``'s lock lives in that process's memory and
    is gone the instant it exits, so back-to-back CLI invocations never
    see each other's lock at all. See docs/scheduling.md.
    """
    self._overlap_window = for_seconds
    return self
```

### Schedule

```python
Schedule(*, container: Container | None = None)
```

The registry `schedule.py` builds against: `schedule.call(fn).daily()`.

Source code in `src/zeython/schedule.py`

```python
def __init__(self, *, container: Container | None = None) -> None:
    self.container = container
    self._events: list[ScheduledEvent] = []
```

#### call

```python
call(
    callback: Callable[..., Awaitable[None]],
    *,
    name: str | None = None,
) -> ScheduledEvent
```

Register `callback` (any async function; type-hinted params beyond the ones you pass are autowired from the container, same as a `Job`'s `handle()`) and return the :class:`ScheduledEvent` to set its frequency on.

Source code in `src/zeython/schedule.py`

```python
def call(self, callback: Callable[..., Awaitable[None]], *, name: str | None = None) -> ScheduledEvent:
    """Register ``callback`` (any async function; type-hinted params
    beyond the ones you pass are autowired from the container, same as
    a ``Job``'s ``handle()``) and return the :class:`ScheduledEvent` to
    set its frequency on."""
    event_name: str = name if name is not None else getattr(callback, "__name__", repr(callback))
    event = ScheduledEvent(
        name=event_name,
        callback=callback,
        container=self.container,
    )
    self._events.append(event)
    return event
```

#### run_due

```python
run_due(
    *, at: datetime | None = None
) -> list[ScheduledEvent]
```

Run every event due at `at` (default: now), returning the ones that were due. An event that raises is logged and doesn't stop the rest from running -- what `zeython schedule run` calls.

Source code in `src/zeython/schedule.py`

```python
async def run_due(self, *, at: datetime | None = None) -> list[ScheduledEvent]:
    """Run every event due at ``at`` (default: now), returning the
    ones that were due. An event that raises is logged and doesn't
    stop the rest from running -- what ``zeython schedule run`` calls.
    """
    now = at or datetime.now()
    due = [event for event in self._events if event.is_due(now)]
    for event in due:
        try:
            await event.run()
        except Exception as exc:
            logger.exception("Scheduled event %s raised", event.name)
            # No retry concept for a scheduled task -- every failure
            # here is already final, unlike a queued job's retries.
            report_exception(exc, scheduled_event=event.name)
    return due
```

### ScheduleServiceProvider

```python
ScheduleServiceProvider(
    app: Application,
    modules: tuple[str, ...] = ("schedule",),
)
```

Bases: `ServiceProvider`

Binds a process-wide :class:`Schedule` singleton and imports `schedule.py` from the project root for its side effect of registering events on it -- the same convention :class:`~zeython.providers.RouteServiceProvider` uses for `routes/web.py`.

Not registered by default -- add it once you have scheduled tasks to define::

```text
# main.py
app.register(ScheduleServiceProvider(app))
```

Source code in `src/zeython/schedule.py`

```python
def __init__(self, app: Application, modules: tuple[str, ...] = ("schedule",)) -> None:
    super().__init__(app)
    self.modules = modules
```

### cron_matches

```python
cron_matches(expression: str, at: datetime) -> bool
```

Whether a standard 5-field cron expression (`minute hour day month weekday`) matches `at`. Supports `*`, single values, comma lists (`1,3,5`), ranges (`1-5`), and step values (`*/15`, `1-10/2`).

The weekday field is `0`-`6` (`0` = Sunday) only -- unlike some cron implementations, `7` is not accepted as an alias for Sunday.

Source code in `src/zeython/schedule.py`

```python
def cron_matches(expression: str, at: datetime) -> bool:
    """Whether a standard 5-field cron expression (``minute hour day month
    weekday``) matches ``at``. Supports ``*``, single values, comma lists
    (``1,3,5``), ranges (``1-5``), and step values (``*/15``, ``1-10/2``).

    The weekday field is ``0``-``6`` (``0`` = Sunday) only -- unlike some
    cron implementations, ``7`` is not accepted as an alias for Sunday.
    """
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError(f"Invalid cron expression (expected 5 space-separated fields): {expression!r}")
    minute, hour, day, month, weekday = fields
    cron_weekday = (at.weekday() + 1) % 7  # Python: Monday=0..Sunday=6 -> cron: Sunday=0..Saturday=6
    return (
        _field_matches(at.minute, minute)
        and _field_matches(at.hour, hour)
        and _field_matches(at.day, day)
        and _field_matches(at.month, month)
        and _field_matches(cron_weekday, weekday)
    )
```

## websockets

Real-time WebSocket support, built directly on Starlette's ASGI-native WebSocket handling -- no separate server, no extra process.

`Router.websocket(...)`/`Application.websocket(...)` registers a handler the same way `@app.get(...)` does for HTTP. :class:`WebSocketHub` is the process-local "broadcast to everyone connected" registry a chat window, a live dashboard, or any other push-to-many feature needs; :class:`RedisWebSocketHub` is the same thing backed by Redis pub/sub, for a broadcast to reach every worker process, not just this one.

### WebSocketHub

```python
WebSocketHub(
    *,
    allowed_origins: Iterable[str] | None = None,
    max_connections_per_ip: int | None = None,
)
```

Tracks connected WebSocket clients and broadcasts messages to them.

Process-local: a message only reaches clients connected to *this* process. Fine for a single worker; running more than one means each worker has its own, disjoint set of connections, so a broadcast only reaches whichever fraction of clients happen to be on the same worker -- back this with a pub/sub backend (Redis's `PUBLISH`/`SUBSCRIBE` is the usual choice) once that matters. See docs/websockets.md.

A WebSocket handshake is a plain HTTP request that carries cookies automatically -- without an origin check, any site can open a connection here using a logged-in visitor's session (cross-site WebSocket hijacking). Pass `allowed_origins` to guard against that; left unset, every origin is accepted (matches every earlier release -- opt in once you actually serve browser clients over more than one origin you don't control).

Nothing stops a single client from opening hundreds of connections -- each one costs a slot in this hub's memory and a slot in the pool of connections a broadcast iterates, so a runaway or malicious client can degrade the service for everyone else. Pass `max_connections_per_ip` to cap it; left unset, there's no limit (matches every earlier release).

Source code in `src/zeython/websockets.py`

```python
def __init__(
    self,
    *,
    allowed_origins: Iterable[str] | None = None,
    max_connections_per_ip: int | None = None,
) -> None:
    self._connections: set[WebSocket] = set()
    self._connections_by_ip: dict[str, set[WebSocket]] = defaultdict(set)
    self._ip_of_connection: dict[WebSocket, str] = {}
    self._allowed_origins = set(allowed_origins) if allowed_origins is not None else None
    self._max_connections_per_ip = max_connections_per_ip
```

#### connect

```python
connect(websocket: WebSocket) -> bool
```

Accept the handshake and start tracking this connection.

Returns `False` (after closing the connection, without ever accepting it) if `allowed_origins` is configured and this handshake's `Origin` header doesn't match one of them (close code 4403), or if `max_connections_per_ip` is configured and this client already has that many connections open (close code 4429). Check the return value and bail out if it's `False` -- proceeding to `receive_text()`/etc. on a connection that was never accepted raises::

```text
if not await hub.connect(websocket):
    return
```

Source code in `src/zeython/websockets.py`

```python
async def connect(self, websocket: WebSocket) -> bool:
    """Accept the handshake and start tracking this connection.

    Returns ``False`` (after closing the connection, without ever
    accepting it) if ``allowed_origins`` is configured and this
    handshake's ``Origin`` header doesn't match one of them (close code
    4403), or if ``max_connections_per_ip`` is configured and this
    client already has that many connections open (close code 4429).
    Check the return value and bail out if it's ``False`` -- proceeding
    to ``receive_text()``/etc. on a connection that was never accepted
    raises::

        if not await hub.connect(websocket):
            return
    """
    if not self._origin_allowed(websocket):
        await websocket.close(code=4403)
        return False

    ip = self._client_ip(websocket)
    if self._max_connections_per_ip is not None and len(self._connections_by_ip[ip]) >= self._max_connections_per_ip:
        await websocket.close(code=4429)
        return False

    await websocket.accept()
    self._connections.add(websocket)
    self._connections_by_ip[ip].add(websocket)
    self._ip_of_connection[websocket] = ip
    return True
```

#### disconnect

```python
disconnect(websocket: WebSocket) -> None
```

Stop tracking a connection -- call this from a `finally` block once its handler loop ends, however it ends.

Source code in `src/zeython/websockets.py`

```python
def disconnect(self, websocket: WebSocket) -> None:
    """Stop tracking a connection -- call this from a ``finally`` block
    once its handler loop ends, however it ends."""
    self._connections.discard(websocket)
    ip = self._ip_of_connection.pop(websocket, None)
    if ip is not None:
        self._connections_by_ip[ip].discard(websocket)
        if not self._connections_by_ip[ip]:
            del self._connections_by_ip[ip]
```

#### broadcast

```python
broadcast(
    message: str | dict, *, exclude: WebSocket | None = None
) -> None
```

Send `message` to every connected client except `exclude` (typically the sender, when echoing a chat message back to everyone *else*).

A send failing -- a client that's disconnected but hasn't reached this hub's `disconnect()` yet -- doesn't stop the broadcast reaching everyone else; that connection is just dropped from the hub instead.

Source code in `src/zeython/websockets.py`

```python
async def broadcast(self, message: str | dict, *, exclude: WebSocket | None = None) -> None:
    """Send ``message`` to every connected client except ``exclude``
    (typically the sender, when echoing a chat message back to everyone
    *else*).

    A send failing -- a client that's disconnected but hasn't reached
    this hub's ``disconnect()`` yet -- doesn't stop the broadcast
    reaching everyone else; that connection is just dropped from the
    hub instead.
    """
    stale: list[WebSocket] = []
    for connection in list(self._connections):
        if connection is exclude:
            continue
        try:
            if isinstance(message, str):
                await connection.send_text(message)
            else:
                await connection.send_json(message)
        except Exception:
            logger.debug("Dropping a stale WebSocket connection during broadcast", exc_info=True)
            stale.append(connection)

    for connection in stale:
        self._connections.discard(connection)
```

### RedisWebSocketHub

```python
RedisWebSocketHub(
    url: str,
    *,
    channel: str = "zeython:websockets:broadcast",
    allowed_origins: Iterable[str] | None = None,
    max_connections_per_ip: int | None = None,
)
```

Bases: `WebSocketHub`

A :class:`WebSocketHub` whose broadcasts reach every process, not just this one -- the distributed backend the base class's docstring names. Requires the `redis` extra (`pip install zeython[redis]`).

Every process running a `RedisWebSocketHub` against the same Redis PUBLISHes each broadcast to a shared channel and SUBSCRIBEs to that same channel, relaying whatever it receives to its own locally connected clients -- so a message broadcast from any one worker reaches clients connected to every worker, this one included, with no special-casing needed (each published message is tagged with this instance's own id so it doesn't relay its own broadcast back to clients that already got it directly from :meth:`broadcast`).

The listener starts automatically on this hub's first :meth:`connect` call -- there's no ASGI lifespan hook to start it any earlier, and nothing needs the listener running before the first connection exists anyway. That first `connect()` (and only that one -- later calls see the subscription already confirmed) doesn't return until the `SUBSCRIBE` has actually been acknowledged by Redis, not just scheduled: without that wait, a client that connects and immediately triggers a broadcast could publish before this instance's own subscription had taken effect, and Redis pub/sub never redelivers a message to a subscriber that wasn't listening yet. Call :meth:`stop` to shut the listener down cleanly (mainly useful in tests; a real process just exits, taking the task with it).

Doesn't attempt to reconnect if the Redis connection drops mid-stream -- the listener task logs the error and stops; broadcasts stop reaching other processes (and this process stops relaying theirs) until the process is restarted. The same accepted trade-off as the other Redis-backed classes here, none of which implement retry logic: simple and predictable beats a hand-rolled reconnect loop that becomes its own source of bugs.

Source code in `src/zeython/websockets.py`

```python
def __init__(
    self,
    url: str,
    *,
    channel: str = "zeython:websockets:broadcast",
    allowed_origins: Iterable[str] | None = None,
    max_connections_per_ip: int | None = None,
) -> None:
    super().__init__(allowed_origins=allowed_origins, max_connections_per_ip=max_connections_per_ip)
    try:
        from redis.asyncio import Redis
    except ImportError as exc:
        raise ImportError(
            "RedisWebSocketHub requires the redis package. Install it with: pip install zeython[redis]"
        ) from exc

    self._client = Redis.from_url(url)
    self._channel = channel
    self._instance_id = uuid.uuid4().hex
    self._listener_task: asyncio.Task[None] | None = None
    self._subscribed = asyncio.Event()
```

#### stop

```python
stop() -> None
```

Cancel the background listener task.

Source code in `src/zeython/websockets.py`

```python
async def stop(self) -> None:
    """Cancel the background listener task."""
    if self._listener_task is not None:
        self._listener_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._listener_task
        self._listener_task = None
```

#### broadcast

```python
broadcast(
    message: str | dict, *, exclude: WebSocket | None = None
) -> None
```

Deliver to this process's own connections immediately (respecting `exclude`, which only ever refers to a connection on this process -- another process can't have the same object), then publish so every other process's listener relays it to theirs.

Source code in `src/zeython/websockets.py`

```python
async def broadcast(self, message: str | dict, *, exclude: WebSocket | None = None) -> None:
    """Deliver to this process's own connections immediately (respecting
    ``exclude``, which only ever refers to a connection on this
    process -- another process can't have the same object), then
    publish so every other process's listener relays it to theirs.
    """
    await super().broadcast(message, exclude=exclude)
    envelope = {"origin": self._instance_id, "payload": message}
    await self._client.publish(self._channel, json.dumps(envelope))
```

### WebSocketHubServiceProvider

```python
WebSocketHubServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Binds a process-local :class:`WebSocketHub` into the container.

`WEBSOCKET_ALLOWED_ORIGINS` -- comma-separated, e.g. `https://example.com,https://app.example.com` -- restricts handshakes to those origins (see :class:`WebSocketHub`'s cross-site hijacking note). Unset by default, matching every earlier release; set it once real browser clients are involved and you're not deliberately serving other origins too.

`WEBSOCKET_MAX_CONNECTIONS_PER_IP` -- caps concurrent connections from a single client (see :class:`WebSocketHub`'s resource-exhaustion note). Unset by default, matching every earlier release.

For a broadcast that reaches every worker process/machine, not just this one, bind :class:`RedisWebSocketHub` directly instead of registering this provider::

```text
app.container.singleton(WebSocketHub, lambda: RedisWebSocketHub(config.get("redis.url")))
```

See docs/redis.md.

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

## mail

Outbound email: a small `Mailer` interface, a log-only default so `zeython new` works with zero mail configuration, and an SMTP backend for when you actually have credentials.

### Message

```python
Message(
    to: str | list[str],
    subject: str,
    body: str,
    html: str | None = None,
    from_address: str | None = None,
)
```

An email to send. `to` accepts a single address or a list.

### LogMailer

Bases: `Mailer`

Writes the email to your app's logs instead of sending it.

The default (`MAIL_DRIVER=log`), so a fresh `zeython new` project can dispatch mail-sending jobs immediately without SMTP credentials. Switch to :class:`SmtpMailer` (`MAIL_DRIVER=smtp`) once you have real ones. See docs/mail.md.

### SmtpMailer

```python
SmtpMailer(
    *,
    host: str,
    port: int,
    username: str | None,
    password: str | None,
    use_tls: bool,
    default_from: str,
)
```

Bases: `Mailer`

Sends real email over SMTP, via the stdlib (no third-party dependency).

`smtplib` is blocking, so :meth:`send` runs it on a worker thread (`asyncio.to_thread`) rather than blocking the event loop.

Source code in `src/zeython/mail.py`

```python
def __init__(
    self,
    *,
    host: str,
    port: int,
    username: str | None,
    password: str | None,
    use_tls: bool,
    default_from: str,
) -> None:
    self.host = host
    self.port = port
    self.username = username
    self.password = password
    self.use_tls = use_tls
    self.default_from = default_from
```

### MailServiceProvider

```python
MailServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Binds a :class:`Mailer` into the container from `.env`.

- `MAIL_DRIVER` — `log` (default) or `smtp`
- `MAIL_HOST`, `MAIL_PORT` (default `587`)
- `MAIL_USERNAME`, `MAIL_PASSWORD`
- `MAIL_ENCRYPTION` — `tls` (default) or `none`
- `MAIL_FROM_ADDRESS` (default `no-reply@example.com`)

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

## notifications

Multi-channel notifications: one :class:`Notification` subclass describes what happened and which channels (`mail`, `database`, `broadcast`) should carry it; :func:`notify` fires all of them. Mirrors Laravel's Notification system.

Deliberately separate from :mod:`zeython.events` -- an event is "this happened, react however you like" (any number of independent listeners, no fixed shape); a notification is "tell *this one recipient*, on *these* channels, in *this* format" -- one `Notification` instance describes its own rendering per channel rather than leaving each listener to reinvent it.

### Notification

Base class for a notification.

Override :meth:`via` to pick channels for a given recipient, and whichever `to_*` builder each of those channels actually needs::

```text
class InvoicePaid(Notification):
    def __init__(self, invoice: Invoice) -> None:
        self.invoice = invoice

    def via(self, notifiable: Any) -> list[str]:
        return ["mail", "database"]

    def to_mail(self, notifiable: Any) -> Message:
        return Message(
            to=notifiable.email,
            subject="Invoice paid",
            body=f"Thanks! We received ${self.invoice.amount}.",
        )

    def to_database(self, notifiable: Any) -> dict:
        return {"invoice_id": self.invoice.id, "amount": self.invoice.amount}
```

### NotificationManager

```python
NotificationManager(
    container: Container,
    *,
    record_model: type[Model] | None = None,
)
```

Fires a :class:`Notification` at a recipient across whichever channels it asks for. Bound in the container by :class:`NotificationServiceProvider` -- use :func:`notify` from a request handler, or resolve this directly outside of one (a job, a scheduled task).

Source code in `src/zeython/notifications.py`

```python
def __init__(self, container: Container, *, record_model: type[Model] | None = None) -> None:
    self._container = container
    self.record_model = record_model
```

#### notify

```python
notify(notifiable: Any, notification: Notification) -> None
```

Send `notification` to `notifiable` on every channel :meth:`Notification.via` names.

A channel's own failure is logged and reported (see :mod:`zeython.error_monitoring`), not raised -- the same reasoning :class:`~zeython.events.EventDispatcher` uses for listeners: a down SMTP server shouldn't also silently swallow the in-app notification that would have told the user something happened.

Source code in `src/zeython/notifications.py`

```python
async def notify(self, notifiable: Any, notification: Notification) -> None:
    """Send ``notification`` to ``notifiable`` on every channel
    :meth:`Notification.via` names.

    A channel's own failure is logged and reported (see
    :mod:`zeython.error_monitoring`), not raised -- the same reasoning
    :class:`~zeython.events.EventDispatcher` uses for listeners: a
    down SMTP server shouldn't also silently swallow the in-app
    notification that would have told the user something happened.
    """
    for channel in notification.via(notifiable):
        try:
            await self._send(channel, notifiable, notification)
        except Exception as exc:
            report_exception(
                exc, channel=channel, notification=type(notification).__name__
            )
            logger.exception(
                "Notification channel %r failed for %s", channel, type(notification).__name__
            )
```

### NotificationServiceProvider

```python
NotificationServiceProvider(
    app: Any, *, record_model: type[Model] | None = None
)
```

Bases: `ServiceProvider`

Binds a :class:`NotificationManager` into the container.

```text
app.register(NotificationServiceProvider(app, record_model=Notification))
```

`record_model` is your own `Model` subclass for the `database` channel (columns: `notifiable_id`, `type`, `data`, `read_at`) -- generated by `zeython make notification` alongside a `Notification` example class, wired into a fresh project's `app/Models/notification.py` by default. Omit it if you only ever use the `mail`/`broadcast` channels; calling the `database` channel without one raises a `RuntimeError` naming the fix -- but :meth:`NotificationManager.notify` catches every channel's exception for isolation (a down SMTP server shouldn't also swallow an unrelated in-app notification), logging and reporting it rather than propagating it to your caller. Check the logs (or Sentry, if :mod:`zeython.error_monitoring` is configured) if a notification silently doesn't show up, rather than expecting `notify()` itself to raise.

Source code in `src/zeython/notifications.py`

```python
def __init__(self, app: Any, *, record_model: type[Model] | None = None) -> None:
    super().__init__(app)
    self.record_model = record_model
```

### notify

```python
notify(
    request: Request,
    notifiable: Any,
    notification: Notification,
) -> None
```

Send `notification` to `notifiable` using whichever :class:`NotificationManager` is bound in the container (see :class:`NotificationServiceProvider`). Outside of a request -- a job, a scheduled task -- resolve directly instead::

```text
manager = app.container.make(NotificationManager)
await manager.notify(user, WelcomeNotification())
```

Source code in `src/zeython/notifications.py`

```python
async def notify(request: Request, notifiable: Any, notification: Notification) -> None:
    """Send ``notification`` to ``notifiable`` using whichever
    :class:`NotificationManager` is bound in the container (see
    :class:`NotificationServiceProvider`). Outside of a request -- a job,
    a scheduled task -- resolve directly instead::

        manager = app.container.make(NotificationManager)
        await manager.notify(user, WelcomeNotification())
    """
    manager: NotificationManager = request.app.state.container.make(NotificationManager)
    await manager.notify(notifiable, notification)
```

### unread_notifications

```python
unread_notifications(
    notifiable: Any, record_model: type[Model]
) -> list[Model]
```

Every `record_model` row for `notifiable` not yet marked read, newest first -- the framework doesn't force a mixin onto your notifiable model to get this, just pass the same `record_model` you registered with :class:`NotificationServiceProvider`.

Source code in `src/zeython/notifications.py`

```python
async def unread_notifications(notifiable: Any, record_model: type[Model]) -> list[Model]:
    """Every ``record_model`` row for ``notifiable`` not yet marked read,
    newest first -- the framework doesn't force a mixin onto your
    notifiable model to get this, just pass the same ``record_model`` you
    registered with :class:`NotificationServiceProvider`."""
    rows = await record_model.find_by(notifiable_id=notifiable.id, read_at=None)
    return sorted(rows, key=lambda row: row.created_at, reverse=True)
```

### mark_as_read

```python
mark_as_read(notification: Model) -> Model
```

Stamp `notification.read_at` with the current time and save it.

Source code in `src/zeython/notifications.py`

```python
async def mark_as_read(notification: Model) -> Model:
    """Stamp ``notification.read_at`` with the current time and save it."""
    return await notification.update(read_at=datetime.now(UTC))
```

## webhooks

Outbound webhooks: notify a third party's URL whenever something happens in your app, the mirror image of :mod:`zeython.notifications` (which notifies a recipient *inside* your own app).

An endpoint subscribes to one event name; :func:`fire_webhook`/ :meth:`WebhookManager.fire` looks up every active subscriber for that event and hands each one off to the existing background-job queue (:mod:`zeython.queue`) as a :class:`DeliverWebhookJob` -- delivery, retries, and backoff are all the queue's own well-tested machinery, not reinvented here. Each POST carries an HMAC-SHA256 signature the receiver can verify, the same double-submit-adjacent idea CSRF uses: proof the payload came from you, not from whoever guessed the URL.

### DeliverWebhookJob

```python
DeliverWebhookJob(
    endpoint_id: int,
    event: str,
    payload: dict[str, Any] = dict(),
    max_attempts: int = 5,
)
```

Bases: `Job`

Delivers one webhook, dispatched by :meth:`WebhookManager.fire` -- retried by whichever :class:`~zeython.queue.Queue` is configured (capped exponential backoff under :class:`~zeython.queue.RedisQueue`) up to `max_attempts` times before giving up.

### WebhookManager

```python
WebhookManager(
    container: Container,
    *,
    endpoint_model: type[Model],
    delivery_model: type[Model] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
)
```

Looks up subscribers for an event and hands delivery off to the queue. Bound in the container by :class:`WebhookServiceProvider`.

Source code in `src/zeython/webhooks.py`

```python
def __init__(
    self,
    container: Container,
    *,
    endpoint_model: type[Model],
    delivery_model: type[Model] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    self._container = container
    self.endpoint_model = endpoint_model
    self.delivery_model = delivery_model
    self.timeout = timeout
```

#### fire

```python
fire(event: str, payload: dict[str, Any]) -> None
```

Queue a delivery to every active endpoint subscribed to `event`. A given endpoint's own dispatch failure (only possible under :class:`~zeython.queue.SyncQueue`, which runs a job inline rather than truly queuing it) is logged and reported, not raised -- the same isolation :class:`~zeython.notifications.NotificationManager` applies per channel, so one bad subscriber can't block delivery to the rest.

Source code in `src/zeython/webhooks.py`

```python
async def fire(self, event: str, payload: dict[str, Any]) -> None:
    """Queue a delivery to every active endpoint subscribed to
    ``event``. A given endpoint's own dispatch failure (only possible
    under :class:`~zeython.queue.SyncQueue`, which runs a job inline
    rather than truly queuing it) is logged and reported, not raised
    -- the same isolation :class:`~zeython.notifications.NotificationManager`
    applies per channel, so one bad subscriber can't block delivery
    to the rest.
    """
    endpoints = await self.endpoint_model.find_by(event=event, active=True)
    if not endpoints:
        return

    queue: Queue = self._container.make(Queue)
    for endpoint in endpoints:
        try:
            await queue.push(DeliverWebhookJob(endpoint_id=endpoint.id, event=event, payload=payload))
        except Exception as exc:
            report_exception(exc, endpoint_id=endpoint.id, event=event)
            logger.exception(
                "Failed to dispatch webhook delivery for endpoint %s (event %r)", endpoint.id, event
            )
```

#### deliver

```python
deliver(
    endpoint_id: int, event: str, payload: dict[str, Any]
) -> None
```

Actually perform one delivery attempt -- called by :class:`DeliverWebhookJob`, but usable directly too (a `zeython.mcp`-style introspection tool, or your own "resend this delivery" admin action).

Re-fetches the endpoint rather than trusting the state at the moment :meth:`fire` ran -- it may have been disabled or deleted in the time a retried delivery sat in the queue.

Source code in `src/zeython/webhooks.py`

```python
async def deliver(self, endpoint_id: int, event: str, payload: dict[str, Any]) -> None:
    """Actually perform one delivery attempt -- called by
    :class:`DeliverWebhookJob`, but usable directly too (a
    `zeython.mcp`-style introspection tool, or your own "resend this
    delivery" admin action).

    Re-fetches the endpoint rather than trusting the state at the
    moment :meth:`fire` ran -- it may have been disabled or deleted in
    the time a retried delivery sat in the queue.
    """
    endpoint: Any = await self.endpoint_model.find(endpoint_id)
    if endpoint is None or not endpoint.active:
        logger.info("Skipping webhook delivery for endpoint %s -- no longer active.", endpoint_id)
        return

    body = json.dumps({"event": event, "data": payload}, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", EVENT_HEADER: event}
    secret = getattr(endpoint, "secret", None)
    if secret:
        headers[SIGNATURE_HEADER] = sign_payload(secret, body)
    else:
        logger.warning(
            "Webhook endpoint %s (event %r) has no secret -- delivering unsigned. "
            "The receiver has no way to verify this payload actually came from you.",
            endpoint_id,
            event,
        )

    status_code: int | None = None
    error: str | None = None
    try:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(endpoint.url, content=body, headers=headers)
            status_code = response.status_code
            response.raise_for_status()
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        if self.delivery_model is not None:
            await self.delivery_model.create(
                endpoint_id=endpoint_id,
                event=event,
                status_code=status_code,
                success=error is None,
                error=error,
            )
```

### WebhookServiceProvider

```python
WebhookServiceProvider(
    app: Any,
    *,
    endpoint_model: type[Model],
    delivery_model: type[Model] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
)
```

Bases: `ServiceProvider`

Binds a :class:`WebhookManager` into the container.

```text
app.register(WebhookServiceProvider(app, endpoint_model=WebhookEndpoint))
```

`endpoint_model` is your own `Model` subclass for endpoint subscriptions (columns: `url`, `event`, `secret`, `active`) -- one row per (url, event) pair, so a single receiving URL that wants several event types just gets several rows. `delivery_model` is optional (columns: `endpoint_id`, `event`, `status_code`, `success`, `error`) -- if given, every delivery *attempt* (including retries) is logged there for an audit trail of what was sent and whether it arrived, mirroring what Stripe/GitHub show in their own webhook dashboards. Neither model is mandated by the framework, the same `record_model` pattern :class:`~zeython.notifications.NotificationServiceProvider` uses -- see docs/webhooks.md.

Source code in `src/zeython/webhooks.py`

```python
def __init__(
    self,
    app: Any,
    *,
    endpoint_model: type[Model],
    delivery_model: type[Model] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    super().__init__(app)
    self.endpoint_model = endpoint_model
    self.delivery_model = delivery_model
    self.timeout = timeout
```

### sign_payload

```python
sign_payload(secret: str, body: bytes) -> str
```

The hex-encoded HMAC-SHA256 signature of `body` under `secret` -- sent as the `X-Webhook-Signature` header on every delivery, and what :func:`verify_signature` checks a received payload against.

Source code in `src/zeython/webhooks.py`

```python
def sign_payload(secret: str, body: bytes) -> str:
    """The hex-encoded HMAC-SHA256 signature of ``body`` under ``secret`` --
    sent as the ``X-Webhook-Signature`` header on every delivery, and what
    :func:`verify_signature` checks a received payload against.
    """
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
```

### verify_signature

```python
verify_signature(
    secret: str, body: bytes, signature: str
) -> bool
```

`True` if `signature` is the correct HMAC-SHA256 of `body` under `secret` -- for code on the *receiving* end of a webhook (a Zeython app included) to check before trusting a delivered payload::

```text
async def receive_webhook(request):
    body = await request.body()
    signature = request.headers.get("X-Webhook-Signature", "")
    if not verify_signature(known_secret, body, signature):
        raise ForbiddenException("Bad webhook signature.")
```

Uses :func:`hmac.compare_digest` rather than `==` -- a naive string comparison leaks how many leading bytes matched through response timing, letting an attacker recover the correct signature one byte at a time.

Source code in `src/zeython/webhooks.py`

```python
def verify_signature(secret: str, body: bytes, signature: str) -> bool:
    """``True`` if ``signature`` is the correct HMAC-SHA256 of ``body`` under
    ``secret`` -- for code on the *receiving* end of a webhook (a Zeython
    app included) to check before trusting a delivered payload::

        async def receive_webhook(request):
            body = await request.body()
            signature = request.headers.get("X-Webhook-Signature", "")
            if not verify_signature(known_secret, body, signature):
                raise ForbiddenException("Bad webhook signature.")

    Uses :func:`hmac.compare_digest` rather than ``==`` -- a naive string
    comparison leaks how many leading bytes matched through response
    timing, letting an attacker recover the correct signature one byte at
    a time.
    """
    return hmac.compare_digest(sign_payload(secret, body), signature)
```

### fire_webhook

```python
fire_webhook(
    request: Request, event: str, payload: dict[str, Any]
) -> None
```

Fire `event` at every subscribed endpoint using whichever :class:`WebhookManager` is bound in the container (see :class:`WebhookServiceProvider`). Outside of a request -- an event listener, a scheduled task -- resolve directly instead::

```text
manager = app.container.make(WebhookManager)
await manager.fire("order.shipped", {"order_id": order.id})
```

Source code in `src/zeython/webhooks.py`

```python
async def fire_webhook(request: Request, event: str, payload: dict[str, Any]) -> None:
    """Fire ``event`` at every subscribed endpoint using whichever
    :class:`WebhookManager` is bound in the container (see
    :class:`WebhookServiceProvider`). Outside of a request -- an event
    listener, a scheduled task -- resolve directly instead::

        manager = app.container.make(WebhookManager)
        await manager.fire("order.shipped", {"order_id": order.id})
    """
    manager: WebhookManager = request.app.state.container.make(WebhookManager)
    await manager.fire(event, payload)
```

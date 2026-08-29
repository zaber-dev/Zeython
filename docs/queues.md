# Background Jobs

`zeython.queue` runs work off the request/response cycle: a `Job` you
define, a `dispatch()` call that queues it, and a queue that runs it —
`InMemoryQueue` by default, a background `asyncio` task with no framework
wiring required.

## Defining a job

```python
# app/Jobs/send_welcome_email_job.py
from dataclasses import dataclass
from zeython import Job, Mailer, Message

@dataclass
class SendWelcomeEmailJob(Job):
    to_email: str
    name: str

    async def handle(self, mailer: Mailer) -> None:
        await mailer.send(Message(to=self.to_email, subject="Welcome!", body=f"Hi {self.name}"))
```

```bash
zeython make job SendWelcomeEmail
```

Jobs are plain Python objects — the default queue never serializes them, so
constructor arguments can be anything (a `User` instance, an open file), not
just JSON-safe values. That's a trade-off, not a free lunch: see
[the process-local limitation](#the-default-queue-is-process-local) below.

### Injecting dependencies into `handle()`

Beyond `self`, `handle()` can declare any type-hinted parameter bound in the
container — `mailer: Mailer` above is resolved automatically when the queue
runs the job, the same autowiring `Container.call` uses everywhere else in
the framework. This is how `QueueServiceProvider` wires things up; if you
construct a `Queue` yourself without a container, `handle()` is called with
no extra arguments, so any declared params must be resolvable or the call
fails with a plain `TypeError` — loud, not silently ignored.

### Database access inside `handle()`

A job doesn't run inside the request that dispatched it — `InMemoryQueue`'s
background task, a separate `zeython queue work` process for `RedisQueue`,
even a retried `SyncQueue` attempt all outlive or sit outside whatever
request/response cycle pushed the job. So if `DatabaseServiceProvider` is
registered, every job gets its own fresh database session for the duration
of `handle()` — opened and committed the same way a request's is via
`DatabaseSessionMiddleware` — rather than reusing whatever session happened
to be live wherever `dispatch()`/`push()` was called. `Model.find()`,
`.create()`, and friends all work inside `handle()` exactly as they do in a
controller, with no extra wiring:

```python
@dataclass
class DeactivateStaleAccountsJob(Job):
    async def handle(self) -> None:
        stale = await User.find_by(last_seen_before=cutoff())
        for user in stale:
            await user.update(active=False)
```

## Dispatching from a request

```python
from zeython.queue import dispatch

async def register(self, request):
    user = await User.create(**data)
    await dispatch(request, SendWelcomeEmailJob(to_email=user.email, name=user.name))
    return JSONResponse(user.to_dict(), status_code=201)
```

`dispatch()` returns as soon as the job is queued — `handle()` runs
afterward, on a background task, so the response isn't held up by whatever
sending an email actually involves.

Outside a request (a script, another job), push directly to a resolved
queue: `await app.container.make(Queue).push(job)`.

## Setup

```python
# main.py
from zeython import Application, QueueServiceProvider

app = Application()
app.register(QueueServiceProvider)
```

## Failure handling

Set `max_attempts` on a job to retry it on failure:

```python
@dataclass
class SendWelcomeEmailJob(Job):
    to_email: str
    name: str
    max_attempts: int = 3

    async def handle(self) -> None:
        ...
```

Each failed attempt is logged (`zeython.queue`, at `ERROR`); once
`max_attempts` is exhausted, the job is dropped and a final "giving up" line
is logged. There's no dead-letter queue or alerting built in — that's
usually deployment-specific (log aggregation, an error tracker); wire your
job's `handle()` to report however you already do that.

## Delaying a job

```python
await dispatch(request, SendReminderEmailJob(...), delay=3600)  # in an hour
```

Works the same on every driver — `InMemoryQueue` schedules it via a
background task; `RedisQueue` scores it into a delayed set and picks it up
once the wait elapses (see below). `SyncQueue` ignores `delay` entirely and
runs the job immediately — it exists for tests/local dev, where "immediate"
is the whole point.

## `QUEUE_DRIVER=sync` for tests and local dev

```env
QUEUE_DRIVER=sync
```

Runs jobs immediately, in-line, with no background task — and, unlike the
default driver, doesn't catch and log exceptions; a failing job raises
straight through `dispatch()`. Useful when you want to see a job's side
effects (or failures) immediately rather than reasoning about timing.

## The default queue is process-local

`InMemoryQueue` holds jobs in this process's memory. A job pushed but not
yet run is lost if the process crashes or restarts — fine for non-critical
background work (a welcome email, warming a cache), a real limitation for
anything you'd be upset to silently lose (payment capture, anything that
must survive a crash). `RedisQueue` is the durable, opt-in alternative —
see below.

## `QUEUE_DRIVER=redis`: a durable queue

```env
QUEUE_DRIVER=redis
REDIS_URL=redis://localhost:6379/0
```

```bash
pip install zeython[redis]
```

A job pushed to `RedisQueue` survives a crash or restart of whatever
process pushed it — it lives in Redis until a **separate worker process**
picks it up and runs it:

```bash
zeython queue work
```

This is the real architectural difference from `InMemoryQueue`: jobs no
longer run inside your web server's own process. Run `zeython queue work`
as its own long-lived process (a second container/systemd unit/Procfile
line) alongside `zeython serve` — scale the two independently, and a web
server restart/deploy no longer drops in-flight jobs.

### Jobs must be `@dataclass`

`InMemoryQueue` never serializes a job — its constructor can hold anything,
even an open file or a live object. `RedisQueue` has to cross a process
boundary, so it JSON-encodes a job via `dataclasses.asdict()` and
reconstructs it on the worker side from the job's fully-qualified class
path. Every constructor field must be JSON-safe
(`str`/`int`/`float`/`bool`/`None`/`list`/`dict`) — pass a `user_id`, not a
`User` instance. A non-dataclass `Job` raises `TypeError` on `push()`,
immediately, not silently at run time on the worker.

One consequence: a job's own instance state (a counter it increments in
`handle()`, say) does **not** carry over between retries — the worker
reconstructs a fresh instance from the stored payload on every attempt.
Track cross-attempt state externally (a database row, a Redis key) if a
job's retry logic needs it.

### Retries and backoff

Same `max_attempts` as `InMemoryQueue`, but a failed attempt is retried
with capped exponential backoff (2s, 4s, 8s, ... up to 60s between
attempts) instead of immediately — a transient failure (a downstream API
having a bad minute) gets a real chance to clear before the next attempt,
rather than three attempts in the same second.

### Failed jobs

A job that exhausts `max_attempts` isn't dropped — it's moved to a
**failed-jobs list**, inspectable from code:

```python
from zeython.queue import RedisQueue

queue: RedisQueue = app.container.make(Queue)
for entry in await queue.failed_jobs():
    print(entry["job_class"], entry["error"], entry["failed_at"])
```

Each entry keeps the job's class path, its original payload, the final
exception (`repr()`), and a `failed_at` timestamp — everything needed to
re-drive it by hand (`job_cls(**entry["payload"])`, re-`push()`) once
whatever caused it to fail is fixed.

### Multiple queues

`QUEUE_NAME` (default `default`) picks which named queue
`QueueServiceProvider` binds — everything is namespaced under
`zeython:queue:<name>:` in Redis. Run a dedicated `zeython queue work`
process per queue name (each pointed at its own `.env`/`QUEUE_NAME`) for a
priority lane — emails on one, report generation on another — so a slow
queue never starves a fast one.

## Chaining jobs

`chain()` wraps a sequence of jobs so they run strictly one after another —
the next link only starts once the previous one finishes successfully:

```python
from zeython.queue import chain

await dispatch(request, chain([
    DownloadReportJob(report_id=report.id),
    EmailReportJob(report_id=report.id, to_email=user.email),
    CleanupTempFilesJob(report_id=report.id),
]))
```

`chain()` returns a single `Job` — dispatch it exactly like any other, with
`dispatch()` or `queue.push()`, on any driver. If a link exhausts its own
`max_attempts`, the chain simply stops there: the rest never runs, and the
failure is logged/reported the same way any other exhausted job's is, not
raised somewhere nothing is watching.

Every job in the chain must be a `@dataclass` — a chain has to serialize
its remaining links to hand off to a later, independent dispatch (the next
link), the same requirement `RedisQueue` has for any job (see above), and
for the same reason: instance state doesn't carry over between links or
across a retried link's attempts, only what's in the job's own constructor
fields.

## Batching jobs

`dispatch_batch()` runs a group of jobs independently — not in order, use
`chain()` for that — and tracks their combined progress:

```python
from zeython.queue import dispatch_batch

batch_id = await dispatch_batch(
    request,
    [ResizeImageJob(photo_id=p.id) for p in album.photos],
    then=NotifyGalleryReadyJob(album_id=album.id),
)
```

`then=` is a job dispatched automatically, exactly once, the moment every
job in the batch has finished — whether it succeeded or exhausted its own
retries. Its own `handle()` can call `batch_progress()` to see how many
failed — since the batch id isn't known until `dispatch_batch()` returns
(after `then` has already been constructed), pass your own via `batch_id=`
if `then` needs it:

```python
import uuid
from zeython.queue import batch_progress

@dataclass
class NotifyGalleryReadyJob(Job):
    batch_id: str

    async def handle(self, request: Request) -> None:
        progress = await batch_progress(request, self.batch_id)
        ...

batch_id = str(uuid.uuid4())
await dispatch_batch(
    request,
    [ResizeImageJob(photo_id=p.id) for p in album.photos],
    then=NotifyGalleryReadyJob(batch_id=batch_id),
    batch_id=batch_id,
)
```

Both `dispatch_batch()`'s own jobs and its `then=` job must be
`@dataclass`, for the same reason as `chain()`'s links.

### Where batch progress is tracked

`QueueServiceProvider` also binds a matching `BatchTracker`:
`InMemoryBatchTracker` (process-local, correct for `InMemoryQueue`/
`SyncQueue`) or `RedisBatchTracker` (correct across every worker process
draining a `RedisQueue`) — picked automatically from `QUEUE_DRIVER`, no
separate configuration. A finished batch's progress is kept around
afterward (so `batch_progress()` keeps answering once `then` has already
fired) — `InMemoryBatchTracker` for the life of the process, like
`InMemoryCache`; `RedisBatchTracker` for 24 hours, refreshed on every
completion so a long-running batch's own bookkeeping never expires
mid-flight.

### Combining chain() and dispatch_batch()

A batch member can be a `chain()` — a batch job that itself has to run a
few things in order. The other direction isn't supported: a chain link
only waits for its own wrapped job's `handle()`, not any further dispatch
it makes, so a batch placed inside a chain link wouldn't actually block
the next link from starting, and the batch's own completion wouldn't be
what advances the chain. To run something once a whole batch finishes, use
`dispatch_batch()`'s own `then=` — not by nesting the batch inside a chain.

## Logging

Job failures are only visible if something is actually printing INFO/ERROR
logs. `Application()` configures a sensible default for you (see the note in
`zeython.application._configure_default_logging`) unless you've already set
up logging yourself — you don't need to do anything for `logger.info(...)`
calls in your own jobs to show up during development.

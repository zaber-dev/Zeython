# Background Jobs

`zeython.queue` runs work off the request/response cycle: a `Job` you
define, a `dispatch()` call that queues it, and a queue that runs it —
`InMemoryQueue` by default, a background `asyncio` task with no framework
wiring required.

## Defining a job

```python
# app/Jobs/send_welcome_email_job.py
from dataclasses import dataclass
from zeython import Job

@dataclass
class SendWelcomeEmailJob(Job):
    to_email: str
    name: str

    async def handle(self) -> None:
        ...  # your actual email-sending code
```

```bash
zeython make job SendWelcomeEmail
```

Jobs are plain Python objects — the default queue never serializes them, so
constructor arguments can be anything (a `User` instance, an open file), not
just JSON-safe values. That's a trade-off, not a free lunch: see
[the process-local limitation](#the-default-queue-is-process-local) below.

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
must survive a crash). For that, implement `Queue` against a durable
backend (a database table, Redis, SQS) and bind it in place of the default:

```python
from zeython import Queue

app.container.singleton(Queue, lambda: MyDurableQueue(...))
```

## Logging

Job failures are only visible if something is actually printing INFO/ERROR
logs. `Application()` configures a sensible default for you (see the note in
`zeython.application._configure_default_logging`) unless you've already set
up logging yourself — you don't need to do anything for `logger.info(...)`
calls in your own jobs to show up during development.

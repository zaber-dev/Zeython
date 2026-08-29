"""Background jobs: run work off the request/response cycle.

The default queue is an ``asyncio.Queue`` living in this process's memory,
drained by a worker task that starts lazily on the first job you push — no
framework wiring required, and it needs no ASGI lifespan hook to work
correctly in tests or under a real server alike.

That also means: a job pushed but not yet run is lost if the process
crashes or restarts. Fine for non-critical background work (a welcome
email, warming a cache); a real limitation for anything you'd be upset to
silently lose (payment capture, anything that must survive a crash).
:class:`RedisQueue` is the durable, opt-in alternative — the same
trade-off as ``RateLimiter`` and ``Cache``, see docs/queues.md.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import importlib
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

from starlette.requests import Request

from zeython.container import Container
from zeython.db.session import Database
from zeython.error_monitoring import report_exception
from zeython.providers import ServiceProvider

logger = logging.getLogger("zeython.queue")


class Job(ABC):
    """A unit of background work. Subclass and implement :meth:`handle`.

    Jobs are plain Python objects (dataclasses are a natural fit) — the
    default queue never serializes them, so constructor arguments can be
    anything, not just JSON-safe values::

        @dataclass
        class SendWelcomeEmail(Job):
            email: str
            name: str

            async def handle(self) -> None:
                ...

    ``handle()`` can also declare type-hinted parameters beyond ``self`` to
    have them resolved from the container that dispatched the job (the same
    autowiring ``Container.call`` uses everywhere else)::

        async def handle(self, mailer: Mailer) -> None:
            await mailer.send(...)
    """

    #: How many times to attempt `handle()` before giving up and logging failure.
    max_attempts: int = 1

    @abstractmethod
    async def handle(self, *args: Any, **kwargs: Any) -> None: ...
    # ^ Typed to accept anything, not because handle() ever actually
    # receives positional/keyword args at the call site -- Queue._invoke()
    # always calls it via Container.call(job.handle), autowiring by
    # parameter name, or with no args at all -- but because a subclass
    # narrowing this to its own concrete, container-resolved parameters
    # (see the docstring above) would otherwise be an LSP-incompatible
    # override under mypy's stricter checking of *args/**kwargs-free
    # signatures.


class Queue(ABC):
    """Accepts jobs to run in the background.

    ``container``, if given, is used to autowire any extra type-hinted
    parameters on a job's ``handle()`` — see :class:`Job`. Without one,
    ``handle()`` is called with no arguments beyond ``self``.
    """

    def __init__(self, *, container: Container | None = None) -> None:
        self.container = container

    async def _invoke(self, job: Job) -> None:
        if self.container is None:
            await job.handle()
            return

        if self.container.has(Database):
            # A job's `handle()` doesn't run inside the request that pushed
            # it -- InMemoryQueue's worker task, RedisQueue's separate
            # `zeython queue work` process, and even SyncQueue's own retry
            # path all outlive or sit outside the request/response cycle
            # DatabaseSessionMiddleware scopes its session to. Reusing that
            # request's session here would mean either a `RuntimeError` (a
            # fresh RedisQueue worker process never had one) or, worse,
            # silently reusing a session the middleware already committed
            # and closed -- further writes on it would flush but never get
            # committed again, vanishing invisibly. A dedicated session per
            # job, opened and committed the same way a request's is, is the
            # fix -- mirroring the one-session-per-unit-of-work rule this
            # framework applies everywhere else.
            database: Database = self.container.make(Database)
            async with database.session():
                await self.container.call(job.handle)
        else:
            await self.container.call(job.handle)

    @abstractmethod
    async def push(self, job: Job, *, delay: float = 0.0) -> None:
        """Queue ``job`` to run -- immediately, or after ``delay`` seconds."""


class InMemoryQueue(Queue):
    """Runs jobs on a background ``asyncio`` task in this process.

    The worker starts on the first :meth:`push` and keeps running for the
    life of the event loop. Failed jobs are retried up to
    ``job.max_attempts`` times, with each failure logged; :meth:`close` is
    available for a clean shutdown (mainly useful in tests, to avoid
    "task was destroyed but it is pending" warnings at interpreter exit).
    ``delay`` schedules a job to be enqueued after a wait rather than
    immediately, via a tracked background task -- also cleaned up by
    :meth:`close`.
    """

    def __init__(self, *, container: Container | None = None) -> None:
        super().__init__(container=container)
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._delayed_tasks: set[asyncio.Task[None]] = set()

    async def push(self, job: Job, *, delay: float = 0.0) -> None:
        self._ensure_worker()
        if delay > 0:
            task = asyncio.create_task(self._put_after_delay(job, delay))
            self._delayed_tasks.add(task)
            task.add_done_callback(self._delayed_tasks.discard)
        else:
            await self._queue.put(job)

    async def _put_after_delay(self, job: Job, delay: float) -> None:
        await asyncio.sleep(delay)
        await self._queue.put(job)

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

    def _ensure_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def _worker_loop(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                await self._run_with_retries(job)
            finally:
                self._queue.task_done()

    async def _run_with_retries(self, job: Job) -> None:
        for attempt in range(1, job.max_attempts + 1):
            try:
                await self._invoke(job)
                return
            except Exception as exc:
                logger.exception(
                    "Job %s failed (attempt %d/%d)", type(job).__name__, attempt, job.max_attempts
                )
                if attempt == job.max_attempts:
                    # Only the final, exhausted attempt is reported -- a
                    # transient failure that a retry then fixes isn't
                    # something worth an alert.
                    report_exception(exc, job=type(job).__name__)
        logger.error("Job %s exhausted %d attempt(s); giving up", type(job).__name__, job.max_attempts)


class SyncQueue(Queue):
    """Runs jobs immediately and synchronously — no background task, no retries.

    Meant for tests and local dev: failures raise straight through `push()`
    instead of being caught and logged, so you see them immediately rather
    than digging through logs. ``delay`` is ignored -- a synchronous,
    immediate-execution queue has nothing to schedule against.
    """

    async def push(self, job: Job, *, delay: float = 0.0) -> None:
        await self._invoke(job)


def _serialize_job(job: Job) -> str:
    if not dataclasses.is_dataclass(job):
        raise TypeError(
            f"{type(job).__name__} must be a @dataclass to use with RedisQueue -- a durable queue has "
            "to serialize a job to survive a process restart, and dataclasses.asdict() is how it does "
            "that. Every constructor field must be JSON-safe (str/int/float/bool/None/list/dict)."
        )
    return json.dumps(
        {
            # A per-push unique id, unused by _deserialize_job itself but
            # carried through every re-serialization (retry, requeue) --
            # see RedisQueue.push()'s use of it for why this has to be here.
            "_id": uuid.uuid4().hex,
            "job_class": f"{type(job).__module__}.{type(job).__qualname__}",
            "payload": dataclasses.asdict(job),
            "attempts": 0,
            "max_attempts": job.max_attempts,
        }
    )


def _deserialize_job(raw: str) -> tuple[Job, dict[str, Any]]:
    data = json.loads(raw)
    module_name, _, class_name = data["job_class"].rpartition(".")
    module = importlib.import_module(module_name)
    job_cls = getattr(module, class_name)
    job = job_cls(**data["payload"])
    job.max_attempts = data["max_attempts"]
    return job, data


class RedisQueue(Queue):
    """A Redis-backed durable queue: a job pushed here survives a crash or
    restart of the process that pushed it, and is processed by a separate
    worker process (``zeython queue work``) rather than a background task
    inside the web server. Requires the ``redis`` extra
    (``pip install zeython[redis]``).

    Jobs must be ``@dataclass`` subclasses of :class:`Job` -- see
    :func:`_serialize_job`. Failed attempts are retried with capped
    exponential backoff (2, 4, 8, ... up to 60 seconds between attempts);
    a job that exhausts ``max_attempts`` is moved to a **failed-jobs list**
    instead of being dropped, so nothing that couldn't be processed is
    silently lost -- see :meth:`failed_jobs`.

    All keys are namespaced under ``prefix`` + ``queue_name`` (default
    ``"zeython:queue:default:"``) — safe to point at a Redis instance
    shared with other subsystems (cache, rate limiting, sessions).
    """

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

    @property
    def _pending_key(self) -> str:
        return f"{self._base}pending"

    @property
    def _delayed_key(self) -> str:
        return f"{self._base}delayed"

    @property
    def _failed_key(self) -> str:
        return f"{self._base}failed"

    async def push(self, job: Job, *, delay: float = 0.0) -> None:
        raw = _serialize_job(job)
        if delay > 0:
            # The Redis sorted set backing the delayed queue requires unique
            # *members* -- ZADD on an existing member just updates its
            # score, it doesn't add a second entry. Two jobs that would
            # otherwise serialize identically (same class + payload +
            # attempts, e.g. two independent dispatches of the same job
            # with the same arguments) collapse into one entry without
            # _serialize_job's per-push "_id", silently dropping one push.
            await self._client.zadd(self._delayed_key, {raw: time.time() + delay})
        else:
            await self._client.lpush(self._pending_key, raw)

    async def failed_jobs(self) -> list[dict[str, Any]]:
        """Every job that exhausted its retries, most recently failed first."""
        raw_entries = await self._client.lrange(self._failed_key, 0, -1)
        return [json.loads(entry) for entry in raw_entries]

    async def close(self) -> None:
        await self._client.aclose()

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

    async def _reclaim_delayed(self) -> None:
        now = time.time()
        # zrangebyscore()'s stub return type covers a withscores=True variant
        # we never use; without it, every element is always bytes|str.
        ready: list[bytes | str] = await self._client.zrangebyscore(
            self._delayed_key, "-inf", now
        )  # type: ignore[assignment]
        for raw in ready:
            # ZREM's return value disambiguates concurrent workers racing
            # the same ready entry -- only the one that actually removed it
            # (return value 1) re-enqueues it, so it's processed exactly once.
            removed = await self._client.zrem(self._delayed_key, raw)
            if removed:
                await self._client.lpush(self._pending_key, raw)

    async def _process(self, raw: str) -> None:
        job, data = _deserialize_job(raw)
        try:
            await self._invoke(job)
        except Exception as exc:
            data["attempts"] += 1
            job_class = data["job_class"]
            if data["attempts"] < data["max_attempts"]:
                backoff = min(2**data["attempts"], 60)
                logger.exception(
                    "Job %s failed (attempt %d/%d), retrying in %ds",
                    job_class,
                    data["attempts"],
                    data["max_attempts"],
                    backoff,
                )
                await self._client.zadd(self._delayed_key, {json.dumps(data): time.time() + backoff})
            else:
                logger.error(
                    "Job %s exhausted %d attempt(s); moved to the failed-jobs list: %s",
                    job_class,
                    data["max_attempts"],
                    exc,
                )
                report_exception(exc, job=job_class)
                data["error"] = repr(exc)
                data["failed_at"] = time.time()
                await self._client.lpush(self._failed_key, json.dumps(data))


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


class QueueServiceProvider(ServiceProvider):
    """Binds a :class:`Queue` into the container.

    ``.env``: ``QUEUE_DRIVER`` —

    - ``memory`` (default) — :class:`InMemoryQueue`, a background task in
      this process. Jobs are lost on crash/restart.
    - ``sync`` — :class:`SyncQueue`, runs jobs immediately in-line; useful
      for tests/local dev.
    - ``redis`` — :class:`RedisQueue`, durable, processed by a separate
      ``zeython queue work`` process. Requires ``REDIS_URL`` and the
      ``redis`` extra. ``QUEUE_NAME`` picks the queue (default ``default``)
      -- useful if you want a dedicated worker/priority lane for, say,
      emails vs. report generation.
    """

    def register(self) -> None:
        driver = self.config.get("queue.driver", "memory")
        queue: Queue
        if driver == "redis":
            queue = RedisQueue(
                self.config.get("redis.url"),
                container=self.container,
                queue_name=self.config.get("queue.name", "default"),
            )
        elif driver == "sync":
            queue = SyncQueue(container=self.container)
        else:
            queue = InMemoryQueue(container=self.container)
        self.container.singleton(Queue, lambda: queue)


__all__ = [
    "Job",
    "Queue",
    "InMemoryQueue",
    "SyncQueue",
    "RedisQueue",
    "dispatch",
    "QueueServiceProvider",
]

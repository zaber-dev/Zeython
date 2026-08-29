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


def _job_to_spec(job: Job, *, purpose: str = "RedisQueue") -> dict[str, Any]:
    """A JSON-safe ``{job_class, payload, max_attempts}`` description of
    ``job``, reconstructible via :func:`_job_from_spec` -- shared by
    :class:`RedisQueue`'s own wire format and by :func:`chain`/
    :func:`dispatch_batch`, which both need to hand a job off to a *later*,
    independent dispatch (the next link, a batch member's retry, the
    ``then`` callback) rather than run it inline.
    """
    if not dataclasses.is_dataclass(job):
        raise TypeError(
            f"{type(job).__name__} must be a @dataclass to use with {purpose} -- it has to be "
            "serialized to hand off to a later, independent dispatch, and dataclasses.asdict() is "
            "how that happens. Every constructor field must be JSON-safe (str/int/float/bool/None/list/dict)."
        )
    return {
        "job_class": f"{type(job).__module__}.{type(job).__qualname__}",
        "payload": dataclasses.asdict(job),
        "max_attempts": job.max_attempts,
    }


def _job_from_spec(spec: dict[str, Any]) -> Job:
    module_name, _, class_name = spec["job_class"].rpartition(".")
    module = importlib.import_module(module_name)
    job_cls = getattr(module, class_name)
    job = job_cls(**spec["payload"])
    job.max_attempts = spec["max_attempts"]
    return job


def _serialize_job(job: Job) -> str:
    spec = _job_to_spec(job)
    return json.dumps(
        {
            # A per-push unique id, unused by _deserialize_job itself but
            # carried through every re-serialization (retry, requeue) --
            # see RedisQueue.push()'s use of it for why this has to be here.
            "_id": uuid.uuid4().hex,
            "attempts": 0,
            **spec,
        }
    )


def _deserialize_job(raw: str) -> tuple[Job, dict[str, Any]]:
    data = json.loads(raw)
    return _job_from_spec(data), data


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


@dataclasses.dataclass
class _ChainedJob(Job):
    """Runs the job described by ``spec``, then (only on success) dispatches
    the next link back onto whichever queue is running this one -- returned
    by :func:`chain`, not constructed directly.

    A failing link is retried like any other job (its own ``max_attempts``,
    via ``__post_init__`` below), by the underlying queue's own existing
    retry mechanism -- ``handle()`` itself has no retry logic of its own,
    it just re-raises. Once a link exhausts its retries, the chain simply
    stops there: nothing pushes the remaining links, and the failure is
    logged/reported exactly the way any other exhausted job's is.
    """

    spec: dict[str, Any]
    remaining: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    def __post_init__(self) -> None:
        self.max_attempts = self.spec["max_attempts"]

    async def handle(self, container: Container, queue: Queue) -> None:
        job = _job_from_spec(self.spec)
        await container.call(job.handle)
        if self.remaining:
            next_spec, *rest = self.remaining
            await queue.push(_ChainedJob(spec=next_spec, remaining=rest))


def chain(jobs: list[Job]) -> Job:
    """Wrap ``jobs`` so they run strictly one after another — the next link
    only starts once the previous one finishes successfully::

        await dispatch(request, chain([DownloadReport(), EmailReport(), CleanupTempFiles()]))

    Returns a single ``Job`` — dispatch it exactly like any other. If a
    link exhausts its own ``max_attempts``, the rest of the chain never
    runs (logged and reported the same way any other exhausted job is,
    not raised somewhere nothing is watching).

    Every job in the chain must be a ``@dataclass`` — a chain has to
    serialize its remaining links to hand off to a later, independent
    dispatch (the next link), the same requirement :class:`RedisQueue` has
    for any job it runs. To run something once a *group* of independent
    jobs all finish, use :func:`dispatch_batch` instead — nesting one
    inside the other isn't supported: a chain link only waits for the
    wrapped job's own ``handle()``, not any further dispatch it makes, so
    a batch placed inside a chain link wouldn't actually block the next
    link, and a chain placed inside a batch would only count that batch
    member done once the chain's *first* link finishes.
    """
    if not jobs:
        raise ValueError("chain() needs at least one job")
    specs = [_job_to_spec(job, purpose="chain()") for job in jobs]
    first, *rest = specs
    return _ChainedJob(spec=first, remaining=rest)


@dataclasses.dataclass(frozen=True)
class BatchProgress:
    """A snapshot of a batch's progress — see :func:`dispatch_batch`."""

    total: int
    pending: int
    failed: int

    @property
    def finished(self) -> bool:
        """Whether every job in the batch has run (successfully or not)."""
        return self.pending == 0

    @property
    def succeeded(self) -> int:
        """How many jobs have finished without exhausting their retries."""
        return self.total - self.pending - self.failed


class BatchTracker(ABC):
    """Tracks how many jobs in a batch are still pending — the shared state
    :func:`dispatch_batch` needs to know when the *last* one finishes.
    Bound automatically by :class:`QueueServiceProvider`, matching whichever
    ``Queue`` driver is active; not meant to be used directly.
    """

    @abstractmethod
    async def create(self, batch_id: str, total: int, *, then: dict[str, Any] | None = None) -> None:
        """Register a new batch of ``total`` jobs, optionally with a
        serialized ``then`` job spec to hand back via :meth:`get_then` once it finishes.
        """

    @abstractmethod
    async def record_completion(self, batch_id: str, *, failed: bool) -> BatchProgress:
        """Record that one job in ``batch_id`` finished, and return the batch's progress so far."""

    @abstractmethod
    async def progress(self, batch_id: str) -> BatchProgress | None:
        """The current progress of ``batch_id``, or ``None`` if unknown."""

    @abstractmethod
    async def get_then(self, batch_id: str) -> dict[str, Any] | None:
        """The batch's ``then`` job spec, if it was given one."""


class InMemoryBatchTracker(BatchTracker):
    """Process-local batch progress — correct for :class:`InMemoryQueue` and
    :class:`SyncQueue`, which only ever run in this same process.

    A finished batch's state is kept for the life of the process (so
    :func:`batch_progress` keeps answering after ``then`` fires) — like
    :class:`~zeython.cache.InMemoryCache`, fine for typical usage, not a
    fit for creating unboundedly many batches over a long-running
    process's lifetime.
    """

    def __init__(self) -> None:
        self._batches: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def create(self, batch_id: str, total: int, *, then: dict[str, Any] | None = None) -> None:
        async with self._lock:
            self._batches[batch_id] = {"total": total, "pending": total, "failed": 0, "then": then}

    async def record_completion(self, batch_id: str, *, failed: bool) -> BatchProgress:
        async with self._lock:
            state = self._batches[batch_id]
            state["pending"] -= 1
            if failed:
                state["failed"] += 1
            return BatchProgress(total=state["total"], pending=state["pending"], failed=state["failed"])

    async def progress(self, batch_id: str) -> BatchProgress | None:
        state = self._batches.get(batch_id)
        if state is None:
            return None
        return BatchProgress(total=state["total"], pending=state["pending"], failed=state["failed"])

    async def get_then(self, batch_id: str) -> dict[str, Any] | None:
        state = self._batches.get(batch_id)
        return state["then"] if state else None


class RedisBatchTracker(BatchTracker):
    """A Redis-backed :class:`BatchTracker`, correct across every worker
    process draining a :class:`RedisQueue` — :class:`InMemoryBatchTracker`'s
    limitation. Requires the ``redis`` extra (``pip install zeython[redis]``).

    Batch state expires after ``ttl`` seconds (default 24h) so completed
    bookkeeping doesn't accumulate in Redis forever; every completion
    refreshes it, so only a genuinely abandoned batch id is ever actually lost.
    """

    def __init__(self, url: str, *, prefix: str = "zeython:batch:", ttl: float = 86400.0) -> None:
        try:
            from redis.asyncio import Redis
        except ImportError as exc:
            raise ImportError(
                "RedisBatchTracker requires the redis package. Install it with: pip install zeython[redis]"
            ) from exc

        self._client = Redis.from_url(url)
        self._prefix = prefix
        self._ttl = ttl

    def _key(self, batch_id: str, field: str) -> str:
        return f"{self._prefix}{batch_id}:{field}"

    async def create(self, batch_id: str, total: int, *, then: dict[str, Any] | None = None) -> None:
        ttl = int(self._ttl)
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.set(self._key(batch_id, "total"), total, ex=ttl)
            pipe.set(self._key(batch_id, "pending"), total, ex=ttl)
            pipe.set(self._key(batch_id, "failed"), 0, ex=ttl)
            if then is not None:
                pipe.set(self._key(batch_id, "then"), json.dumps(then), ex=ttl)
            await pipe.execute()

    async def record_completion(self, batch_id: str, *, failed: bool) -> BatchProgress:
        ttl = int(self._ttl)
        pending = await self._client.decr(self._key(batch_id, "pending"))
        if failed:
            failed_count = await self._client.incr(self._key(batch_id, "failed"))
        else:
            failed_count = int(await self._client.get(self._key(batch_id, "failed")) or 0)
        total = int(await self._client.get(self._key(batch_id, "total")) or 0)
        # Refresh the TTL on every completion so a long-running batch's
        # bookkeeping doesn't expire mid-flight -- only a batch that's
        # truly been abandoned (no completions at all for a full `ttl`) is
        # ever actually lost.
        await self._client.expire(self._key(batch_id, "pending"), ttl)
        await self._client.expire(self._key(batch_id, "failed"), ttl)
        return BatchProgress(total=total, pending=pending, failed=failed_count)

    async def progress(self, batch_id: str) -> BatchProgress | None:
        total = await self._client.get(self._key(batch_id, "total"))
        if total is None:
            return None
        pending = await self._client.get(self._key(batch_id, "pending"))
        failed_count = await self._client.get(self._key(batch_id, "failed"))
        return BatchProgress(total=int(total), pending=int(pending or 0), failed=int(failed_count or 0))

    async def get_then(self, batch_id: str) -> dict[str, Any] | None:
        raw = await self._client.get(self._key(batch_id, "then"))
        return json.loads(raw) if raw is not None else None

    async def close(self) -> None:
        await self._client.aclose()


@dataclasses.dataclass
class _BatchedJob(Job):
    """Runs the job described by ``spec`` — retrying it internally, up to
    its own ``max_attempts``, rather than letting the underlying queue's
    own retry mechanism retry this wrapper — then records the outcome with
    ``batch_id``'s :class:`BatchTracker` exactly once, and fires the
    batch's ``then`` job (if any) the moment that recording reveals every
    job in the batch has finished. Returned by :func:`dispatch_batch`, not
    constructed directly.

    Retrying internally (rather than via the wrapper's own ``max_attempts``,
    fixed at 1) is what keeps that recording to exactly once per job
    regardless of how many attempts it took -- the outer queue only ever
    sees a single pass over this wrapper, succeeding or raising once.
    """

    spec: dict[str, Any]
    batch_id: str
    max_attempts: int = 1

    async def handle(self, container: Container, queue: Queue) -> None:
        job = _job_from_spec(self.spec)
        job_class = self.spec["job_class"]
        own_max_attempts = self.spec["max_attempts"]
        exc: Exception | None = None
        for attempt in range(1, own_max_attempts + 1):
            try:
                await container.call(job.handle)
                exc = None
                break
            except Exception as caught:
                exc = caught
                logger.exception("Batched job %s failed (attempt %d/%d)", job_class, attempt, own_max_attempts)

        tracker: BatchTracker = container.make(BatchTracker)
        progress = await tracker.record_completion(self.batch_id, failed=exc is not None)
        if progress.finished:
            then_spec = await tracker.get_then(self.batch_id)
            if then_spec is not None:
                await queue.push(_job_from_spec(then_spec))

        if exc is not None:
            # The wrapper's own max_attempts is fixed at 1, so this is the
            # underlying queue's *only* pass over this wrapper -- its usual
            # exhausted-job handling (logging, report_exception, RedisQueue's
            # failed-jobs list) runs exactly as it would for any other job
            # that ran out of retries, without us duplicating any of it here.
            raise exc


async def dispatch_batch(request: Request, jobs: list[Job], *, then: Job | None = None, batch_id: str | None = None) -> str:
    """Dispatch every job in ``jobs`` independently — for strict order, use
    :func:`chain` instead — and track their combined progress under a
    batch id this returns::

        batch_id = await dispatch_batch(request, [ResizeImage(p) for p in photos], then=NotifyGalleryReady(album.id))

    Pass ``then=`` a job to dispatch automatically, exactly once, the
    moment every job in the batch has finished — whether it succeeded or
    exhausted its own retries. ``then``'s own ``handle()`` can call
    :func:`batch_progress` to see how many failed; since the batch id isn't
    known until this call returns (after ``then`` has already been
    constructed), pass your own via ``batch_id=`` if ``then`` needs it::

        batch_id = str(uuid.uuid4())
        await dispatch_batch(request, jobs, then=NotifyGalleryReady(batch_id=batch_id), batch_id=batch_id)

    Every job (and ``then``, if given) must be a ``@dataclass`` — see
    :func:`chain`.
    """
    if not jobs:
        raise ValueError("dispatch_batch() needs at least one job")
    container: Container = request.app.state.container
    tracker: BatchTracker = container.make(BatchTracker)
    queue: Queue = container.make(Queue)

    batch_id = batch_id or uuid.uuid4().hex
    then_spec = _job_to_spec(then, purpose="dispatch_batch()'s then=") if then is not None else None
    await tracker.create(batch_id, total=len(jobs), then=then_spec)
    for job in jobs:
        await queue.push(_BatchedJob(spec=_job_to_spec(job, purpose="dispatch_batch()"), batch_id=batch_id))
    return batch_id


async def batch_progress(request: Request, batch_id: str) -> BatchProgress | None:
    """The current progress of the batch ``batch_id`` (from
    :func:`dispatch_batch`), or ``None`` if unknown — never existed, or,
    for :class:`RedisBatchTracker` only, expired (see its docstring).
    """
    tracker: BatchTracker = request.app.state.container.make(BatchTracker)
    return await tracker.progress(batch_id)


class QueueServiceProvider(ServiceProvider):
    """Binds a :class:`Queue` into the container, plus the matching
    :class:`BatchTracker` :func:`dispatch_batch` needs (:class:`RedisBatchTracker`
    for the ``redis`` driver, :class:`InMemoryBatchTracker` for the others).

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
        tracker: BatchTracker
        if driver == "redis":
            queue = RedisQueue(
                self.config.get("redis.url"),
                container=self.container,
                queue_name=self.config.get("queue.name", "default"),
            )
            tracker = RedisBatchTracker(self.config.get("redis.url"))
        elif driver == "sync":
            queue = SyncQueue(container=self.container)
            tracker = InMemoryBatchTracker()
        else:
            queue = InMemoryQueue(container=self.container)
            tracker = InMemoryBatchTracker()
        self.container.singleton(Queue, lambda: queue)
        self.container.singleton(BatchTracker, lambda: tracker)


__all__ = [
    "BatchProgress",
    "BatchTracker",
    "InMemoryBatchTracker",
    "InMemoryQueue",
    "Job",
    "Queue",
    "QueueServiceProvider",
    "RedisBatchTracker",
    "RedisQueue",
    "SyncQueue",
    "batch_progress",
    "chain",
    "dispatch",
    "dispatch_batch",
]

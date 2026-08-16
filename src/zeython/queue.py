"""Background jobs: run work off the request/response cycle.

The default queue is an ``asyncio.Queue`` living in this process's memory,
drained by a worker task that starts lazily on the first job you push — no
framework wiring required, and it needs no ASGI lifespan hook to work
correctly in tests or under a real server alike.

That also means: a job pushed but not yet run is lost if the process
crashes or restarts. Fine for non-critical background work (a welcome
email, warming a cache); a real limitation for anything you'd be upset to
silently lose (payment capture, anything that must survive a crash).
Implement ``Queue`` against a durable backend (a database table, Redis, SQS)
for that — the same trade-off as ``RateLimiter`` and ``Storage``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from abc import ABC, abstractmethod

from starlette.requests import Request

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
    """

    #: How many times to attempt `handle()` before giving up and logging failure.
    max_attempts: int = 1

    @abstractmethod
    async def handle(self) -> None: ...


class Queue(ABC):
    """Accepts jobs to run in the background."""

    @abstractmethod
    async def push(self, job: Job) -> None: ...


class InMemoryQueue(Queue):
    """Runs jobs on a background ``asyncio`` task in this process.

    The worker starts on the first :meth:`push` and keeps running for the
    life of the event loop. Failed jobs are retried up to
    ``job.max_attempts`` times, with each failure logged; :meth:`close` is
    available for a clean shutdown (mainly useful in tests, to avoid
    "task was destroyed but it is pending" warnings at interpreter exit).
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None

    async def push(self, job: Job) -> None:
        self._ensure_worker()
        await self._queue.put(job)

    async def join(self) -> None:
        """Block until every job pushed so far has finished running. Mainly for tests."""
        await self._queue.join()

    async def close(self) -> None:
        """Cancel the background worker task, if one is running."""
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
                await job.handle()
                return
            except Exception:
                logger.exception(
                    "Job %s failed (attempt %d/%d)", type(job).__name__, attempt, job.max_attempts
                )
        logger.error("Job %s exhausted %d attempt(s); giving up", type(job).__name__, job.max_attempts)


class SyncQueue(Queue):
    """Runs jobs immediately and synchronously — no background task, no retries.

    Meant for tests and local dev: failures raise straight through `push()`
    instead of being caught and logged, so you see them immediately rather
    than digging through logs.
    """

    async def push(self, job: Job) -> None:
        await job.handle()


async def dispatch(request: Request, job: Job) -> None:
    """Queue ``job`` to run in the background rather than blocking this request.

    Uses whichever ``Queue`` is bound in the container — :class:`InMemoryQueue`
    by default, :class:`SyncQueue` if ``QUEUE_DRIVER=sync`` (see
    :class:`QueueServiceProvider`). Outside of a request, push directly to a
    resolved queue instead: ``await app.container.make(Queue).push(job)``.
    """
    queue: Queue = request.app.state.container.make(Queue)
    await queue.push(job)


class QueueServiceProvider(ServiceProvider):
    """Binds a :class:`Queue` into the container.

    ``.env``: ``QUEUE_DRIVER`` — ``memory`` (default, background task) or
    ``sync`` (run jobs immediately in-line; useful for tests/local dev).
    """

    def register(self) -> None:
        driver = self.config.get("queue.driver", "memory")
        queue: Queue = SyncQueue() if driver == "sync" else InMemoryQueue()
        self.container.singleton(Queue, lambda: queue)


__all__ = ["Job", "Queue", "InMemoryQueue", "SyncQueue", "dispatch", "QueueServiceProvider"]

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from starlette.responses import JSONResponse

import zeython.queue as queue_module
from zeython.application import Application
from zeython.config import Config
from zeython.container import Container
from zeython.queue import InMemoryQueue, Job, Queue, QueueServiceProvider, SyncQueue, dispatch
from zeython.testing import client


@dataclass
class RecordingJob(Job):
    """Appends to a shared list when it runs -- the simplest possible observable side effect."""

    log: list[str]
    value: str

    async def handle(self) -> None:
        self.log.append(self.value)


@dataclass
class AlwaysFailsJob(Job):
    attempts_log: list[int]
    max_attempts: int = 3

    async def handle(self) -> None:
        self.attempts_log.append(len(self.attempts_log) + 1)
        raise RuntimeError("this job always fails")


@dataclass
class FailsThenSucceedsJob(Job):
    log: list[str]
    fail_times: int
    max_attempts: int = 5
    _calls: int = field(default=0, init=False)

    async def handle(self) -> None:
        self._calls += 1
        if self._calls <= self.fail_times:
            raise RuntimeError("not yet")
        self.log.append("succeeded")


# -- InMemoryQueue ------------------------------------------------------------------


async def test_pushed_job_runs_in_the_background() -> None:
    queue = InMemoryQueue()
    log: list[str] = []

    await queue.push(RecordingJob(log=log, value="hello"))
    await queue.join()

    assert log == ["hello"]
    await queue.close()


async def test_jobs_run_in_fifo_order() -> None:
    queue = InMemoryQueue()
    log: list[str] = []

    await queue.push(RecordingJob(log=log, value="first"))
    await queue.push(RecordingJob(log=log, value="second"))
    await queue.push(RecordingJob(log=log, value="third"))
    await queue.join()

    assert log == ["first", "second", "third"]
    await queue.close()


async def test_failed_job_is_retried_up_to_max_attempts() -> None:
    queue = InMemoryQueue()
    attempts: list[int] = []

    await queue.push(AlwaysFailsJob(attempts_log=attempts, max_attempts=3))
    await queue.join()

    assert attempts == [1, 2, 3]
    await queue.close()


async def test_exhausted_job_reports_to_error_monitoring_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    reported: list[BaseException] = []
    monkeypatch.setattr(queue_module, "report_exception", lambda exc, **tags: reported.append(exc))

    queue = InMemoryQueue()
    attempts: list[int] = []

    await queue.push(AlwaysFailsJob(attempts_log=attempts, max_attempts=3))
    await queue.join()

    # Not once per retry (3 failed attempts) -- only the final one, since a
    # transient failure a retry then fixes isn't worth an alert.
    assert len(reported) == 1
    assert isinstance(reported[0], RuntimeError)
    await queue.close()


async def test_job_succeeds_after_transient_failures() -> None:
    queue = InMemoryQueue()
    log: list[str] = []

    await queue.push(FailsThenSucceedsJob(log=log, fail_times=2))
    await queue.join()

    assert log == ["succeeded"]
    await queue.close()


async def test_one_failing_job_does_not_block_the_next() -> None:
    queue = InMemoryQueue()
    log: list[str] = []
    attempts: list[int] = []

    await queue.push(AlwaysFailsJob(attempts_log=attempts, max_attempts=1))
    await queue.push(RecordingJob(log=log, value="still runs"))
    await queue.join()

    assert log == ["still runs"]
    await queue.close()


async def test_close_is_idempotent() -> None:
    queue = InMemoryQueue()
    await queue.close()
    await queue.close()  # must not raise


async def test_delayed_push_does_not_run_immediately() -> None:
    queue = InMemoryQueue()
    log: list[str] = []

    await queue.push(RecordingJob(log=log, value="delayed"), delay=0.2)
    await asyncio.sleep(0.05)

    assert log == []  # not yet -- the delay hasn't elapsed
    await queue.close()


async def test_delayed_push_runs_after_the_delay() -> None:
    queue = InMemoryQueue()
    log: list[str] = []

    await queue.push(RecordingJob(log=log, value="delayed"), delay=0.1)
    await asyncio.sleep(0.25)
    await queue.join()

    assert log == ["delayed"]
    await queue.close()


async def test_join_alone_waits_out_a_delayed_pushs_full_delay() -> None:
    # Regression guard: join() used to only track work already put() onto
    # the underlying asyncio.Queue -- a delayed push doesn't call put()
    # until its wait elapses, so join() returned instantly, before the
    # job had even been enqueued, let alone run. A caller doing
    # `await queue.join(); await queue.close()` as a graceful-shutdown
    # drain (a reasonable reading of join()'s own docstring) would
    # silently cancel and lose any job still waiting on its delay.
    # Deliberately no manual `asyncio.sleep()` before join() here (unlike
    # the sibling test above) -- join() alone must now be sufficient.
    queue = InMemoryQueue()
    log: list[str] = []

    await queue.push(RecordingJob(log=log, value="delayed"), delay=0.1)
    await queue.join()

    assert log == ["delayed"]
    await queue.close()


async def test_close_cancels_pending_delayed_pushes() -> None:
    queue = InMemoryQueue()
    log: list[str] = []

    await queue.push(RecordingJob(log=log, value="never runs"), delay=10)
    await queue.close()
    await asyncio.sleep(0.05)

    assert log == []  # the delayed push was cancelled, not just the worker


# -- SyncQueue ------------------------------------------------------------------------


async def test_sync_queue_runs_immediately() -> None:
    queue = SyncQueue()
    log: list[str] = []

    await queue.push(RecordingJob(log=log, value="immediate"))

    assert log == ["immediate"]  # no join() needed


async def test_sync_queue_propagates_exceptions() -> None:
    queue = SyncQueue()

    with pytest.raises(RuntimeError, match="always fails"):
        await queue.push(AlwaysFailsJob(attempts_log=[]))


async def test_sync_queue_ignores_delay_and_runs_immediately() -> None:
    queue = SyncQueue()
    log: list[str] = []

    await queue.push(RecordingJob(log=log, value="immediate"), delay=10)

    assert log == ["immediate"]


# -- dispatch() + QueueServiceProvider -------------------------------------------------


def _make_app(tmp_path: Path) -> Application:
    app = Application(Config.load(tmp_path))
    app.register(QueueServiceProvider)
    return app


async def test_dispatch_runs_job_in_background(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    log: list[str] = []

    @app.post("/register")
    async def register(request):
        await dispatch(request, RecordingJob(log=log, value="welcome email"))
        return JSONResponse({"ok": True}, status_code=201)

    async with client(app) as http:
        response = await http.post("/register")
        assert response.status_code == 201

    # The job may not have run yet at this point -- that's the point of a queue.
    queue = app.container.make(Queue)
    await queue.join()
    assert log == ["welcome email"]


async def test_dispatch_with_a_delay_defers_the_job(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    log: list[str] = []

    @app.post("/register")
    async def register(request):
        await dispatch(request, RecordingJob(log=log, value="reminder"), delay=0.1)
        return JSONResponse({"ok": True}, status_code=201)

    async with client(app) as http:
        await http.post("/register")

    assert log == []  # not yet -- delay hasn't elapsed

    await asyncio.sleep(0.25)
    queue = app.container.make(Queue)
    await queue.join()
    assert log == ["reminder"]


async def test_sync_driver_runs_dispatched_jobs_immediately(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("QUEUE_DRIVER=sync\n")
    app = _make_app(tmp_path)
    log: list[str] = []

    @app.post("/register")
    async def register(request):
        await dispatch(request, RecordingJob(log=log, value="welcome email"))
        return JSONResponse({"ok": True}, status_code=201)

    async with client(app) as http:
        response = await http.post("/register")

    assert response.status_code == 201
    assert log == ["welcome email"]  # already ran, no join() needed


async def test_queue_is_available_in_the_container(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    assert isinstance(app.container.make(Queue), InMemoryQueue)


# -- Job dependency injection via the container --------------------------------------


class Greeter:
    def greeting(self) -> str:
        return "hello from the container"


@dataclass
class InjectedJob(Job):
    """A job whose handle() declares an extra typed param, resolved from the container."""

    log: list[str]

    async def handle(self, greeter: Greeter) -> None:
        self.log.append(greeter.greeting())


async def test_in_memory_queue_injects_dependencies_into_handle(tmp_path: Path) -> None:
    container = Container()
    container.singleton(Greeter)
    queue = InMemoryQueue(container=container)
    log: list[str] = []

    await queue.push(InjectedJob(log=log))
    await queue.join()

    assert log == ["hello from the container"]
    await queue.close()


async def test_sync_queue_injects_dependencies_into_handle(tmp_path: Path) -> None:
    container = Container()
    container.singleton(Greeter)
    queue = SyncQueue(container=container)
    log: list[str] = []

    await queue.push(InjectedJob(log=log))

    assert log == ["hello from the container"]


async def test_queue_without_container_cannot_resolve_extra_handle_params() -> None:
    queue = SyncQueue()  # no container -- matches the pre-DI default behavior

    with pytest.raises(TypeError):
        await queue.push(InjectedJob(log=[]))

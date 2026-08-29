"""Tests for job chaining (``chain()``) and batching (``dispatch_batch()``)
-- both built on top of the existing ``Queue``/``Job`` primitives, so they
work with any queue driver. Redis-backed batch tracking and an end-to-end
Redis queue run are covered separately, in test_redis_job_batching.py
(skipped there if no Redis server is reachable).

Every job below carries a ``run_id`` rather than a shared mutable list: both
``chain()`` and ``dispatch_batch()`` round-trip a job through
``dataclasses.asdict()`` and reconstruct a fresh instance from the result
(the same requirement ``RedisQueue`` has, so the wrapper can hand a job off
to a *later*, independent dispatch) -- a job field holding a live list
object would be deep-copied in the process, silently disconnecting it from
whatever the test still holds a reference to. A module-level dict keyed by
``run_id`` survives that reconstruction because it's the module's own
state, not the job's.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.queue import (
    BatchProgress,
    BatchTracker,
    InMemoryBatchTracker,
    Job,
    Queue,
    QueueServiceProvider,
    batch_progress,
    chain,
    dispatch,
    dispatch_batch,
)
from zeython.testing import client

# -- fixtures: module-level dataclasses, required so chain()/dispatch_batch() -------
# -- can reconstruct them by class path (importlib.import_module + getattr). --------

_LOGS: dict[str, list[str]] = {}
_ATTEMPT_COUNTS: dict[str, int] = {}


def _new_run_id() -> str:
    return uuid.uuid4().hex


def _log_for(run_id: str) -> list[str]:
    return _LOGS.setdefault(run_id, [])


@dataclass
class RecordingJob(Job):
    run_id: str
    value: str

    async def handle(self) -> None:
        _log_for(self.run_id).append(self.value)


@dataclass
class FailingJob(Job):
    run_id: str
    max_attempts: int = 1

    async def handle(self) -> None:
        _log_for(self.run_id).append("ran")
        raise RuntimeError("boom")


@dataclass
class FailsThenSucceedsJob(Job):
    run_id: str
    fail_times: int
    max_attempts: int = 3

    async def handle(self) -> None:
        _ATTEMPT_COUNTS[self.run_id] = _ATTEMPT_COUNTS.get(self.run_id, 0) + 1
        if _ATTEMPT_COUNTS[self.run_id] <= self.fail_times:
            raise RuntimeError("not yet")
        _log_for(self.run_id).append("succeeded")


class NotADataclass(Job):
    """A Job subclass that isn't a dataclass -- for the rejection tests."""

    async def handle(self) -> None: ...


def _make_app(tmp_path: Path, *, driver: str = "memory") -> Application:
    (tmp_path / ".env").write_text(f"QUEUE_DRIVER={driver}\n")
    app = Application(Config.load(tmp_path))
    app.register(QueueServiceProvider)
    return app


# -- chain() --------------------------------------------------------------------


def test_chain_requires_at_least_one_job() -> None:
    with pytest.raises(ValueError, match="at least one job"):
        chain([])


def test_chain_requires_dataclass_jobs() -> None:
    with pytest.raises(TypeError, match="must be a @dataclass"):
        chain([NotADataclass()])


async def test_chain_runs_links_in_order(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    run_id = _new_run_id()

    @app.post("/run")
    async def run(request):
        await dispatch(
            request,
            chain([RecordingJob(run_id=run_id, value="a"), RecordingJob(run_id=run_id, value="b"), RecordingJob(run_id=run_id, value="c")]),
        )
        return JSONResponse({}, status_code=201)

    async with client(app) as http:
        await http.post("/run")

    queue = app.container.make(Queue)
    await queue.join()
    # Each link dispatches the next only after this one -- there's no
    # in-between state to poll, "await join() then assert full order" is
    # the way to observe strict sequencing here.
    assert _LOGS[run_id] == ["a", "b", "c"]


async def test_chain_stops_after_a_link_exhausts_its_retries(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    run_id = _new_run_id()

    @app.post("/run")
    async def run(request):
        await dispatch(
            request, chain([RecordingJob(run_id=run_id, value="a"), FailingJob(run_id=run_id), RecordingJob(run_id=run_id, value="c")])
        )
        return JSONResponse({}, status_code=201)

    async with client(app) as http:
        await http.post("/run")

    queue = app.container.make(Queue)
    await queue.join()
    # "a" ran, the failing link ran (and logged "ran" before raising), but
    # "c" never does -- the chain stops at the failed link.
    assert _LOGS[run_id] == ["a", "ran"]


async def test_chain_link_retries_up_to_its_own_max_attempts(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    run_id = _new_run_id()

    @app.post("/run")
    async def run(request):
        await dispatch(
            request,
            chain([FailsThenSucceedsJob(run_id=run_id, fail_times=2), RecordingJob(run_id=run_id, value="after")]),
        )
        return JSONResponse({}, status_code=201)

    async with client(app) as http:
        await http.post("/run")

    queue = app.container.make(Queue)
    await queue.join()
    assert _LOGS[run_id] == ["succeeded", "after"]


async def test_chain_works_with_sync_queue(tmp_path: Path) -> None:
    app = _make_app(tmp_path, driver="sync")
    run_id = _new_run_id()

    @app.post("/run")
    async def run(request):
        await dispatch(request, chain([RecordingJob(run_id=run_id, value="a"), RecordingJob(run_id=run_id, value="b")]))
        return JSONResponse({}, status_code=201)

    async with client(app) as http:
        response = await http.post("/run")

    assert response.status_code == 201
    assert _LOGS[run_id] == ["a", "b"]  # already ran, synchronously, no join() needed


# -- dispatch_batch() / batch_progress() -----------------------------------------


def test_batch_progress_finished_and_succeeded() -> None:
    progress = BatchProgress(total=5, pending=0, failed=2)
    assert progress.finished is True
    assert progress.succeeded == 3

    still_running = BatchProgress(total=5, pending=2, failed=1)
    assert still_running.finished is False


async def test_dispatch_batch_accepts_a_caller_supplied_batch_id(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    run_id = _new_run_id()
    chosen_id = _new_run_id()

    @app.post("/run")
    async def run(request):
        returned_id = await dispatch_batch(
            request, [RecordingJob(run_id=run_id, value="a")], batch_id=chosen_id
        )
        assert returned_id == chosen_id
        return JSONResponse({}, status_code=201)

    async with client(app) as http:
        await http.post("/run")

    queue = app.container.make(Queue)
    await queue.join()
    progress = await _batch_progress_direct(app, chosen_id)
    assert progress == BatchProgress(total=1, pending=0, failed=0)


async def test_dispatch_batch_requires_at_least_one_job(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    @app.post("/run")
    async def run(request):
        await dispatch_batch(request, [])
        return JSONResponse({}, status_code=201)

    async with client(app) as http:
        with pytest.raises(ValueError, match="at least one job"):
            await http.post("/run")


async def test_dispatch_batch_runs_every_job(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    run_id = _new_run_id()
    batch_ids: list[str] = []

    @app.post("/run")
    async def run(request):
        batch_id = await dispatch_batch(
            request,
            [RecordingJob(run_id=run_id, value="a"), RecordingJob(run_id=run_id, value="b"), RecordingJob(run_id=run_id, value="c")],
        )
        batch_ids.append(batch_id)
        return JSONResponse({}, status_code=201)

    async with client(app) as http:
        await http.post("/run")

    queue = app.container.make(Queue)
    await queue.join()
    assert sorted(_LOGS[run_id]) == ["a", "b", "c"]

    progress = await _batch_progress_direct(app, batch_ids[0])
    assert progress == BatchProgress(total=3, pending=0, failed=0)


async def test_dispatch_batch_counts_failed_jobs_without_blocking_the_others(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    run_id = _new_run_id()
    batch_ids: list[str] = []

    @app.post("/run")
    async def run(request):
        batch_id = await dispatch_batch(
            request, [RecordingJob(run_id=run_id, value="a"), FailingJob(run_id=run_id), RecordingJob(run_id=run_id, value="c")]
        )
        batch_ids.append(batch_id)
        return JSONResponse({}, status_code=201)

    async with client(app) as http:
        await http.post("/run")

    queue = app.container.make(Queue)
    await queue.join()
    log = _LOGS[run_id]
    assert sorted(x for x in log if x != "ran") == ["a", "c"]
    assert log.count("ran") == 1

    progress = await _batch_progress_direct(app, batch_ids[0])
    assert progress == BatchProgress(total=3, pending=0, failed=1)
    assert progress.succeeded == 2


async def test_dispatch_batch_fires_then_exactly_once_when_finished(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    run_id = _new_run_id()

    @app.post("/run")
    async def run(request):
        await dispatch_batch(
            request,
            [RecordingJob(run_id=run_id, value="a"), RecordingJob(run_id=run_id, value="b")],
            then=RecordingJob(run_id=run_id, value="then"),
        )
        return JSONResponse({}, status_code=201)

    async with client(app) as http:
        await http.post("/run")

    queue = app.container.make(Queue)
    await queue.join()
    log = _LOGS[run_id]
    assert log.count("then") == 1
    assert log[-1] == "then"  # then only fires once both a and b have already run


async def test_dispatch_batch_fires_then_even_if_a_job_fails(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    run_id = _new_run_id()

    @app.post("/run")
    async def run(request):
        await dispatch_batch(request, [FailingJob(run_id=run_id)], then=RecordingJob(run_id=run_id, value="then"))
        return JSONResponse({}, status_code=201)

    async with client(app) as http:
        await http.post("/run")

    queue = app.container.make(Queue)
    await queue.join()
    assert _LOGS[run_id] == ["ran", "then"]


async def test_batch_progress_returns_none_for_an_unknown_batch_id(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    @app.get("/progress/{batch_id}")
    async def progress(request):
        result = await batch_progress(request, request.path_params["batch_id"])
        return JSONResponse({"progress": None if result is None else result.__dict__})

    async with client(app) as http:
        response = await http.get("/progress/does-not-exist")

    assert response.json() == {"progress": None}


async def test_dispatch_batch_works_with_sync_queue(tmp_path: Path) -> None:
    app = _make_app(tmp_path, driver="sync")
    run_id = _new_run_id()
    batch_ids: list[str] = []

    @app.post("/run")
    async def run(request):
        batch_id = await dispatch_batch(request, [RecordingJob(run_id=run_id, value="a"), RecordingJob(run_id=run_id, value="b")])
        batch_ids.append(batch_id)
        return JSONResponse({}, status_code=201)

    async with client(app) as http:
        await http.post("/run")

    assert sorted(_LOGS[run_id]) == ["a", "b"]  # already ran, synchronously
    progress = await _batch_progress_direct(app, batch_ids[0])
    assert progress == BatchProgress(total=2, pending=0, failed=0)


async def _batch_progress_direct(app: Application, batch_id: str) -> BatchProgress | None:
    tracker: BatchTracker = app.container.make(BatchTracker)
    return await tracker.progress(batch_id)


def test_queue_service_provider_binds_in_memory_batch_tracker_by_default(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    assert isinstance(app.container.make(BatchTracker), InMemoryBatchTracker)


# -- InMemoryBatchTracker (unit-level) --------------------------------------------


async def test_in_memory_batch_tracker_tracks_progress_across_completions() -> None:
    tracker = InMemoryBatchTracker()
    await tracker.create("b1", total=3)

    first = await tracker.record_completion("b1", failed=False)
    assert first == BatchProgress(total=3, pending=2, failed=0)

    second = await tracker.record_completion("b1", failed=True)
    assert second == BatchProgress(total=3, pending=1, failed=1)

    third = await tracker.record_completion("b1", failed=False)
    assert third == BatchProgress(total=3, pending=0, failed=1)
    assert third.finished is True


async def test_in_memory_batch_tracker_stores_and_returns_then_spec() -> None:
    tracker = InMemoryBatchTracker()
    spec = {"job_class": "tests.test_job_batching.RecordingJob", "payload": {}, "max_attempts": 1}
    await tracker.create("b1", total=1, then=spec)
    assert await tracker.get_then("b1") == spec


async def test_in_memory_batch_tracker_progress_is_none_for_unknown_batch() -> None:
    tracker = InMemoryBatchTracker()
    assert await tracker.progress("nope") is None
    assert await tracker.get_then("nope") is None

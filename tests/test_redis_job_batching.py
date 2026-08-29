"""Tests for RedisBatchTracker and an end-to-end dispatch_batch() run
against a real RedisQueue -- skipped if the `redis` extra isn't installed,
or if no Redis server is reachable at TEST_REDIS_URL (see
test_redis_queue.py for the same convention).

RecordingJob observes its own execution through Redis itself (pushing onto
a list key), the same way test_redis_queue.py's own jobs do -- a job field
holding a live Python list would be deep-copied by dataclasses.asdict() on
its way through the queue, and separately, run_worker() below runs in this
same test process purely for convenience; a real deployment would run it
in another process entirely, which couldn't see this process's memory
either way.
"""

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("redis")

from redis.asyncio import Redis  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

from zeython.application import Application  # noqa: E402
from zeython.config import Config  # noqa: E402
from zeython.queue import (  # noqa: E402
    BatchProgress,
    BatchTracker,
    Job,
    Queue,
    QueueServiceProvider,
    RedisBatchTracker,
    RedisQueue,
    dispatch_batch,
)
from zeython.testing import client  # noqa: E402

REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")


@pytest.fixture(autouse=True)
async def _require_redis() -> None:
    redis_client = Redis.from_url(REDIS_URL)
    try:
        await redis_client.ping()
    except Exception:
        pytest.skip(f"No Redis server reachable at {REDIS_URL}")
    finally:
        await redis_client.aclose()


@dataclass
class RecordingJob(Job):
    marker_key: str
    value: str

    async def handle(self) -> None:
        redis_client = Redis.from_url(REDIS_URL)
        try:
            await redis_client.rpush(self.marker_key, self.value)
        finally:
            await redis_client.aclose()


def _prefix() -> str:
    return f"zeython:test:batch:{os.getpid()}:"


async def test_redis_batch_tracker_tracks_progress_across_completions() -> None:
    tracker = RedisBatchTracker(REDIS_URL, prefix=_prefix())
    try:
        await tracker.create("b1", total=2)
        first = await tracker.record_completion("b1", failed=False)
        assert first == BatchProgress(total=2, pending=1, failed=0)
        second = await tracker.record_completion("b1", failed=True)
        assert second == BatchProgress(total=2, pending=0, failed=1)
        assert second.finished is True
    finally:
        await tracker.close()


async def test_redis_batch_tracker_stores_and_returns_then_spec() -> None:
    tracker = RedisBatchTracker(REDIS_URL, prefix=_prefix())
    try:
        spec: dict[str, Any] = {
            "job_class": "tests.test_redis_job_batching.RecordingJob",
            "payload": {"marker_key": "some-key", "value": "x"},
            "max_attempts": 1,
        }
        await tracker.create("b1", total=1, then=spec)
        assert await tracker.get_then("b1") == spec
    finally:
        await tracker.close()


async def test_redis_batch_tracker_progress_is_none_for_unknown_batch() -> None:
    tracker = RedisBatchTracker(REDIS_URL, prefix=_prefix())
    try:
        assert await tracker.progress("nope") is None
        assert await tracker.get_then("nope") is None
    finally:
        await tracker.close()


async def test_dispatch_batch_end_to_end_with_redis_queue(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(f"QUEUE_DRIVER=redis\nREDIS_URL={REDIS_URL}\nQUEUE_NAME=batching-e2e-{os.getpid()}\n")
    app = Application(Config.load(tmp_path))
    app.register(QueueServiceProvider)
    marker_key = f"zeython:test:batching-e2e-marker:{os.getpid()}"
    batch_ids: list[str] = []

    @app.post("/run")
    async def run(request):
        batch_id = await dispatch_batch(
            request,
            [RecordingJob(marker_key=marker_key, value="a"), RecordingJob(marker_key=marker_key, value="b")],
            then=RecordingJob(marker_key=marker_key, value="then"),
        )
        batch_ids.append(batch_id)
        return JSONResponse({}, status_code=201)

    redis_client = Redis.from_url(REDIS_URL)
    try:
        await redis_client.delete(marker_key)

        async with client(app) as http:
            await http.post("/run")

        queue: RedisQueue = app.container.make(Queue)
        shutdown = asyncio.Event()
        worker = asyncio.create_task(queue.run_worker(poll_interval=0.1, shutdown=shutdown))
        try:
            for _ in range(50):
                tracker: RedisBatchTracker = app.container.make(BatchTracker)
                progress = await tracker.progress(batch_ids[0])
                if progress is not None and progress.finished:
                    break
                await asyncio.sleep(0.1)
        finally:
            shutdown.set()
            worker.cancel()

        recorded = [value.decode() for value in await redis_client.lrange(marker_key, 0, -1)]
    finally:
        await redis_client.delete(marker_key)
        await redis_client.aclose()

    assert sorted(x for x in recorded if x != "then") == ["a", "b"]
    assert recorded[-1] == "then"

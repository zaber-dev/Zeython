"""Tests for RedisQueue -- skipped if the `redis` extra isn't installed, or
if no Redis server is reachable at TEST_REDIS_URL (see test_redis_backends.py
for the same convention).

RedisQueue round-trips every job through JSON (dataclasses.asdict()) so it
can survive a process restart -- unlike InMemoryQueue's tests, a job's
*Python object identity* is never preserved across a push/process cycle,
so these tests observe side effects through Redis itself (a job's handle()
writes a marker key), the same way a real, separate worker process would
have to signal completion back to anything watching.
"""

import asyncio
import contextlib
import os
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio

pytest.importorskip("redis")

from redis.asyncio import Redis  # noqa: E402

from zeython.application import Application  # noqa: E402
from zeython.config import Config  # noqa: E402
from zeython.container import Container  # noqa: E402
from zeython.queue import Job, Queue, QueueServiceProvider, RedisQueue  # noqa: E402

REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")


@pytest_asyncio.fixture(autouse=True)
async def _require_redis() -> None:
    from redis.asyncio import Redis

    client = Redis.from_url(REDIS_URL)
    try:
        await client.ping()
    except Exception:
        pytest.skip(f"No Redis server reachable at {REDIS_URL}")
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def redis_client():
    from redis.asyncio import Redis

    instance = Redis.from_url(REDIS_URL)
    yield instance
    async for key in instance.scan_iter(match="zeython-test:queue:*"):
        await instance.delete(key)
    await instance.aclose()


@pytest_asyncio.fixture
async def queue(redis_client):
    container = Container()
    container.instance(Redis, redis_client)
    instance = RedisQueue(REDIS_URL, container=container, queue_name="test", prefix="zeython-test:queue:")
    yield instance
    await instance.close()


async def _run_worker_until(queue: RedisQueue, condition, *, timeout: float = 3.0) -> None:
    """Runs the worker in the background until `condition()` is true, or fails the test."""
    task = asyncio.create_task(queue.run_worker(poll_interval=0.05))
    try:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if await condition():
                return
            await asyncio.sleep(0.02)
        pytest.fail("condition was not met before the timeout")
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@dataclass
class RedisRecordingJob(Job):
    """Writes a marker into Redis when it runs -- the durable-queue
    equivalent of test_queue.py's in-memory RecordingJob."""

    marker_key: str

    async def handle(self, redis_client: Redis) -> None:
        await redis_client.set(self.marker_key, "done")


@dataclass
class RedisFlakyJob(Job):
    """Fails `fail_times` times, tracked via a Redis counter (not instance
    state -- a fresh instance is reconstructed from JSON on every retry)."""

    counter_key: str
    marker_key: str
    fail_times: int
    max_attempts: int = 5

    async def handle(self, redis_client: Redis) -> None:
        calls = await redis_client.incr(self.counter_key)
        if calls <= self.fail_times:
            raise RuntimeError("not yet")
        await redis_client.set(self.marker_key, "done")


@dataclass
class RedisAlwaysFailsJob(Job):
    max_attempts: int = 1

    async def handle(self) -> None:
        raise RuntimeError("this job always fails")


class NotADataclassJob(Job):
    async def handle(self) -> None:
        pass


# -- push() ---------------------------------------------------------------------------


async def test_push_without_delay_enqueues_to_the_pending_list(queue: RedisQueue) -> None:
    await queue.push(RedisRecordingJob(marker_key="m"))

    assert await queue._client.llen(queue._pending_key) == 1
    assert await queue._client.zcard(queue._delayed_key) == 0


async def test_push_with_a_delay_enqueues_to_the_delayed_set_instead(queue: RedisQueue) -> None:
    await queue.push(RedisRecordingJob(marker_key="m"), delay=100)

    assert await queue._client.llen(queue._pending_key) == 0
    assert await queue._client.zcard(queue._delayed_key) == 1


async def test_pushed_payload_round_trips_the_job_class_and_fields(queue: RedisQueue) -> None:
    import json

    await queue.push(RedisRecordingJob(marker_key="my-marker"))

    raw = await queue._client.lpop(queue._pending_key)
    data = json.loads(raw)
    assert data["job_class"].endswith("RedisRecordingJob")
    assert data["payload"] == {"marker_key": "my-marker"}
    assert data["attempts"] == 0
    assert data["max_attempts"] == 1


async def test_a_non_dataclass_job_raises_type_error_on_push(queue: RedisQueue) -> None:
    with pytest.raises(TypeError, match="dataclass"):
        await queue.push(NotADataclassJob())


# -- run_worker(): success -------------------------------------------------------------


async def test_worker_processes_a_pushed_job(queue: RedisQueue, redis_client) -> None:
    await queue.push(RedisRecordingJob(marker_key="worker-marker"))

    await _run_worker_until(queue, lambda: redis_client.exists("worker-marker"))

    assert await redis_client.get("worker-marker") == b"done"


async def test_worker_reclaims_a_delayed_job_once_its_wait_elapses(queue: RedisQueue, redis_client) -> None:
    await queue.push(RedisRecordingJob(marker_key="delayed-marker"), delay=0.2)

    await _run_worker_until(queue, lambda: redis_client.exists("delayed-marker"), timeout=3.0)

    assert await redis_client.get("delayed-marker") == b"done"


# -- run_worker(): retries with backoff -------------------------------------------------


async def test_worker_retries_a_failing_job_until_it_succeeds(queue: RedisQueue, redis_client) -> None:
    # Backoff is 2s after the first failure, 4s after the second, etc. --
    # fail_times=1 keeps this test to one ~2s wait instead of stacking them.
    await queue.push(
        RedisFlakyJob(counter_key="flaky-counter", marker_key="flaky-marker", fail_times=1, max_attempts=5)
    )

    await _run_worker_until(queue, lambda: redis_client.exists("flaky-marker"), timeout=5.0)

    assert await redis_client.get("flaky-marker") == b"done"
    assert int(await redis_client.get("flaky-counter")) == 2  # failed once, then succeeded


# -- run_worker(): exhausted retries -> failed-jobs list --------------------------------


async def test_worker_moves_an_exhausted_job_to_the_failed_jobs_list(queue: RedisQueue) -> None:
    await queue.push(RedisAlwaysFailsJob(max_attempts=1))

    await _run_worker_until(queue, lambda: queue._client.llen(queue._failed_key))

    failed = await queue.failed_jobs()
    assert len(failed) == 1
    assert failed[0]["job_class"].endswith("RedisAlwaysFailsJob")
    assert failed[0]["attempts"] == 1
    assert "this job always fails" in failed[0]["error"]
    assert "failed_at" in failed[0]


async def test_failed_jobs_is_empty_by_default(queue: RedisQueue) -> None:
    assert await queue.failed_jobs() == []


# -- QueueServiceProvider ---------------------------------------------------------------


async def test_queue_driver_redis_binds_a_redis_queue(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(f"QUEUE_DRIVER=redis\nREDIS_URL={REDIS_URL}\nQUEUE_NAME=custom\n")
    app = Application(Config.load(tmp_path))
    app.register(QueueServiceProvider)

    bound = app.container.make(Queue)
    try:
        assert isinstance(bound, RedisQueue)
        assert bound.queue_name == "custom"
    finally:
        await bound.close()


async def test_redis_queue_without_the_redis_package_raises_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def blocking_import(name, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if name == "redis.asyncio":
            raise ImportError("no redis for you")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocking_import)

    with pytest.raises(ImportError, match=r"pip install zeython\[redis\]"):
        RedisQueue(REDIS_URL)

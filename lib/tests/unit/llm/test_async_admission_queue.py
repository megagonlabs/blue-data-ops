from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, Literal

import pytest

from blue_data_ops import _execution_scope as scope
from blue_data_ops.llm import LLMClient, LLMError
from blue_data_ops.llm import client as module
from blue_data_ops.llm.client import (
    _AdmissionControls,  # pyright: ignore[reportPrivateUsage]
)
from tests.unit.llm.test_temperature_fallback import install, prepared


async def until(predicate: Callable[[], bool]) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), 0.3)


async def permits(semaphore: asyncio.Semaphore, count: int) -> None:
    for _ in range(count):
        await asyncio.wait_for(semaphore.acquire(), 0.3)
    assert semaphore.locked(), "semaphore gained an extra permit"
    for _ in range(count):
        semaphore.release()


class TrackedSemaphore(asyncio.Semaphore):
    def __init__(self) -> None:
        super().__init__(0)
        self.pending = 0
        self.attempts = 0
        self.on_grant: Callable[[], None] | None = None

    async def acquire(self) -> Literal[True]:
        self.attempts += 1
        self.pending += 1
        try:
            granted = await super().acquire()
        finally:
            self.pending -= 1
        if self.on_grant is not None:
            self.on_grant()
        return granted


def queued_client(
    monkeypatch: pytest.MonkeyPatch, rate: float | None = None
) -> tuple[LLMClient, TrackedSemaphore, list[dict[str, Any]]]:
    calls = install(monkeypatch, [])
    client = LLMClient("test", prepared({"llm.rate_limit": rate, "llm.max_parallel": 1}))
    semaphore = TrackedSemaphore()

    def resolve(controls: _AdmissionControls) -> asyncio.Semaphore:
        return semaphore

    monkeypatch.setattr(client, "_resolve_semaphore", resolve)
    return client, semaphore, calls


@pytest.mark.parametrize("rate", [0, None])
@pytest.mark.parametrize("parallel", [None, 1])
def test_unlimited_queue_outlives_admission_budget(
    rate: float | None, parallel: int | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    calls = install(monkeypatch, [])
    properties: dict[str, Any] = {"llm.rate_limit": rate}
    if parallel is not None:
        properties["llm.max_parallel"] = parallel
    client = LLMClient("test", prepared(properties))
    limit = parallel or 8

    async def exercise() -> None:
        semaphore = client._resolve_semaphore(  # pyright: ignore[reportPrivateUsage]
            _AdmissionControls(max_parallel=limit)
        )
        for _ in range(limit):
            await semaphore.acquire()
        waiter = asyncio.create_task(client.aexecute_api_call({}))
        try:
            await asyncio.sleep(0.02)
            clock.now = module.MAX_ADMISSION_WAIT + 1
            await asyncio.sleep(scope.POLL_INTERVAL * 1.5)
            assert not waiter.done(), "unlimited backpressure used the rate admission budget"
            assert not calls
            semaphore.release()
            assert await asyncio.wait_for(waiter, 0.3) == "ok"
            assert len(calls) == 1
            for _ in range(limit - 1):
                semaphore.release()
            await permits(semaphore, limit)
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)

    asyncio.run(exercise())


@pytest.mark.parametrize("rate", [None, 1000])
def test_waiters_keep_fifo_position_across_polls(
    rate: float | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, semaphore, calls = queued_client(monkeypatch, rate)

    async def exercise() -> None:
        first = asyncio.create_task(client.aexecute_api_call("first"))
        second: asyncio.Task[Any] | None = None
        try:
            await until(lambda: semaphore.pending == 1)
            await asyncio.sleep(scope.POLL_INTERVAL * 0.6)
            second = asyncio.create_task(client.aexecute_api_call("second"))
            await until(lambda: semaphore.pending == 2)
            await asyncio.sleep(scope.POLL_INTERVAL * 1.6)
            assert semaphore.attempts == 2, "polling cancelled and requeued an acquire"
            assert not calls
            semaphore.release()
            assert await asyncio.wait_for(asyncio.gather(first, second), 0.3) == ["ok", "ok"]
            assert [call["messages"][0]["content"] for call in calls] == [
                "Say first",
                "Say second",
            ]
            assert semaphore.pending == 0
            await permits(semaphore, 1)
        finally:
            tasks = [first] if second is None else [first, second]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(exercise())


@pytest.mark.parametrize("rate", [0, None, 1])
@pytest.mark.parametrize("stop", ["deadline", "scope-stop", "task-cancel"])
def test_scope_or_cancellation_retires_wait_without_blocking_loop(
    rate: float | None, stop: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, semaphore, calls = queued_client(monkeypatch, rate)

    async def exercise() -> None:
        task_scope = scope.create(0.04 if stop == "deadline" else 1)
        with scope.activate(task_scope):
            waiter = asyncio.create_task(client.aexecute_api_call({}))
        beats = 0

        async def heartbeat() -> None:
            nonlocal beats
            while not waiter.done():
                beats += 1
                await asyncio.sleep(0.002)

        pulse = asyncio.create_task(heartbeat())
        started = time.monotonic()
        try:
            await until(lambda: semaphore.pending == 1)
            await asyncio.sleep(0.01)
            assert not calls
            if stop == "scope-stop":
                task_scope.stop.set()
            elif stop == "task-cancel":
                waiter.cancel()
            expected = asyncio.CancelledError if stop == "task-cancel" else scope.ScopeExpired
            with pytest.raises(expected):
                await asyncio.wait_for(waiter, 0.25)
            assert time.monotonic() - started < 0.3
            assert beats >= 2
            assert semaphore.pending == 0
            semaphore.release()
            await asyncio.sleep(scope.POLL_INTERVAL * 1.2)
            assert not calls, "retired waiter reached the provider after release"
            assert await asyncio.wait_for(client.aexecute_api_call({}), 0.3) == "ok"
            assert len(calls) == 1
            await permits(semaphore, 1)
        finally:
            waiter.cancel()
            pulse.cancel()
            await asyncio.gather(waiter, pulse, return_exceptions=True)

    asyncio.run(exercise())


@pytest.mark.parametrize("stop", ["task-cancel", "scope-stop", "deadline"])
@pytest.mark.parametrize("granted", [False, True])
def test_grant_and_retirement_race_returns_exactly_one_permit(
    stop: str, granted: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, semaphore, calls = queued_client(monkeypatch)

    async def exercise() -> None:
        task_scope = scope.create(1)
        with scope.activate(task_scope):
            waiter = asyncio.create_task(client.aexecute_api_call({}))

        def retire() -> None:
            if stop == "task-cancel":
                waiter.cancel()
            elif stop == "scope-stop":
                task_scope.stop.set()
            else:
                task_scope.deadline = time.monotonic() - 1

        try:
            await until(lambda: semaphore.pending == 1)
            if granted:
                semaphore.on_grant = retire
            semaphore.release()
            if not granted:
                retire()
            expected = asyncio.CancelledError if stop == "task-cancel" else scope.ScopeExpired
            with pytest.raises(expected):
                await asyncio.wait_for(waiter, 0.3)
            semaphore.on_grant = None
            assert semaphore.pending == 0
            assert not calls
            await asyncio.sleep(scope.POLL_INTERVAL * 1.2)
            assert not calls
            await permits(semaphore, 1)
            assert await asyncio.wait_for(client.aexecute_api_call({}), 0.3) == "ok"
            assert len(calls) == 1
            await permits(semaphore, 1)
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)

    asyncio.run(exercise())


def test_rated_semaphore_wait_is_still_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    client, semaphore, calls = queued_client(monkeypatch, 1)

    async def exercise() -> None:
        waiter = asyncio.create_task(client.aexecute_api_call({}))
        try:
            await until(lambda: semaphore.pending == 1)
            clock.now = module.MAX_ADMISSION_WAIT + 1
            with pytest.raises(LLMError) as error:
                await asyncio.wait_for(waiter, 0.3)
            assert error.value.code == "local_rate_limit" and error.value.retryable
            assert semaphore.pending == 0
            assert not calls
            semaphore.release()
            await asyncio.sleep(scope.POLL_INTERVAL * 1.2)
            assert not calls
            await permits(semaphore, 1)
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)

    asyncio.run(exercise())

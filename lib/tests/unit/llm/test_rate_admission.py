from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import litellm
import pytest

from blue_data_ops import _execution_scope as scope
from blue_data_ops.llm import LLMClient, LLMError
from blue_data_ops.llm import client as module
from blue_data_ops.llm.client import (
    _AdmissionControls,  # pyright: ignore[reportPrivateUsage]
    validate_llm_caller_controls,
)
from tests.unit.llm.test_client import OP_PROPS
from tests.unit.llm.test_temperature_fallback import install, invoke, prepared, rejection


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    state = SimpleNamespace(now=0.0, jitter=0.0, waits=[])

    def advance(seconds: float) -> None:
        state.waits.append(seconds)
        state.now += seconds + state.jitter

    async def aadvance(seconds: float) -> None:
        advance(seconds)
        await asyncio.sleep(0)

    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: state.now))
    monkeypatch.setattr(scope, "wait_sync", advance)
    monkeypatch.setattr(scope, "wait_async", aadvance)
    litellm.calls.clear()
    litellm.fail_next.clear()
    return state


@pytest.mark.parametrize(
    "key,values,code",
    [
        (
            "llm.rate_limit",
            [
                -1,
                True,
                False,
                "nan",
                float("nan"),
                float("inf"),
                Decimal("NaN"),
                object(),
                0.09999,
                1e-9,
                5e-324,
                "1e-9999",
                Decimal("1e-9999"),
                10**400,
            ],
            "bad_rate_limit",
        ),
        (
            "llm.max_parallel",
            [
                0,
                -1,
                True,
                False,
                "2.5",
                2.5,
                None,
                object(),
                float("inf"),
                10**400,
                Decimal("2.00000000000000001"),
            ],
            "bad_max_parallel",
        ),
    ],
)
def test_bad_controls_before_cache_or_provider(
    key: str, values: list[Any], code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("invalid controls reached request/cache/provider work")

    monkeypatch.setattr(module, "build_message", forbidden)
    for value in values:
        controls = {key: value}
        with pytest.raises(LLMError) as error:
            validate_llm_caller_controls(controls)
        assert error.value.code == code and not error.value.retryable
        client = LLMClient("test", OP_PROPS)
        with pytest.raises(LLMError):
            client.execute_api_call({}, controls)
        with pytest.raises(LLMError):
            asyncio.run(client.aexecute_api_call({}, controls))


@pytest.mark.parametrize("rate", [0, 0.0, "0", None, 1, 2, "5", "0.1", Decimal("0.1")])
@pytest.mark.parametrize("mode", ["sync", "async", "observed"])
@pytest.mark.parametrize("host", [False, True])
def test_first_attempt_immediate_then_paced(
    rate: Any, mode: str, host: bool, clock: SimpleNamespace, completion: list[dict[str, Any]]
) -> None:
    controls = {"llm.rate_limit": rate}
    props = prepared(controls)
    client = LLMClient("test", props if host else prepared())
    caller = props if not host else client.properties
    invoke(client, caller, mode)
    assert clock.now == 0
    invoke(client, caller, mode)
    assert clock.now == (0 if not rate or rate == "0" else 1 / float(rate))
    assert len(completion) == 2


@pytest.fixture(autouse=True)
def completion(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    return install(monkeypatch, [])


@pytest.mark.parametrize("jitter", [0, 0.001, 0.02])
@pytest.mark.parametrize("mode", ["sync", "async", "observed"])
def test_minimum_rate_boundary_uses_required_wait(
    jitter: float, mode: str, clock: SimpleNamespace
) -> None:
    assert module.MIN_RATE == 0.1
    assert module.MAX_ADMISSION_WAIT == 1 / module.MIN_RATE
    clock.jitter = jitter
    props = prepared({"llm.rate_limit": Decimal("0.1")})
    client = LLMClient("test", props)
    invoke(client, props, mode)
    invoke(client, props, mode)
    assert clock.waits == [10]
    assert client._last_call_at == 10 + jitter  # pyright: ignore[reportPrivateUsage]


def test_lock_and_rate_share_one_budget(
    clock: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = LLMClient("test")

    class BusyLock:
        def acquire(self, *, blocking: bool) -> bool:
            if clock.now < 3:
                return False
            client._last_call_at = 3  # pyright: ignore[reportPrivateUsage]
            return True

        def release(self) -> None:
            pass

    monkeypatch.setattr(client, "_rate_lock", BusyLock())
    with pytest.raises(LLMError) as error:
        client._apply_rate_limit(_AdmissionControls(0.1))  # pyright: ignore[reportPrivateUsage]
    assert error.value.code == "local_rate_limit" and error.value.retryable
    assert 3 <= clock.now < 3.1


def test_semaphore_lock_and_rate_share_budget(
    clock: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = LLMClient("test", prepared({"llm.rate_limit": 0.1}))
    sem = asyncio.Semaphore(1)

    async def acquire(semaphore: asyncio.Semaphore, budget: Any) -> None:
        await semaphore.acquire()
        clock.now += 4

    class BusyLock:
        def acquire(self, *, blocking: bool) -> bool:
            if clock.now < 7:
                return False
            client._last_call_at = 7  # pyright: ignore[reportPrivateUsage]
            return True

        def release(self) -> None:
            pass

    def resolve(controls: _AdmissionControls) -> asyncio.Semaphore:
        return sem

    monkeypatch.setattr(client, "_resolve_semaphore", resolve)
    monkeypatch.setattr(client, "_acquire_semaphore", acquire)
    monkeypatch.setattr(client, "_rate_lock", BusyLock())
    with pytest.raises(LLMError) as error:
        asyncio.run(client.aexecute_api_call({}))
    assert error.value.code == "local_rate_limit"
    assert 7 <= clock.now < 7.1
    assert not sem.locked()


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_contention_finishes_with_success_or_retryable_refusal(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "MAX_ADMISSION_WAIT", 0.15)
    client = LLMClient("test", prepared({"llm.rate_limit": 20, "llm.max_parallel": 8}))
    started = time.monotonic()

    def call(_: int) -> str:
        try:
            client.execute_api_call({})
            return "ok"
        except LLMError as error:
            assert error.retryable
            return error.code or ""

    async def acall() -> str:
        try:
            await client.aexecute_api_call({})
            return "ok"
        except LLMError as error:
            assert error.retryable
            return error.code or ""

    async def burst() -> list[str]:
        return await asyncio.gather(*(acall() for _ in range(12)))

    if mode == "sync":
        gate = threading.Barrier(12)

        def together(i: int) -> str:
            gate.wait(timeout=2)
            return call(i)

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(together, range(12)))
    else:
        results = asyncio.run(burst())
    assert 1 <= results.count("ok") < 12
    assert set(results) == {"ok", "local_rate_limit"}
    assert time.monotonic() - started < 0.6


def test_normalized_parallel_keys_and_successive_event_loops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def provider(**kwargs: Any) -> Any:
        await asyncio.sleep(0.01)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(litellm, "acompletion", provider)
    client = LLMClient("test", prepared())

    async def burst() -> asyncio.Semaphore:
        results = await asyncio.gather(
            *(
                client.aexecute_api_call({}, {"llm.max_parallel": limit})
                for limit in ["2", 2.0, 2, Decimal("2"), "2"]
            )
        )
        assert results == ["ok"] * 5
        return client._resolve_semaphore(_AdmissionControls(max_parallel=2))  # pyright: ignore[reportPrivateUsage]

    first = asyncio.run(burst())
    second = asyncio.run(burst())
    assert first is not second


def test_cancelled_waiter_preserves_semaphore_continuity(monkeypatch: pytest.MonkeyPatch) -> None:
    client = LLMClient("test", prepared({"llm.max_parallel": "1"}))

    async def exercise() -> None:
        entered, release = asyncio.Event(), asyncio.Event()

        async def provider(**kwargs: Any) -> Any:
            entered.set()
            await release.wait()
            return {"choices": [{"message": {"content": "ok"}}]}

        monkeypatch.setattr(litellm, "acompletion", provider)
        first = asyncio.create_task(client.aexecute_api_call({}))
        await entered.wait()
        waiter = asyncio.create_task(client.aexecute_api_call({}))
        await asyncio.sleep(0.01)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        release.set()
        await first
        assert await asyncio.wait_for(client.aexecute_api_call({}), 0.3) == "ok"

    asyncio.run(exercise())


@pytest.mark.parametrize("mode", ["sync", "async", "observed"])
@pytest.mark.parametrize("fallback", [False, True])
def test_retry_and_fallback_each_need_a_new_paced_slot(
    mode: str, fallback: bool, clock: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = install(monkeypatch, [rejection("structured")] if fallback else [RuntimeError("local")])
    props = prepared({"llm.rate_limit": 1})
    client = LLMClient("test", props)
    observation = invoke(client, props, mode)
    assert len(calls) == 2
    assert client._last_call_at == 1  # pyright: ignore[reportPrivateUsage]
    if observation:
        assert observation.provider_attempts == 2
    assert all(
        not {"controls", "rate_limit", "max_parallel", "cache"}.intersection(k) for k in calls
    )


@pytest.mark.parametrize("mode", ["sync", "async", "observed"])
def test_fallback_alias_cache_uses_no_slot_or_permit(
    mode: str, clock: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = install(monkeypatch, [rejection("structured")])
    props = prepared({"llm.rate_limit": 1, "llm.cache": True, "llm.cache_dir": str(tmp_path)})
    client = LLMClient("test", props)
    invoke(client, props, mode)
    assert len(calls) == 2
    before = client._last_call_at  # pyright: ignore[reportPrivateUsage]

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("cache hit requested admission")

    monkeypatch.setattr(client, "_resolve_semaphore", forbidden)
    monkeypatch.setattr(client, "_apply_rate_limit", forbidden)
    observation = invoke(client, props, mode)
    assert len(calls) == 2 and client.last_usage and client.last_usage.cache_hit
    assert client._last_call_at == before  # pyright: ignore[reportPrivateUsage]
    if observation:
        assert observation.provider_attempts == 0
    for cache in client._caches.values():  # pyright: ignore[reportPrivateUsage]
        cache.close()


def test_normalizes_effective_controls_once_per_client_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    normalizer = module._normalize_admission_controls  # pyright: ignore[reportPrivateUsage]
    calls = 0

    def normalize(properties: dict[str, Any]) -> _AdmissionControls:
        nonlocal calls
        calls += 1
        return normalizer(properties)

    props = prepared({"llm.rate_limit": 1000})
    client = LLMClient("test", props)
    monkeypatch.setattr(module, "_normalize_admission_controls", normalize)
    for mode in ["sync", "async", "observed"]:
        install(monkeypatch, [RuntimeError("local")])
        invoke(client, props, mode)
    assert calls == 3


def test_minimum_rate_fanout_finishes_within_one_budget() -> None:
    client = LLMClient("test", prepared({"llm.rate_limit": 0.1, "llm.max_parallel": 8}))

    async def exercise() -> list[str]:
        async def call() -> str:
            try:
                await client.aexecute_api_call({})
                return "ok"
            except LLMError as error:
                assert error.retryable
                return error.code or ""

        return await asyncio.gather(*(call() for _ in range(12)))

    started = time.monotonic()
    results = asyncio.run(exercise())
    elapsed = time.monotonic() - started
    assert 1 <= results.count("ok") <= 2
    assert set(results) == {"ok", "local_rate_limit"}
    assert elapsed < module.MAX_ADMISSION_WAIT + 0.5

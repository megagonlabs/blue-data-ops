from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest

from blue_data_ops import ErrorCode, FunctionResult
from blue_data_ops import _execution_scope as scope
from blue_data_ops.llm import LLMClient
from blue_data_ops.llm import client as client_module
from blue_data_ops.operators import OperatorRegistry
from blue_data_ops.operators.types import Attributes, DataBundle, Properties
from tests.unit.llm.test_temperature_fallback import install, prepared
from tests.unit.operators.test_v2_execution import ProbeOperator


@pytest.mark.parametrize("wait_kind", ["rate", "lock", "backoff", "semaphore"])
def test_operator_deadline_retires_owned_wait_and_preserves_bound_identity(
    wait_kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = install(monkeypatch, [RuntimeError("local retry")] if wait_kind == "backoff" else [])
    client = LLMClient("test", prepared({"llm.rate_limit": 1}))
    finished = threading.Event()
    if wait_kind == "rate":
        client.execute_api_call({})
    if wait_kind == "lock":
        client._rate_lock.acquire()  # pyright: ignore[reportPrivateUsage]

    class WaitingOperator(ProbeOperator):
        name = "waiting"

        def _execute(
            self,
            input_data: DataBundle,
            attributes: Attributes,
            properties: Properties | None = None,
        ) -> FunctionResult:
            try:
                if wait_kind == "semaphore":

                    async def blocked() -> None:
                        sem = asyncio.Semaphore(0)

                        def resolve(controls: Any) -> asyncio.Semaphore:
                            return sem

                        monkeypatch.setattr(client, "_resolve_semaphore", resolve)
                        await client.aexecute_api_call({})

                    asyncio.run(blocked())
                else:
                    client.execute_api_call({})
                return FunctionResult(input_data, {})
            finally:
                finished.set()

    registry = OperatorRegistry()
    registry.register(WaitingOperator(), version="9.0.0")
    operator = registry.resolve("waiting@9.0.0")
    started = time.monotonic()
    try:
        _, _, meta = operator.run(
            [[{"v": 1}]], {"required": "yes"}, {"execution.timeout_seconds": 0.04}
        )
        assert meta.errors[0].code is ErrorCode.OPERATOR_TIMEOUT
        assert meta.errors[0].operator_id == "waiting@9.0.0"
        assert finished.wait(0.3)
        assert time.monotonic() - started < 0.4
        assert len(calls) == (1 if wait_kind in {"rate", "backoff"} else 0)
        time.sleep(0.03)
        assert len(calls) == (1 if wait_kind in {"rate", "backoff"} else 0)
        assert scope._CURRENT.get() is None  # pyright: ignore[reportPrivateUsage]
    finally:
        if wait_kind == "lock":
            client._rate_lock.release()  # pyright: ignore[reportPrivateUsage]


def test_worker_expiration_before_future_timeout_keeps_timeout_code() -> None:
    class ExpiringOperator(ProbeOperator):
        def _execute(
            self,
            input_data: DataBundle,
            attributes: Attributes,
            properties: Properties | None = None,
        ) -> FunctionResult:
            raise scope.ScopeExpired

    _, _, meta = ExpiringOperator().run([[]], {"required": "yes"}, {"execution.timeout_seconds": 1})
    assert meta.errors[0].code is ErrorCode.OPERATOR_TIMEOUT
    assert scope._CURRENT.get() is None  # pyright: ignore[reportPrivateUsage]


def test_nested_deadline_and_stop_reset_context() -> None:
    outer = scope.create(0.03)
    with scope.activate(outer):
        inner = scope.create(20)
        assert inner.deadline == outer.deadline
        with scope.activate(inner):
            outer.stop.set()
            with pytest.raises(scope.ScopeExpired):
                scope.wait_sync(1)
        assert scope._CURRENT.get() is outer  # pyright: ignore[reportPrivateUsage]
    assert scope._CURRENT.get() is None  # pyright: ignore[reportPrivateUsage]
    scope.wait_sync(0)


@pytest.mark.parametrize("wait_kind", ["rate", "lock", "backoff", "semaphore"])
@pytest.mark.parametrize("stop", [False, True])
def test_native_async_cancellation_and_stop_release_permits(
    wait_kind: str, stop: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = install(monkeypatch, [RuntimeError("local retry")] if wait_kind == "backoff" else [])
    props = prepared({"llm.rate_limit": 1, "llm.max_parallel": 1})
    client = LLMClient("test", props)

    async def exercise() -> None:
        if wait_kind == "rate":
            await client.aexecute_api_call({})
        sem = client._resolve_semaphore(  # pyright: ignore[reportPrivateUsage]
            client_module._AdmissionControls(1, 1)  # pyright: ignore[reportPrivateUsage]
        )
        if wait_kind == "semaphore":
            await sem.acquire()
        if wait_kind == "lock":
            client._rate_lock.acquire()  # pyright: ignore[reportPrivateUsage]
        task_scope = scope.create(1)
        try:
            with scope.activate(task_scope):
                task = asyncio.create_task(client.aexecute_api_call({}))
                await asyncio.sleep(0.02)
                if stop:
                    task_scope.stop.set()
                    with pytest.raises(scope.ScopeExpired):
                        await asyncio.wait_for(task, 0.2)
                else:
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                    task_scope.stop.set()
                with pytest.raises(scope.ScopeExpired):
                    await client.aexecute_api_call({})
        finally:
            if wait_kind == "lock":
                client._rate_lock.release()  # pyright: ignore[reportPrivateUsage]
            if wait_kind == "semaphore":
                sem.release()
        assert not sem.locked()
        assert len(calls) == (1 if wait_kind in {"rate", "backoff"} else 0)
        result = await asyncio.wait_for(client.aexecute_api_call({}, {"llm.rate_limit": 0}), 0.3)
        assert result == "ok"

    asyncio.run(exercise())


def test_cache_diagnostic_is_actionable_at_operator_boundary(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from blue_data_ops.operators import active_registry

    install(monkeypatch, [])
    unsafe = tmp_path / "synthetic-private-path"
    unsafe.mkdir(mode=0o755)
    _, _, meta = (
        active_registry()
        .resolve("nl2llm@3.0.0")
        .run([[]], {"query": "x"}, {"llm.cache": True, "llm.cache_dir": str(unsafe)})
    )
    [error] = meta.errors
    assert "llm.cache_dir" in error.message
    assert error.suggestion and "0700" in error.suggestion
    assert str(unsafe) not in error.message + error.suggestion

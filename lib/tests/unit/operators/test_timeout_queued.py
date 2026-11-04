from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future

import pytest

import blue_data_ops.operators.operator as operator_module
from blue_data_ops import ErrorCode, ErrorStage, FunctionResult
from tests.unit.operators.test_v2_execution import ProbeOperator


def test_timeout_cancels_queued_body_before_start(monkeypatch: pytest.MonkeyPatch) -> None:
    future: Future[FunctionResult] = Future()
    shutdown_calls: list[tuple[bool, bool]] = []

    class QueuedExecutor:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def submit(
            self, fn: Callable[..., FunctionResult], *args: object, **kwargs: object
        ) -> Future[FunctionResult]:
            del fn, args, kwargs
            return future

        def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
            shutdown_calls.append((wait, cancel_futures))

    monkeypatch.setattr(operator_module, "ThreadPoolExecutor", QueuedExecutor)
    operator = ProbeOperator()
    output, attributes, meta = operator.run(
        [[{"x": 1}]],
        {"required": "given"},
        {"execution.timeout_seconds": 0.001},
    )
    assert output == [[]]
    assert attributes == {}
    assert meta.errors[0].code is ErrorCode.OPERATOR_TIMEOUT
    assert meta.errors[0].stage is ErrorStage.EXECUTE
    assert operator.body_calls == 0
    assert future.cancelled()
    assert not future.set_running_or_notify_cancel()
    assert shutdown_calls == [(False, True)]

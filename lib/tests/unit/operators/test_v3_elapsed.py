from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from threading import Event
from typing import Any, NoReturn, ParamSpec, TypeVar, cast

import pytest

from blue_data_ops.operators import _outcomes
from blue_data_ops.operators import operator as runtime
from blue_data_ops.operators.registry import versioned_registry
from blue_data_ops.operators.types import (
    Attributes,
    DataBundle,
    ExecMeta,
    FunctionResult,
    Properties,
    ValidationResult,
)

P = ParamSpec("P")
T = TypeVar("T")


def fail(*args: object, **kwargs: object) -> NoReturn:
    raise RuntimeError("test failure")


@pytest.mark.parametrize(
    "outcome,expected",
    [
        ("success", None),
        ("empty", None),
        ("invalid", ("INVALID_INPUT", "VALIDATE")),
        ("execution", ("EXECUTION_FAILED", "EXECUTE")),
        ("validator", ("VALIDATION_FAILED", "VALIDATE")),
        ("normalization", ("EXECUTION_RESULT_INVALID", "NORMALIZE")),
        ("timeout_setting", ("INVALID_INPUT", "VALIDATE")),
    ],
)
def test_elapsed_on_every_return_path(
    monkeypatch: pytest.MonkeyPatch, outcome: str, expected: tuple[str, str] | None
) -> None:
    operator = versioned_registry().resolve("avg@3.0.0")
    clock = iter([12.0, 12.125])
    monkeypatch.setattr(_outcomes, "monotonic", lambda: next(clock))
    rows: DataBundle
    settings: Attributes
    properties: Properties
    rows, settings, properties = [[{"x": 5}]], {"avg_key": "x"}, {}
    if outcome == "empty":
        rows = [[]]
    elif outcome == "invalid":
        settings = {}
    elif outcome == "execution":
        monkeypatch.setattr(operator, "_execute", fail)
    elif outcome == "validator":
        monkeypatch.setattr(operator, "_validate_input", fail)
    elif outcome == "normalization":

        def malformed_result(*args: object) -> object:
            return object()

        monkeypatch.setattr(operator, "_execute", malformed_result)
    elif outcome == "timeout_setting":
        properties = {"execution.timeout_seconds": 0}
    data, attributes, meta = operator.run(rows, settings, properties)
    assert meta.traces["elapsed_ms"] == 125.0
    assert meta.traces["input_shape"] == {
        "groups": 1,
        "rows_per_group": [0 if outcome == "empty" else 1],
    }
    if expected is None:
        assert meta.traces["output_shape"] == {
            "groups": 1,
            "rows_per_group": [0 if outcome == "empty" else 1],
        }
    else:
        assert "output_shape" not in meta.traces
    assert [(error.code.value, error.stage.value) for error in meta.errors] == (
        [] if expected is None else [expected]
    )
    if expected:
        assert data == [[]] and attributes == {} and meta.is_empty is False
    else:
        assert meta.is_empty is (outcome == "empty")


def test_timer_covers_defaults_validation_execution_and_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = versioned_registry().resolve("avg@3.0.0")
    now = [10.0]
    monkeypatch.setattr(_outcomes, "monotonic", lambda: now[0])

    def measured(function: Callable[P, T]) -> Callable[P, T]:
        def invoke(*args: P.args, **kwargs: P.kwargs) -> T:
            now[0] += 0.125
            return function(*args, **kwargs)

        return invoke

    monkeypatch.setattr(runtime, "apply_defaults", measured(runtime.apply_defaults))
    monkeypatch.setattr(
        operator,
        "_validate_input",
        measured(
            cast(
                Callable[[DataBundle, Attributes, Properties | None], ValidationResult],
                getattr(operator, "_validate_input"),
            )
        ),
    )
    monkeypatch.setattr(
        operator,
        "_execute",
        measured(
            cast(
                Callable[[DataBundle, Attributes, Properties | None], FunctionResult],
                getattr(operator, "_execute"),
            )
        ),
    )
    monkeypatch.setattr(
        runtime,
        "_normalize_data",
        measured(
            cast(
                Callable[[DataBundle], tuple[DataBundle, bool]],
                getattr(runtime, "_normalize_data"),
            )
        ),
    )
    result = operator.run([[{"x": 9}]], {"avg_key": "x"})
    assert result[2].traces == {
        "elapsed_ms": 500.0,
        "input_shape": {"groups": 1, "rows_per_group": [1]},
        "output_shape": {"groups": 1, "rows_per_group": [1]},
    }


@pytest.mark.parametrize(
    "readings",
    [
        [RuntimeError()],
        [5.0, RuntimeError()],
        [float("nan"), 6.0],
        [5.0, float("inf")],
        [6.0, 5.0],
    ],
)
def test_unavailable_clock_does_not_fail_the_result(
    monkeypatch: pytest.MonkeyPatch, readings: list[float | Exception]
) -> None:
    clock = iter(readings)

    def monotonic() -> float:
        value = next(clock)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(_outcomes, "monotonic", monotonic)
    data, attributes, meta = (
        versioned_registry().resolve("avg@3.0.0").run([[{"x": 9}]], {"avg_key": "x"})
    )
    assert data == [[{"avg": 9}]] and attributes == {"num_values_used": 1}
    assert not meta.errors and "elapsed_ms" not in meta.traces
    assert meta.traces == {
        "input_shape": {"groups": 1, "rows_per_group": [1]},
        "output_shape": {"groups": 1, "rows_per_group": [1]},
    }


def test_timeout_metadata_survives_late_worker_completion_and_another_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = versioned_registry().resolve("avg@3.0.0")
    original = cast(
        Callable[[DataBundle, Attributes, Properties | None], FunctionResult],
        getattr(operator, "_execute"),
    )
    entered, release = Event(), Event()
    futures: list[Future[tuple[DataBundle, Attributes, ExecMeta]]] = []

    def delayed(
        data: DataBundle, attributes: Attributes, properties: Properties | None
    ) -> FunctionResult:
        entered.set()
        assert release.wait(5), "test did not release the worker"
        return original(data, attributes, properties)

    class TimeoutFuture:
        def __init__(self, future: Future[tuple[DataBundle, Attributes, ExecMeta]]) -> None:
            self.future = future

        def result(self, timeout: float | None) -> NoReturn:
            assert entered.wait(5), "worker did not start"
            raise TimeoutError

        def cancel(self) -> bool:
            return self.future.cancel()

    class ControlledExecutor:
        def __init__(self, **kwargs: Any) -> None:
            self.executor = ThreadPoolExecutor(**kwargs)

        def submit(self, *args: Any) -> TimeoutFuture:
            future: Future[tuple[DataBundle, Attributes, ExecMeta]] = self.executor.submit(*args)
            futures.append(future)
            return TimeoutFuture(future)

        def shutdown(self, **kwargs: Any) -> None:
            return self.executor.shutdown(**kwargs)

    monkeypatch.setattr(runtime, "ThreadPoolExecutor", ControlledExecutor)
    monkeypatch.setattr(operator, "_execute", delayed)
    clock = iter([2.0, 2.25, 8.0, 8.5])
    monkeypatch.setattr(_outcomes, "monotonic", lambda: next(clock))
    late: tuple[DataBundle, Attributes, ExecMeta] | None = None
    timed_out: tuple[DataBundle, Attributes, ExecMeta] | None = None
    completed: tuple[DataBundle, Attributes, ExecMeta] | None = None
    try:
        timed_out = operator.run(
            [[{"x": 9}]],
            {"avg_key": "x"},
            {
                "execution.timeout_seconds": 1,
            },
        )
        assert timed_out[0:2] == ([[]], {})
        assert timed_out[2].errors[0].code.value == "OPERATOR_TIMEOUT"
        assert timed_out[2].traces == {
            "elapsed_ms": 250.0,
            "input_shape": {"groups": 1, "rows_per_group": [1]},
        }
        monkeypatch.setattr(operator, "_execute", original)
        completed = operator.run([[{"x": 20}]], {"avg_key": "x"})
        assert completed[2].traces == {
            "elapsed_ms": 500.0,
            "input_shape": {"groups": 1, "rows_per_group": [1]},
            "output_shape": {"groups": 1, "rows_per_group": [1]},
        }
    finally:
        release.set()
        for future in futures:
            late = future.result(timeout=5)
    assert late is not None
    assert timed_out is not None
    assert completed is not None
    assert late[0] == [[{"avg": 9}]] and late[1] == {"num_values_used": 1}
    assert late[2].traces == {}
    assert timed_out[1] == {} and timed_out[2].traces == {
        "elapsed_ms": 250.0,
        "input_shape": {"groups": 1, "rows_per_group": [1]},
    }
    assert completed[1] == {"num_values_used": 1}


@pytest.mark.parametrize(
    "name,settings,rows",
    [
        ("avg", {"avg_key": "x"}, [[{"x": 1}]]),
        ("join", {"join_on": [["id"], ["id"]]}, [[{"id": 1}], [{"id": 1}]]),
        ("insert_table", {"source": "x", "database": "x", "table": "x"}, cast(DataBundle, [[]])),
    ],
)
def test_only_new_versions_get_timing(
    monkeypatch: pytest.MonkeyPatch, name: str, settings: Attributes, rows: DataBundle
) -> None:
    registry = versioned_registry()
    clock = iter([1.0, 1.0])
    monkeypatch.setattr(_outcomes, "monotonic", lambda: next(clock))
    for version in ("1.0.0", "2.0.0"):
        assert registry.resolve(f"{name}@{version}").run(rows, settings)[2].traces == {}
    result = registry.resolve(f"{name}@3.0.0").run(rows, settings)
    assert result[2].traces["elapsed_ms"] == 0.0
    assert result[2].traces["input_shape"] == {
        "groups": len(rows),
        "rows_per_group": [len(group) for group in rows],
    }
    if result[2].errors:
        assert "output_shape" not in result[2].traces
    else:
        assert result[2].traces["output_shape"] == {
            "groups": len(result[0]),
            "rows_per_group": [len(group) for group in result[0]],
        }

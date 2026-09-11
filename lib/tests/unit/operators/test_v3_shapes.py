from __future__ import annotations

from typing import NoReturn, cast

import pytest

from blue_data_ops.operators import _outcomes
from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.registry import versioned_registry
from blue_data_ops.operators.types import Attributes, DataBundle, FunctionResult, Properties
from tests.unit.operators._registry_catalog_expectations import ADDED_OPERATOR_IDS


class EchoOutcome(_OutcomeOperator):
    name = "shape_echo"

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        del attributes, properties
        return input_data


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_outcomes, "monotonic", lambda: 1.0)


def test_shapes_preserve_mixed_group_structure() -> None:
    rows = [[], [{"x": 1}, {"x": 2}]]
    data, attributes, meta = EchoOutcome().run(rows, {})

    assert data == rows and attributes == {} and not meta.errors
    assert meta.traces == {
        "elapsed_ms": 0.0,
        "input_shape": {"groups": 2, "rows_per_group": [0, 2]},
        "output_shape": {"groups": 2, "rows_per_group": [0, 2]},
    }


def test_all_empty_output_is_normalized_after_input_shape_capture() -> None:
    data, attributes, meta = EchoOutcome().run([[], []], {})

    assert data == [[]] and attributes == {} and meta.is_empty and not meta.errors
    assert meta.traces == {
        "elapsed_ms": 0.0,
        "input_shape": {"groups": 2, "rows_per_group": [0, 0]},
        "output_shape": {"groups": 1, "rows_per_group": [0]},
    }


def test_input_and_output_shapes_do_not_retain_bundle_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = versioned_registry().resolve("avg@3.0.0")
    rows = [[{"x": 9}]]

    def mutating_execute(
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None,
    ) -> FunctionResult:
        del attributes, properties
        input_data.append([{"late": True}])
        return FunctionResult([[{"avg": 9}]], {"num_values_used": 1})

    monkeypatch.setattr(operator, "_execute", mutating_execute)
    data, attributes, meta = operator.run(rows, {"avg_key": "x"})
    rows[0].append({"x": 10})
    data[0].append({"avg": 10})

    assert attributes == {"num_values_used": 1} and not meta.errors
    assert meta.traces == {
        "elapsed_ms": 0.0,
        "input_shape": {"groups": 1, "rows_per_group": [1]},
        "output_shape": {"groups": 1, "rows_per_group": [1]},
    }


@pytest.mark.parametrize("failure", ["validation", "execution", "normalization"])
def test_failure_keeps_valid_input_shape_and_omits_output_shape(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    operator = versioned_registry().resolve("avg@3.0.0")

    if failure == "execution":

        def fail(*args: object, **kwargs: object) -> NoReturn:
            raise RuntimeError("test failure")

        monkeypatch.setattr(operator, "_execute", fail)
    elif failure == "normalization":

        def malformed(*args: object, **kwargs: object) -> object:
            return object()

        monkeypatch.setattr(operator, "_execute", malformed)

    settings = {} if failure == "validation" else {"avg_key": "x"}
    data, attributes, meta = operator.run([[{"x": 9}]], settings)

    assert data == [[]] and attributes == {} and meta.errors
    assert meta.traces == {
        "elapsed_ms": 0.0,
        "input_shape": {"groups": 1, "rows_per_group": [1]},
    }


def test_invalid_bundle_omits_both_shapes() -> None:
    invalid = cast(DataBundle, [{"x": 9}])
    data, attributes, meta = (
        versioned_registry().resolve("avg@3.0.0").run(invalid, {"avg_key": "x"})
    )

    assert data == [[]] and attributes == {} and meta.errors
    assert meta.traces == {"elapsed_ms": 0.0}


def test_shape_instrumentation_failure_does_not_change_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_shape(value: DataBundle) -> NoReturn:
        raise RuntimeError("test instrumentation failure")

    monkeypatch.setattr(_outcomes, "_bundle_shape", fail_shape)
    data, attributes, meta = (
        versioned_registry().resolve("avg@3.0.0").run([[{"x": 9}]], {"avg_key": "x"})
    )

    assert data == [[{"avg": 9}]] and attributes == {"num_values_used": 1}
    assert not meta.errors and meta.traces == {"elapsed_ms": 0.0}


def test_only_the_21_exact_outcome_versions_use_the_shape_wrapper() -> None:
    registry = versioned_registry()
    cards = registry.list_cards()
    wrapped = {
        card.operator_id
        for card in cards
        if isinstance(registry.resolve(card.operator_id), _OutcomeOperator)
    }

    assert wrapped == set(ADDED_OPERATOR_IDS)
    assert len(wrapped) == 21
    assert not any(
        card.version in {"1.0.0", "2.0.0"} and card.operator_id in wrapped for card in cards
    )

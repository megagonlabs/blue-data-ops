from __future__ import annotations

from typing import cast
from unittest.mock import patch

import pytest

from blue_data_ops import ErrorCategory, ErrorCode, ErrorStage, FunctionResult, ValidationResult
from blue_data_ops.operators import (
    ArgmaxOperator,
    ArgminOperator,
    Attributes,
    AvgOperator,
    DataBundle,
    MaxOperator,
    MinOperator,
    Operator,
    Properties,
    SumOperator,
)

INPUT = [[{"value": 3}, {"value": "5"}, {"value": 5}]]

CASES: list[tuple[Operator, str, DataBundle, DataBundle]] = [
    (ArgmaxOperator(), "argmax_key", [[{"value": "5"}, {"value": 5}]], [[]]),
    (ArgminOperator(), "argmin_key", [[{"value": 3}]], [[]]),
    (AvgOperator(), "avg_key", [[{"avg": 13 / 3}]], [[{"avg": 0}]]),
    (MaxOperator(), "max_key", [[{"max": 5}]], [[{"max": None}]]),
    (MinOperator(), "min_key", [[{"min": 3}]], [[{"min": None}]]),
    (SumOperator(), "sum_key", [[{"sum": 13}]], [[{"sum": 0}]]),
]


@pytest.mark.parametrize(("operator", "key", "expected", "empty_expected"), CASES)
def test_native_execution_matches_public_apply(
    operator: Operator,
    key: str,
    expected: DataBundle,
    empty_expected: DataBundle,
) -> None:
    attributes = {key: "value"}

    result = getattr(operator, "_execute")(INPUT, attributes)

    assert type(result) is FunctionResult
    assert result == FunctionResult(expected, {})
    assert operator.apply(INPUT, attributes) == expected
    assert operator.apply([[]], attributes) == empty_expected


@pytest.mark.parametrize(("operator", "key", "expected", "empty_expected"), CASES)
def test_run_uses_native_result_and_keeps_call_attributes_unchanged(
    operator: Operator,
    key: str,
    expected: DataBundle,
    empty_expected: DataBundle,
) -> None:
    del empty_expected
    attributes: Attributes = {key: "value"}
    before = dict(attributes)

    output_data, output_attributes, meta = operator.run(INPUT, attributes)
    second_output_attributes = operator.run(INPUT, attributes)[1]

    assert output_data == expected
    assert output_attributes == {}
    assert output_attributes is not second_output_attributes
    assert meta.is_empty is False
    assert meta.errors == []
    assert attributes == before


@pytest.mark.parametrize(("operator", "key", "expected", "empty_expected"), CASES)
def test_invalid_input_is_canonical_and_suppresses_execution(
    operator: Operator,
    key: str,
    expected: DataBundle,
    empty_expected: DataBundle,
) -> None:
    del expected, empty_expected
    with patch.object(
        operator,
        "_execute",
        side_effect=AssertionError("execution must be suppressed"),
    ) as execute:
        output_data, output_attributes, meta = operator.run(INPUT, {})

    assert execute.call_count == 0
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert len(meta.errors) == 1
    error = meta.errors[0]
    assert error.category is ErrorCategory.RECOVERABLE
    assert error.code is ErrorCode.INVALID_INPUT
    assert error.stage is ErrorStage.VALIDATE
    assert error.operator_id == f"{operator.name}@2.0.0"
    assert error.suggestion == f"supply a non-empty {key}"


@pytest.mark.parametrize(("operator", "key", "expected", "empty_expected"), CASES)
def test_run_preserves_each_aggregate_empty_result(
    operator: Operator,
    key: str,
    expected: DataBundle,
    empty_expected: DataBundle,
) -> None:
    del expected
    output_data, output_attributes, meta = operator.run([[]], {key: "value"})

    assert output_data == empty_expected
    assert output_attributes == {}
    assert meta.is_empty is (empty_expected == [[]])
    assert meta.errors == []


class CountingSum(SumOperator):
    def __init__(self) -> None:
        self.execution_calls = 0

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        self.execution_calls += 1
        return super()._execute(input_data, attributes, properties)


def test_run_executes_sum_body_once_without_adapter_recursion() -> None:
    operator = CountingSum()

    output_data, output_attributes, meta = operator.run([[{"value": 4}]], {"sum_key": "value"})

    assert output_data == [[{"sum": 4}]]
    assert output_attributes == {}
    assert meta.errors == []
    assert operator.execution_calls == 1


class MalformedValidationSum(SumOperator):
    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        del input_data, attributes, properties
        return cast(ValidationResult, True)


def test_public_validate_requires_the_exact_structured_result() -> None:
    operator = MalformedValidationSum()

    assert operator.validate(INPUT, {"sum_key": "value"}) is False

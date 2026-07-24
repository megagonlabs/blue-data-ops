from __future__ import annotations

from collections.abc import Callable
from typing import cast
from unittest.mock import patch

import pytest

from blue_data_ops import ErrorCategory, ErrorCode, ErrorStage, FunctionResult, ValidationResult
from blue_data_ops.operators import (
    Attributes,
    DataBundle,
    DeleteOperator,
    InsertOperator,
    Operator,
    ProjectOperator,
    Properties,
    SelectOperator,
)

R1 = {"id": 1, "score": 1, "name": "A"}
R2 = {"id": 2, "score": 2, "name": "B"}
R3 = {"id": 3, "score": 3, "name": "C"}
INPUT = [[R1, R2]]

SUCCESS_CASES: list[tuple[Operator, Attributes, DataBundle]] = [
    (DeleteOperator(), {"delete_idx": 0}, [[R2]]),
    (InsertOperator(), {"insert_records": [R3], "insert_idx": 1}, [[R1, R3, R2]]),
    (ProjectOperator(), {"kept_keys": ["id"]}, [[{"id": 1}, {"id": 2}]]),
    (
        SelectOperator(),
        {"operand_key": "score", "operand": ">", "operand_val": 1},
        [[R2]],
    ),
]

INVALID_CASES: list[tuple[Operator, Attributes, str]] = [
    (
        DeleteOperator(),
        {"delete_idx": (0,)},
        "delete_idx must be an integer or a list of integers",
    ),
    (
        InsertOperator(),
        {"insert_idx": -2},
        "supply valid insert_records and insert_idx attributes",
    ),
    (
        ProjectOperator(),
        {},
        "supply compatible kept_keys and key_mapping attributes",
    ),
    (
        SelectOperator(),
        {"operand_key": "score", "operand": "~=", "operand_val": 1},
        "supply a supported operand and a nonnegative eps value",
    ),
]

EMPTY_CASES: list[tuple[Operator, Attributes, DataBundle, DataBundle]] = [
    (DeleteOperator(), {"delete_idx": 0}, [[]], []),
    (InsertOperator(), {"insert_records": [R3]}, [[]], []),
    (ProjectOperator(), {"kept_keys": []}, INPUT, []),
    (
        SelectOperator(),
        {"operand_key": "score", "operand": ">", "operand_val": 99},
        INPUT,
        [[]],
    ),
]


@pytest.mark.parametrize(("operator", "attributes", "expected"), SUCCESS_CASES)
def test_native_execution_matches_public_apply_and_run(
    operator: Operator,
    attributes: Attributes,
    expected: DataBundle,
) -> None:
    before = dict(attributes)

    result = getattr(operator, "_execute")(INPUT, attributes)
    raw = operator.apply(INPUT, attributes)
    first = operator.run(INPUT, attributes)
    second = operator.run(INPUT, attributes)

    assert type(result) is FunctionResult
    assert result == FunctionResult(expected, {})
    assert raw == expected
    assert first[0] == raw
    assert first[1] == {}
    assert first[1] is not second[1]
    assert first[2].errors == []
    assert attributes == before


@pytest.mark.parametrize(("operator", "attributes", "suggestion"), INVALID_CASES)
def test_invalid_input_is_recoverable_and_suppresses_execution(
    operator: Operator,
    attributes: Attributes,
    suggestion: str,
) -> None:
    with patch.object(
        operator,
        "_execute",
        side_effect=AssertionError("execution must be suppressed"),
    ) as execute:
        output_data, output_attributes, meta = operator.run(INPUT, attributes)

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
    assert error.suggestion == suggestion


@pytest.mark.parametrize(("operator", "attributes", "expected"), SUCCESS_CASES)
def test_run_executes_each_native_body_once(
    operator: Operator,
    attributes: Attributes,
    expected: DataBundle,
) -> None:
    native = getattr(operator, "_execute")
    with patch.object(operator, "_execute", wraps=native) as execute:
        output_data, output_attributes, meta = operator.run(INPUT, attributes)

    assert output_data == expected
    assert output_attributes == {}
    assert meta.errors == []
    assert execute.call_count == 1


@pytest.mark.parametrize(
    ("operator", "attributes", "input_data", "raw_empty"),
    EMPTY_CASES,
)
def test_run_canonicalizes_each_successful_empty(
    operator: Operator,
    attributes: Attributes,
    input_data: DataBundle,
    raw_empty: DataBundle,
) -> None:
    assert operator.apply(input_data, attributes) == raw_empty
    output_data, output_attributes, meta = operator.run(input_data, attributes)

    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is True
    assert meta.errors == []


@pytest.mark.parametrize(
    ("operator", "attributes", "default_name"),
    [
        (DeleteOperator(), {}, "delete_idx"),
        (InsertOperator(), {}, "insert_records"),
        (ProjectOperator(), {"kept_keys": ["id"]}, "key_mapping"),
    ],
)
def test_mutable_defaults_are_isolated_between_runs(
    operator: Operator,
    attributes: Attributes,
    default_name: str,
) -> None:
    seen: list[object] = []
    native = cast(
        Callable[[DataBundle, Attributes, Properties | None], FunctionResult],
        getattr(operator, "_execute"),
    )

    def capture(
        input_data: DataBundle,
        call_attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        seen.append(call_attributes[default_name])
        return native(input_data, call_attributes, properties)

    with patch.object(operator, "_execute", side_effect=capture):
        operator.run(INPUT, attributes)
        operator.run(INPUT, attributes)

    assert seen[0] == seen[1]
    assert seen[0] is not seen[1]
    assert attributes == ({} if not attributes else {"kept_keys": ["id"]})


def test_select_numeric_string_eps_keeps_raw_error_and_run_contains_it() -> None:
    operator = SelectOperator()
    attributes: Attributes = {
        "operand_key": "score",
        "operand": "=",
        "operand_val": 1,
        "eps": "0.5",
    }

    with pytest.raises(TypeError):
        operator.validate(INPUT, attributes)
    with pytest.raises(TypeError):
        operator.invoke(INPUT, attributes)

    with patch.object(
        operator,
        "_execute",
        side_effect=AssertionError("execution must be suppressed"),
    ) as execute:
        output_data, output_attributes, meta = operator.run(INPUT, attributes)

    assert execute.call_count == 0
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.errors[0].code is ErrorCode.VALIDATION_FAILED
    assert meta.errors[0].stage is ErrorStage.VALIDATE


@pytest.mark.parametrize("insert_index", [(0,), "0"])
def test_insert_lax_index_keeps_raw_error_and_run_contains_it(insert_index: object) -> None:
    operator = InsertOperator()
    attributes: Attributes = {"insert_records": [R3], "insert_idx": insert_index}

    assert operator.validate(INPUT, attributes) is True
    with pytest.raises(AttributeError):
        operator.apply(INPUT, attributes)
    with pytest.raises(AttributeError):
        operator.invoke(INPUT, attributes)

    output_data, output_attributes, meta = operator.run(INPUT, attributes)

    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert meta.errors[0].stage is ErrorStage.EXECUTE
    assert attributes == {"insert_records": [R3], "insert_idx": insert_index}


class MalformedValidationSelect(SelectOperator):
    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        del input_data, attributes, properties
        return cast(ValidationResult, True)


def test_public_validate_requires_the_exact_structured_result() -> None:
    operator = MalformedValidationSelect()

    assert (
        operator.validate(
            INPUT,
            {"operand_key": "score", "operand": "=", "operand_val": 1},
        )
        is False
    )

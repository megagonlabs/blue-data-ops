from __future__ import annotations

from unittest.mock import patch

import pytest

from blue_data_ops import ErrorCategory, ErrorCode, ErrorStage, FunctionResult, ValidationResult
from blue_data_ops.operators import (
    Attributes,
    DataBundle,
    IntersectOperator,
    JoinOperator,
    NormalizeTextOperator,
    Operator,
    SegmentTextOperator,
    UnionOperator,
)

RELATIONAL_INPUT: DataBundle = [
    [{"id": 1, "left": "L1"}, {"id": 2, "left": "L2"}],
    [{"id": 2, "right": "R2"}, {"id": 3, "right": "R3"}],
]

CASES: list[tuple[Operator, DataBundle, Attributes, DataBundle]] = [
    (
        IntersectOperator(),
        [[{"id": 1}, {"id": 2}], [{"id": 2}, {"id": 3}]],
        {},
        [[{"id": 2}]],
    ),
    (
        JoinOperator(),
        RELATIONAL_INPUT,
        {"join_on": [["id"], ["id"]]},
        [[{"id": 2, "left": "L2", "right": "R2"}]],
    ),
    (
        UnionOperator(),
        [[{"id": 1}, {"id": 2}], [{"id": 2}, {"id": 3}]],
        {},
        [[{"id": 1}, {"id": 2}, {"id": 3}]],
    ),
    (
        NormalizeTextOperator(),
        [[{"text": "  Hello\u00a0world  "}]],
        {"text_field": ["text"]},
        [[{"text": "  Hello\u00a0world  ", "text_norm": "Hello world"}]],
    ),
    (
        SegmentTextOperator(),
        [[{"doc_id": "doc", "text": "Hello world."}]],
        {"text_field": "text"},
        [
            [
                {
                    "segment_id": "doc::S0000",
                    "doc_id": "doc",
                    "text": "Hello world.",
                    "start_char": 0,
                    "end_char": 12,
                    "segment.split_strategy": "sentence",
                }
            ]
        ],
    ),
]

INVALID_CASES: list[tuple[Operator, DataBundle, Attributes, str]] = [
    (
        IntersectOperator(),
        [[{"id": 1}], [{"id": 1}]],
        {"match_option": "unknown"},
        "supply match_option as key_match or seq_match",
    ),
    (
        JoinOperator(),
        RELATIONAL_INPUT,
        {},
        "supply valid join_on, join_suffix, keep_keys, and join_type values",
    ),
    (
        UnionOperator(),
        [[{"id": 1}]],
        {"match_option": "unknown"},
        "supply match_option as key_match or seq_match",
    ),
    (
        NormalizeTextOperator(),
        [[{"text": "Hello"}]],
        {},
        "supply valid input attributes",
    ),
    (
        SegmentTextOperator(),
        [[{"text": "Hello"}]],
        {},
        "supply valid text segmentation options",
    ),
]

EMPTY_CASES: list[tuple[Operator, Attributes]] = [
    (IntersectOperator(), {}),
    (JoinOperator(), {"join_on": [["id"], ["id"]]}),
    (UnionOperator(), {}),
    (NormalizeTextOperator(), {"text_field": ["text"]}),
    (SegmentTextOperator(), {"text_field": "text"}),
]


@pytest.mark.parametrize(("operator", "input_data", "attributes", "expected"), CASES)
def test_native_result_and_public_paths_preserve_v1_output(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
    expected: DataBundle,
) -> None:
    result = operator._execute(  # pyright: ignore[reportPrivateUsage]
        input_data, attributes
    )

    assert type(result) is FunctionResult
    assert result == FunctionResult(expected, {})
    assert operator.apply(input_data, attributes) == expected
    assert operator.invoke(input_data, attributes) == expected


@pytest.mark.parametrize(("operator", "input_data", "attributes", "expected"), CASES)
def test_run_matches_raw_output_and_preserves_call_attributes(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
    expected: DataBundle,
) -> None:
    before = dict(attributes)

    output_data, output_attributes, meta = operator.run(input_data, attributes)
    second_output_attributes = operator.run(input_data, attributes)[1]

    assert output_data == expected
    assert output_attributes == {}
    assert output_attributes is not second_output_attributes
    assert meta.is_empty is False
    assert meta.errors == []
    assert attributes == before


@pytest.mark.parametrize(("operator", "input_data", "attributes", "reason"), INVALID_CASES)
def test_structured_validation_suppresses_execution(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
    reason: str,
) -> None:
    validation = operator._validate_input(  # pyright: ignore[reportPrivateUsage]
        input_data, attributes
    )
    assert type(validation) is ValidationResult
    assert validation == ValidationResult(False, reason)
    assert operator.validate(input_data, attributes) is False
    assert operator.invoke(input_data, attributes) is None

    with patch.object(
        operator,
        "_execute",
        side_effect=AssertionError("execution must be suppressed"),
    ) as execute:
        output_data, output_attributes, meta = operator.run(input_data, attributes)

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
    assert error.suggestion == reason


@pytest.mark.parametrize(("operator", "attributes"), EMPTY_CASES)
def test_run_normalizes_successful_empty_results(
    operator: Operator,
    attributes: Attributes,
) -> None:
    assert operator.apply([], attributes) == []

    output_data, output_attributes, meta = operator.run([], attributes)

    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is True
    assert meta.errors == []


@pytest.mark.parametrize(("operator", "input_data", "attributes", "expected"), CASES)
def test_run_calls_each_native_body_once(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
    expected: DataBundle,
) -> None:
    with patch.object(
        operator,
        "_execute",
        wraps=operator._execute,  # pyright: ignore[reportPrivateUsage]
    ) as execute:
        output_data, output_attributes, meta = operator.run(input_data, attributes)

    assert output_data == expected
    assert output_attributes == {}
    assert meta.errors == []
    assert execute.call_count == 1


def test_segment_text_unknown_placeholder_keeps_raw_error_and_run_contains_it() -> None:
    operator = SegmentTextOperator()
    input_data = [[{"doc_id": "doc", "text": "Hello world."}]]
    attributes: Attributes = {
        "text_field": "text",
        "segment_id_format": "{unknown}",
    }

    with pytest.raises(KeyError, match="unknown"):
        operator.apply(input_data, attributes)
    with pytest.raises(KeyError, match="unknown"):
        operator.invoke(input_data, attributes)

    output_data, output_attributes, meta = operator.run(input_data, attributes)

    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert len(meta.errors) == 1
    error = meta.errors[0]
    assert error.category is ErrorCategory.FAILED
    assert error.code is ErrorCode.EXECUTION_FAILED
    assert error.stage is ErrorStage.EXECUTE
    assert error.operator_id == "segment_text@2.0.0"
    assert "unknown" not in error.message
    assert error.message == "operator execution failed"
    assert error.suggestion == "Check the declared inputs and backend configuration."

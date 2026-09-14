from __future__ import annotations

import pytest

from blue_data_ops import ErrorCategory, ErrorCode, ErrorStage
from blue_data_ops.operators import (
    ArgmaxOperator,
    ArgminOperator,
    Attributes,
    AvgOperator,
    DataBundle,
    DeleteOperator,
    InsertOperator,
    IntersectOperator,
    JoinOperator,
    MaxOperator,
    MinOperator,
    NormalizeTextOperator,
    Operator,
    OperatorRegistry,
    ProjectOperator,
    SegmentTextOperator,
    SelectOperator,
    SumOperator,
    UnionOperator,
    default_registry,
)

INPUT: DataBundle = [[{"id": 1, "value": 3}], [{"id": 1, "value": 3}]]

INVALID_CASES: list[tuple[Operator, Attributes]] = [
    (ArgmaxOperator(), {}),
    (ArgminOperator(), {}),
    (AvgOperator(), {}),
    (DeleteOperator(), {"delete_idx": (0,)}),
    (InsertOperator(), {"insert_idx": -2}),
    (IntersectOperator(), {"match_option": "unknown"}),
    (JoinOperator(), {}),
    (MaxOperator(), {}),
    (MinOperator(), {}),
    (NormalizeTextOperator(), {}),
    (ProjectOperator(), {}),
    (SegmentTextOperator(), {}),
    (SelectOperator(), {"operand": "unknown"}),
    (SumOperator(), {}),
    (UnionOperator(), {"match_option": "unknown"}),
]


@pytest.mark.parametrize(("operator", "attributes"), INVALID_CASES)
def test_pure_operator_owns_native_execution_and_validation_hooks(
    operator: Operator,
    attributes: Attributes,
) -> None:
    del attributes
    operator_type = type(operator)

    assert "_execute" in operator_type.__dict__
    assert "_validate_input" in operator_type.__dict__


@pytest.mark.parametrize(("operator", "attributes"), INVALID_CASES)
def test_pure_operator_reports_selected_registry_version(
    operator: Operator,
    attributes: Attributes,
) -> None:
    registry = OperatorRegistry()
    registry.register(operator, "1.0.0")
    registry.register(operator, "2.0.0")

    for version in ("1.0.0", "2.0.0"):
        operator_id = f"{operator.name}@{version}"
        resolved = registry.resolve(operator_id)
        output_data, output_attributes, meta = resolved.run(INPUT, attributes)

        assert resolved.operator_id == operator_id
        assert output_data == [[]]
        assert output_attributes == {}
        assert len(meta.errors) == 1
        error = meta.errors[0]
        assert error.category is ErrorCategory.RECOVERABLE
        assert error.code is ErrorCode.INVALID_INPUT
        assert error.stage is ErrorStage.VALIDATE
        assert error.operator_id == operator_id
        assert error.suggestion


def test_v1_default_registry_is_a_33_card_compatibility_catalog() -> None:
    cards = default_registry().list_cards()

    assert len(cards) == 33
    assert all(card.version == "1.0.0" for card in cards)
    assert all(card.operator_id.endswith("@1.0.0") for card in cards)

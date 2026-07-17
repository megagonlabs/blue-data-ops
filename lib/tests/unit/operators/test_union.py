from __future__ import annotations

import math

import pytest

from blue_data_ops.operators import Attributes, DataBundle, UnionOperator


@pytest.fixture
def op() -> UnionOperator:
    return UnionOperator()


R1 = {"id": 1, "name": "A"}
R2 = {"id": 2, "name": "B"}
R3 = {"id": 3, "name": "C"}
IDENTITY_RECORD = {"id": 9, "payload": [1, {"x": True}]}

FUNCTION_CASES: list[tuple[str, DataBundle, Attributes, DataBundle]] = [
    (
        "U1",
        [[R1, R2], [{"name": "A", "id": 1}, R3]],
        {"match_option": "key_match"},
        [[R1, R2, R3]],
    ),
    (
        "U2",
        [
            [{"a": 1, "b": "x"}],
            [{"other": 1, "fields": "x"}, {"other": 2, "fields": "y"}],
        ],
        {"match_option": "seq_match"},
        [[{"a": 1, "b": "x"}, {"other": 2, "fields": "y"}]],
    ),
    (
        "U3",
        [[{"a": 1, "b": 2}], [{"b": 2, "a": 1}]],
        {"match_option": "seq_match"},
        [[{"a": 1, "b": 2}, {"b": 2, "a": 1}]],
    ),
    ("U4", [], {}, []),
    ("U5", [[]], {}, [[]]),
    ("U6", [[], []], {}, [[]]),
    (
        "U7",
        [[IDENTITY_RECORD, IDENTITY_RECORD], [{"id": 9, "payload": [1, {"x": True}]}]],
        {},
        [[IDENTITY_RECORD]],
    ),
    ("U8", [[{"id": 1}], [{"id": 1, "name": None}]], {}, [[{"id": 1}, {"id": 1, "name": None}]]),
    ("U10", [[R1], [{"name": "A", "id": 1}]], {}, [[R1]]),
]


@pytest.mark.parametrize(
    "case_id,input_data,attributes,expected",
    FUNCTION_CASES,
    ids=[case[0] for case in FUNCTION_CASES],
)
def test_apply(
    op: UnionOperator,
    case_id: str,
    input_data: DataBundle,
    attributes: Attributes,
    expected: DataBundle,
) -> None:
    assert op.apply(input_data, attributes) == expected


def test_apply_normalizes_nan_signatures(op: UnionOperator) -> None:
    first = {"x": math.nan}
    output = op.apply([[first], [{"x": math.nan}]], {})
    assert len(output[0]) == 1
    assert output[0][0] is first


def test_apply_preserves_first_record_identity(op: UnionOperator) -> None:
    output = op.apply(
        [[IDENTITY_RECORD, IDENTITY_RECORD], [{"id": 9, "payload": [1, {"x": True}]}]],
        {},
    )
    assert output[0][0] is IDENTITY_RECORD


VALIDATOR_CASES: list[tuple[str, Attributes, bool]] = [
    ("UV1", {}, True),
    ("UV2", {"match_option": "key_match"}, True),
    ("UV3", {"match_option": "seq_match"}, True),
    ("UV4", {"match_option": "identity"}, False),
    ("UV5", {"match_option": 1}, False),
    ("UV6", {"match_option": None}, False),
    ("UV7", {"match_option": b"key_match"}, False),
]


@pytest.mark.parametrize(
    "case_id,attributes,expected",
    VALIDATOR_CASES,
    ids=[case[0] for case in VALIDATOR_CASES],
)
def test_validate(op: UnionOperator, case_id: str, attributes: Attributes, expected: bool) -> None:
    assert op.validate([[R1]], attributes) is expected


def test_invoke_default(op: UnionOperator) -> None:
    assert op.invoke([[R1], [{"name": "A", "id": 1}]], {}) == [[R1]]


def test_invoke_invalid_returns_none(op: UnionOperator) -> None:
    assert op.invoke([[R1]], {"match_option": "identity"}) is None


def test_invoke_one_empty_source_returns_wrapped_empty(op: UnionOperator) -> None:
    assert op.invoke([[]], {}) == [[]]


def test_direct_invalid_apply_raises_when_signature_is_generated(op: UnionOperator) -> None:
    with pytest.raises(ValueError, match="Invalid match_option: identity"):
        op.apply([[R1]], {"match_option": "identity"})


def test_interface_contract(op: UnionOperator) -> None:
    assert op.name == "union"
    assert op.description == (
        "Given multiple input data sources, combine all records and remove exact duplicates"
    )
    spec = op.attributes["match_option"]
    assert set(op.attributes) == {"match_option"}
    assert spec.type == "str"
    assert spec.description == (
        "Matching strategy for duplicate detection: 'key_match' (exact field names and values) or "
        "'seq_match' (position-based comparison regardless of field names)"
    )
    assert op.is_required("match_option") is False
    assert op.default_of("match_option") == "key_match"

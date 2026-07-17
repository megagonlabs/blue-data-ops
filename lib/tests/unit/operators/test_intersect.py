from __future__ import annotations

import math

import pytest

from blue_data_ops.operators import Attributes, DataBundle, IntersectOperator


@pytest.fixture
def op() -> IntersectOperator:
    return IntersectOperator()


BASE_FIRST = {"id": 1, "name": "A"}
BASE_DUPLICATE = {"id": 1, "name": "A"}
BASE_DATA = [BASE_FIRST, {"id": 2, "name": "B"}, BASE_DUPLICATE]

FUNCTION_CASES: list[tuple[str, DataBundle, Attributes, DataBundle]] = [
    (
        "I1",
        [
            BASE_DATA,
            [{"name": "A", "id": 1}, {"id": 3, "name": "C"}],
            [{"id": 1, "name": "A"}, {"id": 4, "name": "D"}],
        ],
        {"match_option": "key_match"},
        [[BASE_FIRST, BASE_DUPLICATE]],
    ),
    (
        "I2",
        [
            [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}],
            [{"c": 1, "d": "x"}],
            [{"e": 1, "f": "x"}],
        ],
        {"match_option": "seq_match"},
        [[{"a": 1, "b": "x"}]],
    ),
    (
        "I3",
        [[{"a": 1, "b": 2}], [{"b": 2, "a": 1}]],
        {"match_option": "seq_match"},
        [[]],
    ),
    ("I4", [], {}, []),
    ("I5", [[]], {}, []),
    ("I6", [[], []], {}, []),
    (
        "I7",
        [[{"id": 1}], [], [{"id": 1}], [{"id": 1}, {"id": 2}]],
        {},
        [[{"id": 1}]],
    ),
    (
        "I8",
        [[], [BASE_FIRST, {"id": 2}], [{"name": "A", "id": 1}]],
        {},
        [[BASE_FIRST]],
    ),
    ("I9", [[{"id": 1}], [{"id": 2}]], {}, [[]]),
    ("I10", [[{"id": 1}], [{"id": 1, "name": None}]], {}, [[]]),
]


@pytest.mark.parametrize(
    "case_id,input_data,attributes,expected",
    FUNCTION_CASES,
    ids=[case[0] for case in FUNCTION_CASES],
)
def test_apply(
    op: IntersectOperator,
    case_id: str,
    input_data: DataBundle,
    attributes: Attributes,
    expected: DataBundle,
) -> None:
    assert op.apply(input_data, attributes) == expected


def test_apply_preserves_base_duplicates_and_identity(op: IntersectOperator) -> None:
    output = op.apply(
        [BASE_DATA, [{"name": "A", "id": 1}], [{"id": 1, "name": "A"}]],
        {},
    )
    assert len(output[0]) == 2
    assert output[0][0] is BASE_FIRST
    assert output[0][1] is BASE_DUPLICATE


def test_apply_uses_first_non_empty_source_as_identity_base(op: IntersectOperator) -> None:
    output = op.apply([[], [BASE_FIRST, {"id": 2}], [{"name": "A", "id": 1}]], {})
    assert output[0][0] is BASE_FIRST


def test_apply_normalizes_nan_signatures(op: IntersectOperator) -> None:
    first = {"x": math.nan}
    output = op.apply([[first], [{"x": math.nan}]], {})
    assert len(output[0]) == 1
    assert output[0][0] is first


VALIDATOR_CASES: list[tuple[str, Attributes, bool]] = [
    ("IV1", {}, True),
    ("IV2", {"match_option": "key_match"}, True),
    ("IV3", {"match_option": "seq_match"}, True),
    ("IV4", {"match_option": "identity"}, False),
    ("IV5", {"match_option": 1}, False),
    ("IV6", {"match_option": None}, False),
    ("IV7", {"match_option": b"key_match"}, False),
]


@pytest.mark.parametrize(
    "case_id,attributes,expected",
    VALIDATOR_CASES,
    ids=[case[0] for case in VALIDATOR_CASES],
)
def test_validate(
    op: IntersectOperator, case_id: str, attributes: Attributes, expected: bool
) -> None:
    assert op.validate([[BASE_FIRST], [{"name": "A", "id": 1}]], attributes) is expected


def test_invoke_default(op: IntersectOperator) -> None:
    assert op.invoke([[BASE_FIRST], [{"name": "A", "id": 1}]], {}) == [[BASE_FIRST]]


def test_invoke_invalid_returns_none(op: IntersectOperator) -> None:
    assert op.invoke([[BASE_FIRST], [BASE_FIRST]], {"match_option": "identity"}) is None


def test_invoke_two_empty_sources_returns_guard_empty(op: IntersectOperator) -> None:
    assert op.invoke([[], []], {}) == []


def test_direct_invalid_apply_raises_when_signature_is_generated(op: IntersectOperator) -> None:
    with pytest.raises(ValueError, match="Invalid match_option: identity"):
        op.apply([[BASE_FIRST], [BASE_FIRST]], {"match_option": "identity"})


def test_interface_contract(op: IntersectOperator) -> None:
    assert op.name == "intersect"
    assert op.description == (
        "Given multiple input data sources, return only records that exist in all data sources"
    )
    spec = op.attributes["match_option"]
    assert set(op.attributes) == {"match_option"}
    assert spec.type == "str"
    assert spec.description == (
        "Matching strategy for record comparison: 'key_match' (exact field names and values) or "
        "'seq_match' (position-based comparison regardless of field names)"
    )
    assert op.is_required("match_option") is False
    assert op.default_of("match_option") == "key_match"

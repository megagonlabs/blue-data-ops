"""Behavior and declarative-interface tests for the `select` operator."""

from __future__ import annotations

import pytest

from blue_data_ops.operators import Attributes, DataBundle, SelectOperator

REC1 = {"job_id": 1, "name": "name A", "salary": 80000, "experience": 3}
REC2 = {"job_id": 2, "name": "name B", "salary": 95000, "experience": 5}
REC3 = {"job_id": 3, "name": "name C", "salary": 75000, "experience": 4}
D = [REC1, REC2, REC3]
INPUT_DATA = [D]


@pytest.fixture
def op() -> SelectOperator:
    return SelectOperator()


# --- A. apply() — output shape: normal -> [result]; no-match -> [[]]; empty-input -> [] ---
FUNCTION_CASES: list[tuple[str, DataBundle, Attributes, DataBundle]] = [
    (
        "F1",
        INPUT_DATA,
        {"operand_key": "experience", "operand": ">=", "operand_val": 4},
        [[REC2, REC3]],
    ),
    (
        "F2",
        INPUT_DATA,
        {"operand_key": "name", "operand": "!=", "operand_val": "name B"},
        [[REC1, REC3]],
    ),
    ("F3", INPUT_DATA, {"operand_key": "salary", "operand": ">", "operand_val": 80000}, [[REC2]]),
    ("F4", INPUT_DATA, {"operand_key": "experience", "operand": "=", "operand_val": 4}, [[REC3]]),
    (
        "F5",
        INPUT_DATA,
        {
            "operand_key": "salary",
            "operand": "=",
            "operand_val": 80000.5,
            "approximate_match": True,
            "eps": 1.0,
        },
        [[REC1]],
    ),
    (
        "F6",
        INPUT_DATA,
        {
            "operand_key": "salary",
            "operand": "=",
            "operand_val": 80000.5,
            "approximate_match": False,
            "eps": 1.0,
        },
        [[]],
    ),
    (
        "F7",
        INPUT_DATA,
        {"operand_key": "name", "operand": ">", "operand_val": "name A"},
        [[REC2, REC3]],
    ),
    ("F8", INPUT_DATA, {"operand_key": "experience", "operand": "=", "operand_val": "4"}, [[]]),
    (
        "F9",
        INPUT_DATA,
        {"operand_key": "experience", "operand": "!=", "operand_val": "4"},
        [[REC1, REC2, REC3]],
    ),
    ("F10", INPUT_DATA, {"operand_key": "nonexistent", "operand": "=", "operand_val": 1}, [[]]),
    ("F11a", [], {"operand_key": "experience", "operand": ">=", "operand_val": 4}, []),
    ("F11b", [[]], {"operand_key": "experience", "operand": ">=", "operand_val": 4}, []),
    (
        "F12",
        INPUT_DATA,
        {
            "operand_key": "salary",
            "operand": "!=",
            "operand_val": 80000.5,
            "approximate_match": True,
            "eps": 1.0,
        },
        [[REC2, REC3]],
    ),
]


@pytest.mark.parametrize(
    "case_id,input_data,attributes,expected", FUNCTION_CASES, ids=[c[0] for c in FUNCTION_CASES]
)
def test_apply(
    op: SelectOperator,
    case_id: str,
    input_data: DataBundle,
    attributes: Attributes,
    expected: DataBundle,
) -> None:
    assert op.apply(input_data, attributes) == expected


# --- B. validate() — total (never raises); validated against the operator's own spec ---
VALIDATOR_CASES: list[tuple[str, Attributes, bool]] = [
    ("V1", {"operand_key": "experience", "operand": ">=", "operand_val": 4}, True),
    ("V2", {"operand_key": "experience", "operand": "~=", "operand_val": 4}, False),
    ("V3", {"operand_key": "experience", "operand": ">=", "operand_val": 4, "eps": -1}, False),
    ("V4", {"operand": ">=", "operand_val": 4}, False),
    (
        "V5",
        {
            "operand_key": "experience",
            "operand": ">=",
            "operand_val": 4,
            "approximate_match": True,
            "eps": 0.5,
        },
        True,
    ),
]


@pytest.mark.parametrize(
    "case_id,attributes,expected", VALIDATOR_CASES, ids=[c[0] for c in VALIDATOR_CASES]
)
def test_validate(op: SelectOperator, case_id: str, attributes: Attributes, expected: bool) -> None:
    assert op.validate(INPUT_DATA, attributes) is expected


def test_validate_is_total(op: SelectOperator) -> None:
    junk_cases: list[Attributes] = [{}, {"operand": 123}, {"operand_key": object()}]
    for junk in junk_cases:
        assert isinstance(op.validate(INPUT_DATA, junk), bool)


# --- C. invoke() — validate unconditionally; falsy -> None; else apply() ---
def test_invoke_valid(op: SelectOperator) -> None:
    out = op.invoke(INPUT_DATA, {"operand_key": "experience", "operand": ">=", "operand_val": 4})
    assert out == [[REC2, REC3]]


def test_invoke_invalid(op: SelectOperator) -> None:
    out = op.invoke(INPUT_DATA, {"operand_key": "experience", "operand": "~=", "operand_val": 4})
    assert out is None


# --- Declarative interface contract ---
def test_interface_identity(op: SelectOperator) -> None:
    assert op.name == "select"
    assert op.description == (
        "Given an input data, filter data elements based on a specified condition "
        "by type-aware comparison (record-wise)"
    )


def test_interface_attributes(op: SelectOperator) -> None:
    assert set(op.attributes) == {
        "operand_key",
        "operand",
        "operand_val",
        "approximate_match",
        "eps",
    }
    assert op.is_required("operand_key") is True
    assert op.is_required("operand") is True
    assert op.is_required("operand_val") is True
    assert op.is_required("approximate_match") is False
    assert op.is_required("eps") is False
    assert op.default_of("approximate_match") is False
    assert op.default_of("eps") == 1e-9
    assert op.attributes["operand_key"].type == "str"
    assert op.attributes["operand_val"].type == "Any"
    assert op.attributes["eps"].type == "float"


def test_explain_shape(op: SelectOperator) -> None:
    attributes: Attributes = {"operand_key": "experience", "operand": ">=", "operand_val": 4}
    output = op.apply(INPUT_DATA, attributes)
    exp = op.explain(output, INPUT_DATA, attributes)
    assert exp["num_input_data"] == 1
    assert exp["num_input_records"] == 3
    assert exp["num_input_records_per_data"] == [3]
    assert exp["output"] == output

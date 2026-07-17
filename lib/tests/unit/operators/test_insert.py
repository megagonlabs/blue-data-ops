from __future__ import annotations

import pytest

from blue_data_ops.operators import Attributes, DataBundle, InsertOperator

R1, R2, R3 = {"id": 1}, {"id": 2}, {"id": 3}
X, Y, Z, W = {"id": 10}, {"id": 11}, {"id": 12}, {"id": 13}
BASE = [R1, R2, R3]
INPUT = [BASE]


@pytest.fixture
def op() -> InsertOperator:
    return InsertOperator()


FUNCTION_CASES: list[tuple[str, DataBundle, Attributes, DataBundle]] = [
    ("I1", [BASE, [X, Y]], {"insert_idx": -1}, [[R1, R2, R3, X, Y]]),
    ("I2", INPUT, {"insert_records": [X], "insert_idx": 0}, [[X, R1, R2, R3]]),
    ("I3", INPUT, {"insert_records": [X], "insert_idx": 1}, [[R1, X, R2, R3]]),
    ("I4", INPUT, {"insert_records": [X], "insert_idx": 3}, [[R1, R2, R3, X]]),
    ("I5", INPUT, {"insert_records": [X], "insert_idx": -2}, [[R1, R2, R3, X]]),
    ("I6", INPUT, {"insert_records": [X], "insert_idx": 4}, [[R1, R2, R3, X]]),
    (
        "I7",
        INPUT,
        {"insert_records": [X, Y, Z, W], "insert_idx": [2, -1, 0, 2]},
        [[Z, R1, R2, X, W, R3, Y]],
    ),
    (
        "I8",
        INPUT,
        {"insert_records": [X, Y], "insert_idx": [1]},
        [[R1, X, R2, R3, Y]],
    ),
    (
        "I9",
        INPUT,
        {"insert_records": [X], "insert_idx": [0, 2]},
        [[X, R1, R2, R3]],
    ),
    (
        "I10",
        INPUT,
        {"insert_records": [X, Y], "insert_idx": [1, 1]},
        [[R1, X, Y, R2, R3]],
    ),
    ("I11", INPUT, {}, [[R1, R2, R3]]),
    ("I12", [], {"insert_records": [X]}, []),
    ("I13", [[]], {"insert_records": [X]}, []),
    (
        "I14",
        [BASE, [X]],
        {"insert_records": [Y], "insert_idx": 0},
        [[X, R1, R2, R3]],
    ),
    (
        "I15",
        [BASE, []],
        {"insert_records": [Y], "insert_idx": 0},
        [[Y, R1, R2, R3]],
    ),
    (
        "I16",
        INPUT,
        {"insert_records": [X], "insert_idx": True},
        [[R1, X, R2, R3]],
    ),
]


@pytest.mark.parametrize(
    "case_id,input_data,attributes,expected",
    FUNCTION_CASES,
    ids=[case[0] for case in FUNCTION_CASES],
)
def test_apply(
    op: InsertOperator,
    case_id: str,
    input_data: DataBundle,
    attributes: Attributes,
    expected: DataBundle,
) -> None:
    assert op.apply(input_data, attributes) == expected


def test_apply_preserves_record_identity_and_copies_list(op: InsertOperator) -> None:
    result = op.apply([BASE, [X]], {"insert_idx": -1})[0]
    assert result is not BASE
    assert result[0] is R1
    assert result[-1] is X

    noop = op.apply(INPUT, {})[0]
    assert noop is not BASE
    assert all(actual is expected for actual, expected in zip(noop, BASE, strict=True))


@pytest.mark.parametrize(
    "attributes,error_type",
    [
        ({"insert_records": [X], "insert_idx": (0,)}, AttributeError),
        ({"insert_records": [X], "insert_idx": "0"}, AttributeError),
        ({"insert_records": (X,), "insert_idx": -1}, TypeError),
    ],
)
def test_direct_apply_preserves_type_errors(
    op: InsertOperator, attributes: Attributes, error_type: type[Exception]
) -> None:
    with pytest.raises(error_type):
        op.apply(INPUT, attributes)


VALIDATOR_CASES: list[tuple[str, Attributes, bool]] = [
    ("IV1", {}, True),
    ("IV2", {"insert_idx": -1}, True),
    ("IV3", {"insert_idx": 0}, True),
    ("IV4", {"insert_idx": [0, -1]}, True),
    ("IV5", {"insert_idx": -2}, False),
    ("IV6", {"insert_idx": [0, -2]}, False),
    ("IV7", {"insert_idx": (0,)}, True),
    ("IV8", {"insert_idx": "0"}, True),
    ("IV9", {"insert_idx": 0.0}, True),
    ("IV10-total-port", {"insert_idx": ["0"]}, False),
    ("IV11", {"insert_idx": [True]}, True),
    ("IV12", {"insert_idx": None}, False),
    ("IV13", {"insert_records": (X,)}, True),
    ("IV14", {"insert_records": ["bad"]}, False),
]


@pytest.mark.parametrize(
    "case_id,attributes,expected",
    VALIDATOR_CASES,
    ids=[case[0] for case in VALIDATOR_CASES],
)
def test_validate(op: InsertOperator, case_id: str, attributes: Attributes, expected: bool) -> None:
    assert op.validate(INPUT, attributes) is expected


def test_invocation_paths_and_documented_bug_surface(op: InsertOperator) -> None:
    assert op.invoke(INPUT, {"insert_records": [X], "insert_idx": 0}) == [[X, R1, R2, R3]]
    assert op.invoke(INPUT, {"insert_idx": -2}) is None
    assert op.invoke(INPUT, {"insert_idx": ["0"]}) is None
    with pytest.raises(AttributeError):
        op.invoke(INPUT, {"insert_records": [X], "insert_idx": (0,)})


def test_interface_contract(op: InsertOperator) -> None:
    assert (op.name, op.description) == (
        "insert",
        "Given input data, insert records by position(s)",
    )
    expected: dict[str, tuple[str, str, bool, object]] = {
        "insert_records": (
            "list[dict]",
            "List of records to insert into the first data source "
            "(optional if second data group provided)",
            False,
            [],
        ),
        "insert_idx": (
            "Union[int, list[int]]",
            "Position(s) to insert records (-1 for append, 0+ for specific position). "
            "If list, each element corresponds to position for each record",
            False,
            -1,
        ),
    }
    assert set(op.attributes) == set(expected)
    for name, interface in expected.items():
        spec = op.attributes[name]
        assert (spec.type, spec.description, op.is_required(name), spec.default) == interface


def test_explain_delegates_to_default(op: InsertOperator) -> None:
    attributes: Attributes = {"insert_records": [X], "insert_idx": 0}
    output = op.apply(INPUT, attributes)
    explanation = op.explain(output, INPUT, attributes)
    assert explanation["output"] == output
    assert explanation["num_input_records"] == 3
    assert explanation["num_output_records"] == 1

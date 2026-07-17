from __future__ import annotations

import pytest

from blue_data_ops.operators import Attributes, DataBundle, DeleteOperator

R1 = {"id": 1, "name": "A"}
R2 = {"id": 2, "name": "B"}
R3 = {"id": 3, "name": "C"}
BASE = [R1, R2, R3]
INPUT = [BASE]


@pytest.fixture
def op() -> DeleteOperator:
    return DeleteOperator()


FUNCTION_CASES: list[tuple[str, DataBundle, Attributes, DataBundle]] = [
    ("D1", INPUT, {"delete_idx": -1}, [[R1, R2]]),
    ("D2", INPUT, {"delete_idx": [1, -1, 0]}, [[]]),
    ("D3", [], {"delete_idx": -1}, []),
    ("D4", [[]], {"delete_idx": -1}, []),
    ("D5", INPUT, {}, [[R1, R2, R3]]),
    ("D6", INPUT, {"delete_idx": []}, [[R1, R2, R3]]),
    ("D7", INPUT, {"delete_idx": None}, [[R1, R2, R3]]),
    ("D8", INPUT, {"delete_idx": 0}, [[R2, R3]]),
    ("D9", INPUT, {"delete_idx": -3}, [[R2, R3]]),
    ("D10", INPUT, {"delete_idx": 3}, [[R1, R2, R3]]),
    ("D11", INPUT, {"delete_idx": -4}, [[R1, R2, R3]]),
    ("D12", INPUT, {"delete_idx": [1, 1, -1, 99, -99]}, [[R1]]),
    ("D13", [BASE, [{"id": 99}]], {"delete_idx": [1]}, [[R1, R3]]),
    ("D14", INPUT, {"delete_idx": True}, [[R1, R3]]),
    ("D15", INPUT, {"delete_idx": False}, [[R2, R3]]),
]


@pytest.mark.parametrize(
    "case_id,input_data,attributes,expected",
    FUNCTION_CASES,
    ids=[case[0] for case in FUNCTION_CASES],
)
def test_apply(
    op: DeleteOperator,
    case_id: str,
    input_data: DataBundle,
    attributes: Attributes,
    expected: DataBundle,
) -> None:
    assert op.apply(input_data, attributes) == expected


def test_apply_noop_and_out_of_range_identity(op: DeleteOperator) -> None:
    copied = op.apply(INPUT, {})[0]
    assert copied is not BASE
    assert all(actual is expected for actual, expected in zip(copied, BASE, strict=True))

    integer_out_of_range = op.apply(INPUT, {"delete_idx": 99})[0]
    assert integer_out_of_range is BASE

    list_out_of_range = op.apply(INPUT, {"delete_idx": [99]})[0]
    assert list_out_of_range is not BASE
    assert all(actual is expected for actual, expected in zip(list_out_of_range, BASE, strict=True))


VALIDATOR_CASES: list[tuple[str, Attributes, bool]] = [
    ("DV1", {}, True),
    ("DV2", {"delete_idx": 1}, True),
    ("DV3", {"delete_idx": -99}, True),
    ("DV4", {"delete_idx": [0, -1]}, True),
    ("DV5", {"delete_idx": [1, 1]}, True),
    ("DV6", {"delete_idx": None}, False),
    ("DV7", {"delete_idx": (0, 1)}, False),
    ("DV8", {"delete_idx": "1"}, False),
    ("DV9", {"delete_idx": 1.0}, False),
    ("DV10", {"delete_idx": ["1"]}, False),
    ("DV11", {"delete_idx": [True]}, True),
    ("DV12", {"delete_idx": {0: 1}}, False),
]


@pytest.mark.parametrize(
    "case_id,attributes,expected",
    VALIDATOR_CASES,
    ids=[case[0] for case in VALIDATOR_CASES],
)
def test_validate(op: DeleteOperator, case_id: str, attributes: Attributes, expected: bool) -> None:
    assert op.validate(INPUT, attributes) is expected


def test_invocation_paths(op: DeleteOperator) -> None:
    assert op.invoke(INPUT, {"delete_idx": -1}) == [[R1, R2]]
    assert op.invoke(INPUT, {"delete_idx": (0, 1)}) is None
    assert op.invoke(INPUT, {}) == [[R1, R2, R3]]


def test_interface_contract(op: DeleteOperator) -> None:
    assert op.name == "delete"
    assert op.description == (
        "Given input data, delete records from the first data source at specified positions"
    )
    spec = op.attributes["delete_idx"]
    assert (spec.type, spec.description, op.is_required("delete_idx"), spec.default) == (
        "Union[int, list[int]]",
        "Position(s) to delete records. Supports negative indexing "
        "(-1 = last, -2 = second to last, etc.)",
        False,
        [],
    )


def test_explain_delegates_to_default(op: DeleteOperator) -> None:
    attributes: Attributes = {"delete_idx": -1}
    output = op.apply(INPUT, attributes)
    explanation = op.explain(output, INPUT, attributes)
    assert explanation["output"] == output
    assert explanation["num_input_records"] == 3
    assert explanation["num_output_records"] == 1
    assert explanation["transformation_ratio"] == pytest.approx(1 / 3)

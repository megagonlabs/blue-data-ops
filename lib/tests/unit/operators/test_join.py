from __future__ import annotations

import pytest

from blue_data_ops.operators import Attributes, DataBundle, JoinOperator

LEFT = [
    {"id": 1, "name": "A", "shared": "L1"},
    {"id": 2, "name": "B", "shared": "L2"},
]
RIGHT = [
    {"id": 2, "dept": "D2", "shared": "R2"},
    {"id": 3, "dept": "D3", "shared": "R3"},
]
INPUT = [LEFT, RIGHT]
BASE: Attributes = {
    "join_on": [["id"], ["id"]],
    "join_type": "inner",
    "join_suffix": ["_l", "_r"],
    "keep_keys": "left",
}
MATCHED = {"id": 2, "name": "B", "shared_l": "L2", "dept": "D2", "shared_r": "R2"}


@pytest.fixture
def op() -> JoinOperator:
    return JoinOperator()


FUNCTION_CASES: list[tuple[str, DataBundle, Attributes, DataBundle]] = [
    ("J1", INPUT, BASE, [[MATCHED]]),
    (
        "J2",
        INPUT,
        {**BASE, "keep_keys": "both"},
        [
            [
                {
                    "id_l": 2,
                    "id_r": 2,
                    "name": "B",
                    "shared_l": "L2",
                    "dept": "D2",
                    "shared_r": "R2",
                }
            ]
        ],
    ),
    (
        "J3",
        INPUT,
        {**BASE, "join_type": "left"},
        [
            [
                {"id": 1, "name": "A", "shared_l": "L1", "dept": None, "shared_r": None},
                MATCHED,
            ]
        ],
    ),
    (
        "J4",
        INPUT,
        {**BASE, "join_type": "right"},
        [
            [
                MATCHED,
                {
                    "id": None,
                    "name": None,
                    "shared_l": None,
                    "dept": "D3",
                    "shared_r": "R3",
                },
            ]
        ],
    ),
    (
        "J5",
        INPUT,
        {**BASE, "join_type": "outer"},
        [
            [
                MATCHED,
                {"id": 1, "name": "A", "shared_l": "L1", "dept": None, "shared_r": None},
                {
                    "id": None,
                    "name": None,
                    "shared_l": None,
                    "dept": "D3",
                    "shared_r": "R3",
                },
            ]
        ],
    ),
    (
        "J6",
        [
            [
                {"tenant": "a", "code": 1, "value": "L1"},
                {"tenant": "a", "code": 2, "value": "L2"},
            ],
            [
                {"org": "a", "sku": 1, "value": "R1"},
                {"org": "b", "sku": 2, "value": "R2"},
            ],
        ],
        {
            "join_on": [["tenant", "code"], ["org", "sku"]],
            "join_type": "inner",
            "join_suffix": ["_left", "_right"],
            "keep_keys": "both",
        },
        [
            [
                {
                    "tenant": "a",
                    "code": 1,
                    "org": "a",
                    "sku": 1,
                    "value_left": "L1",
                    "value_right": "R1",
                }
            ]
        ],
    ),
    (
        "J7",
        [
            [{"id": 1, "left": "L1"}, {"id": 1, "left": "L2"}],
            [{"id": 1, "right": "R1"}, {"id": 1, "right": "R2"}],
        ],
        BASE,
        [
            [
                {"id": 1, "left": "L1", "right": "R1"},
                {"id": 1, "left": "L1", "right": "R2"},
                {"id": 1, "left": "L2", "right": "R1"},
                {"id": 1, "left": "L2", "right": "R2"},
            ]
        ],
    ),
    (
        "J8",
        [[{"left": "L"}], [{"right": "R"}]],
        BASE,
        [[{"left": "L", "right": "R"}]],
    ),
    (
        "J9",
        [
            [{"job_id": 1, "name": "A"}, {"job_id": 2, "name": "B"}],
            [{"job_id": 2, "location": "B"}, {"job_id": 1, "location": "A"}],
            [{"id": 1, "title": "T1"}, {"id": 2, "title": "T2"}],
        ],
        {
            "join_on": [["job_id"], ["job_id"], ["id"]],
            "join_type": "inner",
            "join_suffix": ["_employee", "_place", "_content"],
            "keep_keys": "left",
        },
        [
            [
                {"job_id": 1, "name": "A", "location": "A", "title": "T1"},
                {"job_id": 2, "name": "B", "location": "B", "title": "T2"},
            ]
        ],
    ),
    ("J10", [], {"join_on": []}, []),
    ("J11", [[]], {"join_on": [[]]}, []),
    ("J12", [[], []], BASE, [[]]),
    ("J13", INPUT, {**BASE, "join_on": [["id"]]}, []),
    ("J14", INPUT, {**BASE, "join_suffix": ["_same", "_same"]}, []),
    (
        "J15",
        INPUT,
        {"join_on": [["id"], ["id"]], "join_type": "inner", "keep_keys": "both"},
        [
            [
                {
                    "id_ds0": 2,
                    "id_ds1": 2,
                    "name": "B",
                    "shared_ds0": "L2",
                    "dept": "D2",
                    "shared_ds1": "R2",
                }
            ]
        ],
    ),
    ("J16", [[{"id": 1}], [{"id": 2}]], BASE, [[]]),
    (
        "J17",
        [[{"id": 1}], [{"id": 2}], [{"id": 1}]],
        {
            "join_on": [["id"], ["id"], ["id"]],
            "join_type": "inner",
            "join_suffix": ["_one", "_two", "_three"],
            "keep_keys": "left",
        },
        [[]],
    ),
    ("J18", INPUT, {**BASE, "join_type": "cross"}, [[]]),
]


@pytest.mark.parametrize(
    "case_id,input_data,attributes,expected",
    FUNCTION_CASES,
    ids=[case[0] for case in FUNCTION_CASES],
)
def test_apply(
    op: JoinOperator,
    case_id: str,
    input_data: DataBundle,
    attributes: Attributes,
    expected: DataBundle,
) -> None:
    assert op.apply(input_data, attributes) == expected


VALIDATOR_CASES: list[tuple[str, DataBundle, Attributes, bool]] = [
    ("JV1", INPUT, BASE, True),
    ("JV2", INPUT, {}, False),
    ("JV3", INPUT, {"join_on": []}, False),
    ("JV4", INPUT, {"join_on": ["id", "id"]}, False),
    ("JV5", INPUT, {"join_on": (["id"], ["id"])}, False),
    ("JV6", INPUT, {"join_on": [("id",), ("id",)]}, False),
    ("JV7", INPUT, {"join_on": [[b"id"], [b"id"]]}, False),
    ("JV8", INPUT, {"join_on": [["id"], []]}, False),
    (
        "JV9",
        INPUT,
        {"join_on": [["id"], ["id"]], "join_suffix": ["_same", "_same"]},
        True,
    ),
    ("JV10", INPUT, {"join_on": [["id"], ["id"]], "join_suffix": ["_one"]}, False),
    (
        "JV11",
        INPUT,
        {"join_on": [["id"], ["id"]], "join_suffix": ("_l", "_r")},
        False,
    ),
    ("JV12", INPUT, {"join_on": [["id"], ["id"]], "join_suffix": ()}, True),
    ("JV13", INPUT, {"join_on": [["id"], ["id"]], "keep_keys": "right"}, False),
    ("JV14", INPUT, {"join_on": [["id"], ["id"]], "join_type": "cross"}, False),
    ("JV15", INPUT, {"join_on": [["id"], ["id"]], "join_type": b"inner"}, False),
    ("JV16", [*INPUT, [{"id": 2}]], {"join_on": [["id"], ["id"]]}, True),
]


@pytest.mark.parametrize(
    "case_id,input_data,attributes,expected",
    VALIDATOR_CASES,
    ids=[case[0] for case in VALIDATOR_CASES],
)
def test_validate(
    op: JoinOperator,
    case_id: str,
    input_data: DataBundle,
    attributes: Attributes,
    expected: bool,
) -> None:
    assert op.validate(input_data, attributes) is expected


def test_invoke_valid(op: JoinOperator) -> None:
    assert op.invoke(INPUT, BASE) == [[MATCHED]]


def test_invoke_invalid_returns_none(op: JoinOperator) -> None:
    assert op.invoke(INPUT, {**BASE, "join_type": "cross"}) is None


def test_invoke_valid_duplicate_suffix_reaches_apply_guard(op: JoinOperator) -> None:
    attributes = {**BASE, "join_suffix": ["_same", "_same"]}
    assert op.invoke(INPUT, attributes) == []


def test_invoke_valid_source_count_mismatch_reaches_apply_guard(op: JoinOperator) -> None:
    assert op.invoke([*INPUT, [{"id": 2}]], BASE) == []


def test_interface_contract(op: JoinOperator) -> None:
    assert op.name == "join"
    assert op.description == "Joins multiple JSON array data sources using N-way join operations"
    expected: dict[str, tuple[str, str, bool, object]] = {
        "join_on": (
            "list[list[str]]",
            "List of join key lists for each data source",
            True,
            None,
        ),
        "join_type": (
            "str",
            "Type of join: 'inner', 'left', 'right', 'outer'",
            False,
            "inner",
        ),
        "join_suffix": ("list[str]", "Suffixes for non-key fields", False, []),
        "keep_keys": (
            "str",
            "'left' to keep left keys only, 'both' to keep both",
            False,
            "left",
        ),
    }
    assert set(op.attributes) == set(expected)
    for name, (type_name, description, required, default) in expected.items():
        spec = op.attributes[name]
        assert spec.type == type_name
        assert spec.description == description
        assert op.is_required(name) is required
        assert op.default_of(name) == default


def test_explain_delegates_to_default(op: JoinOperator) -> None:
    output = op.apply(INPUT, BASE)
    explanation = op.explain(output, INPUT, BASE)
    assert explanation == {
        "output": output,
        "num_input_data": 2,
        "num_input_records": 4,
        "num_input_records_per_data": [2, 2],
        "num_output_data": 1,
        "num_output_records": 1,
        "transformation_ratio": 0.25,
        "attributes": BASE,
    }

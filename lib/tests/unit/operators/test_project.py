from __future__ import annotations

import pytest

from blue_data_ops.operators import Attributes, DataBundle, ProjectOperator

R1 = {"job_id": 1, "name": "name A", "salary": 80000}
R2 = {"job_id": 2, "name": "name B", "salary": 95000}
R3 = {"job_id": 3, "name": "name C", "salary": 75000}
INPUT = [[R1, R2, R3]]


@pytest.fixture
def op() -> ProjectOperator:
    return ProjectOperator()


FUNCTION_CASES: list[tuple[str, DataBundle, Attributes, DataBundle]] = [
    (
        "F1",
        INPUT,
        {"kept_keys": ["job_id", "name"]},
        [
            [
                {"job_id": 1, "name": "name A"},
                {"job_id": 2, "name": "name B"},
                {"job_id": 3, "name": "name C"},
            ]
        ],
    ),
    (
        "F2",
        INPUT,
        {"kept_keys": ["job_id", "name"], "key_mapping": {"name": "employee_name"}},
        [
            [
                {"job_id": 1, "employee_name": "name A"},
                {"job_id": 2, "employee_name": "name B"},
                {"job_id": 3, "employee_name": "name C"},
            ]
        ],
    ),
    ("F3", [], {"kept_keys": ["job_id"]}, []),
    ("F4", [[]], {"kept_keys": ["job_id"]}, []),
    ("F5", INPUT, {"kept_keys": []}, []),
    ("F6", INPUT, {"kept_keys": ["missing"]}, [[{}, {}, {}]]),
    (
        "F7",
        INPUT,
        {"kept_keys": ["name", "missing"]},
        [[{"name": "name A"}, {"name": "name B"}, {"name": "name C"}]],
    ),
    (
        "F8",
        INPUT,
        {"kept_keys": ["job_id", "salary"], "key_mapping": {"salary": "job_id"}},
        [[{"job_id": 80000}, {"job_id": 95000}, {"job_id": 75000}]],
    ),
    (
        "F9",
        [INPUT[0], [{"job_id": 99, "name": "ignored"}]],
        {"kept_keys": ["job_id"]},
        [[{"job_id": 1}, {"job_id": 2}, {"job_id": 3}]],
    ),
    (
        "F10",
        INPUT,
        {"kept_keys": ["salary", "job_id"]},
        [
            [
                {"salary": 80000, "job_id": 1},
                {"salary": 95000, "job_id": 2},
                {"salary": 75000, "job_id": 3},
            ]
        ],
    ),
]


@pytest.mark.parametrize(
    "case_id,input_data,attributes,expected",
    FUNCTION_CASES,
    ids=[case[0] for case in FUNCTION_CASES],
)
def test_apply(
    op: ProjectOperator,
    case_id: str,
    input_data: DataBundle,
    attributes: Attributes,
    expected: DataBundle,
) -> None:
    assert op.apply(input_data, attributes) == expected


def test_apply_preserves_kept_key_order(op: ProjectOperator) -> None:
    output = op.apply(INPUT, {"kept_keys": ["salary", "job_id"]})
    assert [list(record) for record in output[0]] == [["salary", "job_id"]] * 3


VALIDATOR_CASES: list[tuple[str, Attributes, bool]] = [
    ("V1", {"kept_keys": ["job_id", "name"]}, True),
    ("V2", {}, False),
    ("V3", {"kept_keys": []}, True),
    (
        "V4",
        {"kept_keys": ["job_id"], "key_mapping": {"name": "employee_name"}},
        False,
    ),
    (
        "V5",
        {"kept_keys": ["job_id", "salary"], "key_mapping": {"salary": "job_id"}},
        False,
    ),
    ("V6", {"kept_keys": ["job_id", "job_id"]}, True),
    (
        "V7",
        {
            "kept_keys": ["job_id", "name"],
            "key_mapping": {"job_id": "name", "name": "job_id"},
        },
        True,
    ),
    ("V8", {"kept_keys": ("job_id", "name")}, True),
    ("V9", {"kept_keys": "job_id"}, False),
    ("V10", {"kept_keys": [1]}, False),
    ("V11", {"kept_keys": ["job_id"], "key_mapping": {"job_id": 1}}, False),
    ("V12", {"kept_keys": ["job_id"], "key_mapping": None}, False),
    ("V13", {"kept_keys": [b"job_id"]}, True),
    ("V14", {"kept_keys": ["job_id"], "key_mapping": {"job_id": b"id"}}, True),
    ("V15", {"kept_keys": [b"\xff"]}, False),
]


@pytest.mark.parametrize(
    "case_id,attributes,expected", VALIDATOR_CASES, ids=[case[0] for case in VALIDATOR_CASES]
)
def test_validate(
    op: ProjectOperator, case_id: str, attributes: Attributes, expected: bool
) -> None:
    assert op.validate(INPUT, attributes) is expected


def test_invoke_valid(op: ProjectOperator) -> None:
    assert op.invoke(INPUT, {"kept_keys": ["job_id"]}) == [
        [{"job_id": 1}, {"job_id": 2}, {"job_id": 3}]
    ]


def test_invoke_invalid_mapping_returns_none(op: ProjectOperator) -> None:
    attributes: Attributes = {
        "kept_keys": ["job_id", "salary"],
        "key_mapping": {"salary": "job_id"},
    }
    assert op.invoke(INPUT, attributes) is None


def test_invoke_empty_kept_keys_runs_apply(op: ProjectOperator) -> None:
    assert op.invoke(INPUT, {"kept_keys": []}) == []


def test_interface_contract(op: ProjectOperator) -> None:
    assert op.name == "project"
    assert op.description == (
        "Given an input data, return only a set of attributes for each data element (key-wise)"
    )
    expected: dict[str, tuple[str, str, bool, object]] = {
        "kept_keys": (
            "list[str]",
            "List of keys to keep in each record",
            True,
            None,
        ),
        "key_mapping": (
            "dict[str, str]",
            "Dictionary mapping old key names to new key names",
            False,
            {},
        ),
    }
    assert set(op.attributes) == set(expected)
    for name, (type_name, description, required, default) in expected.items():
        spec = op.attributes[name]
        assert spec.type == type_name
        assert spec.description == description
        assert op.is_required(name) is required
        assert op.default_of(name) == default


def test_explain_delegates_to_default(op: ProjectOperator) -> None:
    attributes: Attributes = {"kept_keys": ["job_id"]}
    output = op.apply(INPUT, attributes)
    explanation = op.explain(output, INPUT, attributes)
    assert explanation["output"] == output
    assert explanation["num_input_data"] == 1
    assert explanation["num_input_records"] == 3
    assert explanation["num_input_records_per_data"] == [3]
    assert explanation["num_output_data"] == 1
    assert explanation["num_output_records"] == 1
    assert explanation["transformation_ratio"] == pytest.approx(1 / 3)

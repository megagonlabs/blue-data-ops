"""Behavior and declarative-interface tests for the six aggregation operators.

Max deliberately returns a null result when its first participating value cannot be
coerced, avoiding an uninitialized comparison value.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from blue_data_ops.operators import (
    ArgmaxOperator,
    ArgminOperator,
    Attributes,
    AvgOperator,
    MaxOperator,
    MinOperator,
    Operator,
    SumOperator,
)

R1 = {"job_id": 1, "dept": "engineering", "salary": 80000}
R2 = {"job_id": 2, "dept": "sales", "salary": 95000}
R3 = {"job_id": 3, "dept": "engineering", "salary": 75000}
R4 = {"job_id": 4, "dept": "sales", "salary": "95000.0"}
R5 = {"job_id": 5, "dept": "engineering", "salary": None}
R6 = {"job_id": 6, "dept": "hr", "salary": "70000"}
R7 = {"job_id": 7, "dept": "hr", "salary": "N/A"}
D = [R1, R2, R3, R4, R5, R6, R7]
INPUT = [D]

OPS: dict[str, Operator] = {
    "argmax": ArgmaxOperator(),
    "argmin": ArgminOperator(),
    "max": MaxOperator(),
    "min": MinOperator(),
    "avg": AvgOperator(),
    "sum": SumOperator(),
}


# argmax / argmin
def test_argmax_records_tie() -> None:
    assert OPS["argmax"].apply(INPUT, {"argmax_key": "salary"}) == [[R2, R4]]


def test_argmax_indices() -> None:
    out = OPS["argmax"].apply(INPUT, {"argmax_key": "salary", "return_index": True})
    assert out == [[{"indices": [1, 3]}]]


def test_argmin_records() -> None:
    assert OPS["argmin"].apply(INPUT, {"argmin_key": "salary"}) == [[R6]]


def test_argmin_indices() -> None:
    out = OPS["argmin"].apply(INPUT, {"argmin_key": "salary", "return_index": True})
    assert out == [[{"indices": [5]}]]


# Symmetric coverage: every duplicated sibling branch is tested on BOTH ops, with a
# fixture whose SELECTED extremum ties for each op (one parameterized test).
TIE_CASES: dict[str, tuple[list[list[dict[str, object]]], list[dict[str, object]], list[int]]] = {
    # op: (data, expected tied records in input order, expected indices)
    "argmin": ([[{"k": 1}, {"k": "1.0"}, {"k": 2}]], [{"k": 1}, {"k": "1.0"}], [0, 1]),
    "argmax": ([[{"k": 2}, {"k": "2.0"}, {"k": 1}]], [{"k": 2}, {"k": "2.0"}], [0, 1]),
}


@pytest.mark.parametrize("op_name", ["argmax", "argmin"])
def test_tie_symmetric(op_name: str) -> None:
    data, tied_records, tied_indices = TIE_CASES[op_name]
    assert OPS[op_name].apply(data, {KEY_ATTR[op_name]: "k"}) == [tied_records]
    out = OPS[op_name].apply(data, {KEY_ATTR[op_name]: "k", "return_index": True})
    assert out == [[{"indices": tied_indices}]]


@pytest.mark.parametrize("op_name", ["argmax", "argmin"])
def test_arg_non_coercible_and_missing_key(op_name: str) -> None:
    assert OPS[op_name].apply(INPUT, {KEY_ATTR[op_name]: "dept"}) == [[]]
    assert OPS[op_name].apply(INPUT, {KEY_ATTR[op_name]: "nonexistent"}) == [[]]


@pytest.mark.parametrize("op_name", ["argmax", "argmin"])
@pytest.mark.parametrize("empty_input", [[], [[]]])
def test_arg_empty_input_guards(op_name: str, empty_input: list[list[dict[str, object]]]) -> None:
    # The empty result is [[]], unlike select's [] guard.
    assert OPS[op_name].apply(empty_input, {KEY_ATTR[op_name]: "salary"}) == [[]]
    out = OPS[op_name].apply(empty_input, {KEY_ATTR[op_name]: "salary", "return_index": True})
    assert out == [[{"indices": []}]]


# max / min
def test_max_int_wins_over_equal_float() -> None:
    out = OPS["max"].apply(INPUT, {"max_key": "salary"})
    assert out == [[{"max": 95000}]]
    value = out[0][0]["max"]
    assert type(value) is int  # 95000 (int) seen first; 95000.0 does not replace it


def test_min_coerced_str_int() -> None:
    out = OPS["min"].apply(INPUT, {"min_key": "salary"})
    assert out == [[{"min": 70000}]]
    assert type(out[0][0]["min"]) is int


def test_max_custom_output_key() -> None:
    assert OPS["max"].apply(INPUT, {"max_key": "salary", "output_key": "top"}) == [[{"top": 95000}]]


@pytest.mark.parametrize("op_name", ["max", "min"])
def test_scalar_extremum_non_coercible_none(op_name: str) -> None:
    assert OPS[op_name].apply(INPUT, {KEY_ATTR[op_name]: "dept"}) == [[{op_name: None}]]


@pytest.mark.parametrize("op_name", ["max", "min"])
@pytest.mark.parametrize("empty_input", [[], [[]]])
def test_scalar_extremum_empty_input_guards(
    op_name: str, empty_input: list[list[dict[str, object]]]
) -> None:
    assert OPS[op_name].apply(empty_input, {KEY_ATTR[op_name]: "salary"}) == [[{op_name: None}]]


def test_max_first_value_non_coercible_returns_null() -> None:
    # A non-coercible first value must not access uninitialized comparison state.
    assert OPS["max"].apply([[{"k": "N/A"}]], {"max_key": "k"}) == [[{"max": None}]]


# avg / sum
def test_sum() -> None:
    assert OPS["sum"].apply(INPUT, {"sum_key": "salary"}) == [[{"sum": 415000.0}]]


def test_avg() -> None:
    assert OPS["avg"].apply(INPUT, {"avg_key": "salary"}) == [[{"avg": 83000.0}]]


@pytest.mark.parametrize("op_name", ["avg", "sum"])
def test_aggregate_non_coercible_zero(op_name: str) -> None:
    assert OPS[op_name].apply(INPUT, {KEY_ATTR[op_name]: "dept"}) == [[{op_name: 0}]]


@pytest.mark.parametrize("op_name", ["avg", "sum"])
@pytest.mark.parametrize("empty_input", [[], [[]]])
def test_aggregate_empty_input_guards(
    op_name: str, empty_input: list[list[dict[str, object]]]
) -> None:
    assert OPS[op_name].apply(empty_input, {KEY_ATTR[op_name]: "salary"}) == [[{op_name: 0}]]


def test_sum_bools_are_ints() -> None:
    data = [[{"f": True}, {"f": False}, {"f": 3}]]
    assert OPS["sum"].apply(data, {"sum_key": "f"}) == [[{"sum": 4}]]


def test_coercion_is_general_not_str_only() -> None:
    # Integer-first conversion lets bytes coerce and truncates Decimal before summing.
    data = [[{"k": b"4"}, {"k": Decimal("3.9")}]]
    assert OPS["sum"].apply(data, {"sum_key": "k"}) == [[{"sum": 7}]]


def test_uncaught_coercion_exception_propagates() -> None:
    # Only conversion failures are caught; unrelated exceptions propagate.
    class Boom:
        def __int__(self) -> int:
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        OPS["sum"].apply([[{"k": Boom()}]], {"sum_key": "k"})


# Validators
KEY_ATTR = {
    "argmax": "argmax_key",
    "argmin": "argmin_key",
    "max": "max_key",
    "min": "min_key",
    "avg": "avg_key",
    "sum": "sum_key",
}


@pytest.mark.parametrize("op_name", sorted(OPS))
def test_validator_accepts_valid_attributes(op_name: str) -> None:
    assert OPS[op_name].validate(INPUT, {KEY_ATTR[op_name]: "salary"}) is True


@pytest.mark.parametrize("op_name", sorted(OPS))
def test_validator_rejects_missing_required_key(op_name: str) -> None:
    assert OPS[op_name].validate(INPUT, {}) is False


@pytest.mark.parametrize("op_name", sorted(OPS))
def test_validator_rejects_falsy_key(op_name: str) -> None:
    assert OPS[op_name].validate(INPUT, {KEY_ATTR[op_name]: ""}) is False


@pytest.mark.parametrize("op_name", sorted(OPS))
def test_validator_rejects_non_string_key(op_name: str) -> None:
    assert OPS[op_name].validate(INPUT, {KEY_ATTR[op_name]: 123}) is False


# Bool validation uses Pydantic's lax rules: coercible strings and numeric values are
# valid, while values such as "maybe" and 2 are not.
@pytest.mark.parametrize("op_name", ["argmax", "argmin"])
@pytest.mark.parametrize(
    "value,expected",
    [
        (True, True),
        ("yes", True),
        ("no", True),
        ("on", True),
        ("TRUE", True),
        (1, True),
        (0, True),
        (1.0, True),
        ("maybe", False),
        (2, False),
    ],
)
def test_return_index_uses_pydantic_lax_bool(op_name: str, value: object, expected: bool) -> None:
    attrs: Attributes = {KEY_ATTR[op_name]: "salary", "return_index": value}
    assert OPS[op_name].validate(INPUT, attrs) is expected


def test_truthy_string_return_index_takes_index_path() -> None:
    # "no" validates as a lax bool, but the function
    # reads the RAW value — any non-empty string is truthy, so "no" selects indices.
    out = OPS["argmax"].invoke(INPUT, {"argmax_key": "salary", "return_index": "no"})
    assert out == [[{"indices": [1, 3]}]]


@pytest.mark.parametrize("op_name", ["max", "min", "avg", "sum"])
def test_output_key_rejects_non_string_value(op_name: str) -> None:
    attrs: Attributes = {KEY_ATTR[op_name]: "salary", "output_key": 123}
    assert OPS[op_name].validate(INPUT, attrs) is False


# Invocation and interface contract
@pytest.mark.parametrize("op_name", sorted(OPS))
def test_invoke_invalid_returns_none(op_name: str) -> None:
    assert OPS[op_name].invoke(INPUT, {}) is None


def test_invoke_valid() -> None:
    assert OPS["sum"].invoke(INPUT, {"sum_key": "salary"}) == [[{"sum": 415000.0}]]


# Assert every public attribute field: type, description, required flag, and default.
RETURN_INDEX_DESC = (
    "If True, returns indices (0-based) instead of records, otherwise returns records"
)
EXPECTED_INTERFACE: dict[str, tuple[str, dict[str, tuple[str, str, bool, object]]]] = {
    # op: (description, {attr: (type, description, required, default)})
    "argmax": (
        "Given an input data, find the record(s) that contain the maximum value for a "
        "specified key.",
        {
            "argmax_key": ("str", "The key to find the maximum value for", True, None),
            "return_index": ("bool", RETURN_INDEX_DESC, False, False),
        },
    ),
    "argmin": (
        "Given an input data, find the record(s) that contain the minimum value for a "
        "specified key.",
        {
            "argmin_key": ("str", "The key to find the minimum value for", True, None),
            "return_index": ("bool", RETURN_INDEX_DESC, False, False),
        },
    ),
    "max": (
        "Given an input data, find the maximum value for a specified key across all records.",
        {
            "max_key": ("str", "The key to find the maximum value for", True, None),
            "output_key": ("str", "The key name for the result max value", False, "max"),
        },
    ),
    "min": (
        "Given an input data, find the minimum value for a specified key across all records.",
        {
            "min_key": ("str", "The key to find the minimum value for", True, None),
            "output_key": ("str", "The key name for the result min value", False, "min"),
        },
    ),
    "avg": (
        "Given an input data, calculate the average (arithmetic mean) of values for a specified "
        "key across all records.",
        {
            "avg_key": ("str", "The key to average the values for", True, None),
            "output_key": ("str", "The key name for the result average", False, "avg"),
        },
    ),
    "sum": (
        "Given an input data, calculate the sum of values for a specified key across all records.",
        {
            "sum_key": ("str", "The key to sum the values for", True, None),
            "output_key": ("str", "The key name for the result sum", False, "sum"),
        },
    ),
}


@pytest.mark.parametrize("op_name", sorted(OPS))
def test_interface_contract(op_name: str) -> None:
    op = OPS[op_name]
    description, attrs = EXPECTED_INTERFACE[op_name]
    assert op.name == op_name
    assert op.description == description
    assert set(op.attributes) == set(attrs)
    for attr_name, (attr_type, attr_desc, required, default) in attrs.items():
        spec = op.attributes[attr_name]
        assert spec.type == attr_type
        assert spec.description == attr_desc
        assert spec.required is required
        assert spec.default == default
        assert op.is_required(attr_name) is required
        assert op.default_of(attr_name) == default


@pytest.mark.parametrize("op_name", sorted(OPS))
def test_explain_delegates_to_default(op_name: str) -> None:
    op = OPS[op_name]
    attrs: Attributes = {KEY_ATTR[op_name]: "salary"}
    output = op.apply(INPUT, attrs)
    exp = op.explain(output, INPUT, attrs)
    assert exp["num_input_data"] == 1
    assert exp["num_input_records"] == 7
    assert exp["output"] == output

import copy
import sqlite3
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.unit.operators.outcome_measurement_support import (
    bind_case,
    compare_result,
    exact,
    load_fixture,
    validate_case,
)

CASES: list[dict[str, Any]] = load_fixture()["cases"]
BY_ID = {case["id"]: case for case in CASES}


def literal_result(case: dict[str, Any]) -> tuple[list[Any], dict[str, Any], SimpleNamespace]:
    expected = copy.deepcopy(case["expected"])
    return (
        expected["output_data"],
        expected["output_attributes"],
        SimpleNamespace(
            is_empty=expected["is_empty"],
            errors=[SimpleNamespace(**error) for error in expected["errors"]],
        ),
    )


def test_fixture_consistency() -> None:
    assert len(load_fixture()["cases"]) == 25


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_comparator_accepts_literal_result(case: dict[str, Any]) -> None:
    compare_result(case, literal_result(case))


@pytest.mark.parametrize(
    "case",
    [case for case in CASES if case["expected"]["output_attributes"]],
    ids=lambda case: case["id"],
)
@pytest.mark.parametrize("replacement", [False, True, 0.0, 1.0, 2.0, 3.0, 4.0])
def test_count_type_negative_control(case: dict[str, Any], replacement: bool | float) -> None:
    result = literal_result(case)
    key = next(iter(result[1]))
    result[1][key] = replacement
    with pytest.raises(AssertionError):
        compare_result(case, result)


def test_wrong_integer_count_negative_control() -> None:
    case = BY_ID["insert_table_empty_first_group_keeps_later_rows"]
    result = literal_result(case)
    result[1]["num_rows_insert"] = 0
    with pytest.raises(AssertionError):
        compare_result(case, result)


@pytest.mark.parametrize("value", [0, 1, None, "false"])
def test_is_empty_requires_bool(value: int | str | None) -> None:
    case = BY_ID["avg_no_usable_values_successful_empty"]
    result = literal_result(case)
    result[2].is_empty = value
    with pytest.raises(AssertionError):
        compare_result(case, result)


@pytest.mark.parametrize("value", [False, True, 0.01, float("nan"), float("inf")])
def test_average_rejects_bool_wrong_and_nonfinite_values(value: bool | float) -> None:
    case = BY_ID["avg_all_zero_values_are_data"]
    result = literal_result(case)
    result[0][0][0]["avg"] = value
    with pytest.raises(AssertionError):
        compare_result(case, result)


def test_tolerance_is_absolute_and_only_for_average() -> None:
    case = BY_ID["avg_all_zero_values_are_data"]
    result = literal_result(case)
    result[0][0][0]["avg"] = 5e-10
    compare_result(case, result)
    for actual in [2.0, 2 + 5e-10, True]:
        case = BY_ID["join_inner_match_on_id_default_suffix"]
        result = literal_result(case)
        result[0][0][0]["id"] = actual
        with pytest.raises(AssertionError):
            compare_result(case, result)


@pytest.mark.parametrize(
    "case_id", ["avg_no_usable_values_successful_empty", "avg_empty_first_group_successful_empty"]
)
def test_false_zero_average_negative_control(case_id: str) -> None:
    case = BY_ID[case_id]
    result = literal_result(case)
    result[0][0].append({"avg": 0.0})
    result[2].is_empty = False
    with pytest.raises(AssertionError):
        compare_result(case, result)


def test_later_insert_group_loss_negative_control() -> None:
    case = BY_ID["insert_table_empty_first_group_keeps_later_rows"]
    result = literal_result(case)
    result[0].pop()
    with pytest.raises(AssertionError):
        compare_result(case, result)


@pytest.mark.parametrize(
    "case",
    [case for case in CASES if case["operator_id"] == "join@3.0.0" and case["expected"]["errors"]],
    ids=lambda case: case["id"],
)
def test_silent_join_validation_negative_control(case: dict[str, Any]) -> None:
    result = literal_result(case)
    result[2].errors = []
    with pytest.raises(AssertionError):
        compare_result(case, result)


@pytest.mark.parametrize(
    "case_id",
    ["join_inner_match_on_id_default_suffix", "join_no_match_empty_suffix_list_keeps_defaults"],
)
def test_rejected_default_join_suffix_negative_control(case_id: str) -> None:
    case = BY_ID[case_id]
    result = literal_result(case)
    result[2].errors = [SimpleNamespace(code="INVALID_INPUT", stage="VALIDATE")]
    with pytest.raises(AssertionError):
        compare_result(case, result)


@pytest.mark.parametrize(
    "case",
    [case for case in CASES if not case["expected"]["output_attributes"]],
    ids=lambda case: case["id"],
)
@pytest.mark.parametrize("value", [-1, None, 1])
def test_failure_and_unknown_count_attributes_negative_control(
    case: dict[str, Any], value: int | None
) -> None:
    result = literal_result(case)
    result[1]["num_rows_insert"] = value
    with pytest.raises(AssertionError):
        compare_result(case, result)


@pytest.mark.parametrize(
    "malformed", [[], [[{"id": 2, "extra": 0}]], [[{"id": 2}], []], (({"id": 2},),)]
)
def test_exact_data_structure_negative_control(malformed: Any) -> None:
    case = BY_ID["join_inner_match_on_id_default_suffix"]
    result = literal_result(case)
    with pytest.raises(AssertionError):
        compare_result(case, (malformed, result[1], result[2]))


def test_error_pair_and_partial_error_matching() -> None:
    case = BY_ID["avg_absent_avg_key_rejected"]
    result = literal_result(case)
    result[2].errors[0].message = "description is not matched"
    compare_result(case, result)
    result[2].errors[0].stage = "EXECUTE"
    with pytest.raises(AssertionError):
        compare_result(case, result)


@pytest.mark.parametrize(
    "field,value",
    [
        ("setup", {"backend": "other"}),
        ("backend", {"double": "unknown"}),
        ("typed_input", [{"path": "arbitrary", "python_type": "eval"}]),
        ("operator_id", "other@3.0.0"),
        ("unknown_descriptor", {}),
    ],
)
def test_unknown_descriptors_rejected(field: str, value: Any) -> None:
    case = copy.deepcopy(BY_ID["insert_table_ordinary_rows_sqlite"])
    case[field] = value
    with pytest.raises(AssertionError):
        validate_case(case)


def test_decimal_transform_is_narrow_and_does_not_mutate_fixture(tmp_path: Path) -> None:
    case = BY_ID["avg_decimal_typed_input_discriminates_int_then_float"]
    with bind_case(case, tmp_path) as call:
        value = call.input_data[0][0]["score"]
        assert type(value) is Decimal and value == Decimal("3.9")
        assert int(value) == 3 and float(value) == 3.9
    assert case["input_data"][0][0]["score"] == "3.9"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_each_case_binding_without_operator(case: dict[str, Any], tmp_path: Path) -> None:
    original = copy.deepcopy(case)
    with bind_case(case, tmp_path) as call:
        assert call.input_data is not case["input_data"]
        assert call.attributes is not case["input_attributes"]
        exact(call.observation.attempts, 0)
        if call.database is not None:
            exact(call.rows_after(), [])
    exact(case, original)


@pytest.mark.parametrize("unknown", [False, True])
def test_sqlite_adapter_real_rows_batches_and_rowcount(tmp_path: Path, unknown: bool) -> None:
    case_id = (
        "insert_table_unknown_backend_count_omits_key"
        if unknown
        else "insert_table_ordinary_rows_sqlite"
    )
    case = BY_ID[case_id]
    with bind_case(case, tmp_path) as call:
        source = call.properties["data_registry"].connect_source("sqlite_fixture")
        connection = source._db_connect("fixture")
        statements: list[str] = []
        connection.set_trace_callback(statements.append)
        cursor = connection.cursor()
        cursor.executemany("INSERT INTO sample VALUES (?, ?)", [(1, 10), (2, 20)])
        assert cursor.rowcount == (-1 if unknown else 2)
        assert cursor.raw.rowcount == 2
        assert connection.total_changes == 2
        connection.commit()
        source._db_disconnect(connection)
        assert call.observation.attempts == 1
        assert call.observation.successful_batches == call.observation.commits == 1
        assert sum(sql.startswith("INSERT") for sql in statements) == 2
        call.compare_persistence(case)


def test_sqlite_connection_shortcut_is_observed(tmp_path: Path) -> None:
    case = BY_ID["insert_table_unknown_backend_count_omits_key"]
    with bind_case(case, tmp_path) as call:
        connection = (
            call.properties["data_registry"].connect_source("sqlite_fixture")._db_connect("fixture")
        )
        cursor = connection.executemany("INSERT INTO sample VALUES (?, ?)", [(1, 10), (2, 20)])
        assert cursor.rowcount == -1 and cursor.raw.rowcount == 2
        connection.commit()
        call.compare_persistence(case)


def test_sqlite_adapter_failed_batch_entry_and_reopened_partial_commit(tmp_path: Path) -> None:
    case = BY_ID["insert_table_write_failure_after_first_batch_commit"]
    with bind_case(case, tmp_path) as call:
        source = call.properties["data_registry"].connect_source("sqlite_fixture")
        first = source._db_connect("fixture")
        first.cursor().executemany("INSERT INTO sample VALUES (?, ?)", [(1, 10)])
        first.commit()
        source._db_disconnect(first)
        second = source._db_connect("fixture")
        with pytest.raises(sqlite3.IntegrityError):
            second.cursor().executemany("INSERT INTO sample VALUES (?, ?)", [(1, 20)])
        assert call.observation.attempts == 2
        assert call.observation.successful_batches == call.observation.commits == 1
        call.compare_persistence(case)
        source._db_disconnect(second)


def test_absent_registry_and_zero_write_observation(tmp_path: Path) -> None:
    from blue_data_ops.data import resolve_registry

    case = BY_ID["insert_table_empty_input_missing_registry_execution_failed"]
    with bind_case(case, tmp_path) as call:
        exact(call.properties, {})
        assert resolve_registry(call.properties) is None
        assert call.database is None
        call.compare_persistence(case)


def test_sqlite_persistence_negative_control_and_isolation(tmp_path: Path) -> None:
    case = BY_ID["insert_table_empty_first_group_keeps_later_rows"]
    with bind_case(case, tmp_path / "first") as first:
        with pytest.raises(AssertionError):
            first.compare_persistence(case)
        with bind_case(case, tmp_path / "second") as second:
            assert first.properties["data_registry"] is not second.properties["data_registry"]
            assert first.database != second.database
            exact(first.rows_after(), [])
            exact(second.rows_after(), [])

from __future__ import annotations

import copy
import json
import math
import sqlite3
from collections.abc import Callable, Generator, Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, Self, cast

if TYPE_CHECKING:
    from blue_data_ops.operators import Operator

    class ResultErrors(Protocol):
        errors: list[Any]


FIXTURE = Path(__file__).parents[2] / "fixtures" / "operator_outcome_updates.json"
OPERATOR_IDS = {"avg@3.0.0", "insert_table@3.0.0", "join@3.0.0"}
SQLITE_SETUP: dict[str, Any] = {
    "backend": "sqlite",
    "registry_source": "sqlite_fixture",
    "schema_sql": "CREATE TABLE sample (id INTEGER PRIMARY KEY, value INTEGER)",
    "preexisting_rows": [],
}
ABSENT_SETUP: dict[str, Any] = {
    "backend": "sqlite",
    "registry_source": None,
    "registry_state": "absent",
    "note": "properties is empty: no registry object and no registry construction keys",
}
UNKNOWN_COUNT = {"double": "sqlite_cursor_rowcount_unknown", "rowcount": -1}
DECIMAL_INPUT = [
    {
        "path": "input_data[0][0].score",
        "python_type": "decimal.Decimal",
        "constructor_arg": "3.9",
    }
]


def exact(
    actual: Any,
    expected: Any,
    path: tuple[str | int, ...] = (),
    average_path: tuple[str | int, ...] | None = None,
) -> None:
    if path == average_path:
        assert type(actual) in (int, float), f"{path}: average must be numeric, not bool"
        assert math.isclose(actual, expected, rel_tol=0, abs_tol=1e-9), (path, actual, expected)
        return
    assert type(actual) is type(expected), (
        f"{path}: {type(actual).__name__} != {type(expected).__name__}"
    )
    if type(expected) is dict:
        assert actual.keys() == cast(dict[str, Any], expected).keys(), f"{path}: keys differ"
        for key, value in cast(dict[str, Any], expected).items():
            exact(actual[key], value, (*path, key), average_path)
    elif type(expected) is list:
        assert len(actual) == len(cast(list[Any], expected)), f"{path}: list length differs"
        for index, value in enumerate(cast(list[Any], expected)):
            exact(actual[index], value, (*path, index), average_path)
    else:
        assert actual == expected, (path, actual, expected)


def validate_case(case: dict[str, Any]) -> None:
    required = {"id", "operator_id", "purpose", "input_data", "input_attributes", "expected"}
    assert required <= case.keys()
    assert case.keys() <= required | {"setup", "backend", "typed_input", "persistence"}
    assert type(case["id"]) is str and case["id"]
    operator_id = case["operator_id"]
    assert operator_id in OPERATOR_IDS, f"unknown operator descriptor: {operator_id}"
    assert type(case["input_data"]) is list
    assert type(case["input_attributes"]) is dict
    if "typed_input" in case:
        exact(case["typed_input"], DECIMAL_INPUT)
        assert case["id"] == "avg_decimal_typed_input_discriminates_int_then_float"
        exact(case["input_data"], [[{"score": "3.9"}]])
    if operator_id == "insert_table@3.0.0":
        assert "setup" in case and "persistence" in case
        absent = case["setup"].get("registry_state") == "absent"
        exact(case["setup"], ABSENT_SETUP if absent else SQLITE_SETUP)
        attrs = cast(dict[str, Any], case["input_attributes"])
        assert attrs["source"] == ("unregistered_source" if absent else "sqlite_fixture")
        assert attrs["database"] == "fixture" and attrs["table"] == "sample"
        if "backend" in case:
            assert not absent
            exact(case["backend"], UNKNOWN_COUNT)
        persistence = case["persistence"]
        assert persistence.keys() <= {
            "rows_after",
            "write_batches",
            "write_batches_attempted",
            "note",
        }
        batch_keys = {"write_batches", "write_batches_attempted"} & persistence.keys()
        assert len(batch_keys) == 1
        for key in batch_keys:
            assert type(persistence[key]) is int and persistence[key] >= 0
        if absent:
            assert "rows_after" not in persistence and "backend" not in case
        else:
            assert "rows_after" in persistence
            assert type(persistence["rows_after"]) is list
            for row in persistence["rows_after"]:
                assert type(row) is dict and row.keys() == {"id", "value"}
    else:
        assert not ({"setup", "backend", "persistence"} & case.keys())
    expected = case["expected"]
    assert expected.keys() == {"output_data", "output_attributes", "is_empty", "errors"}
    assert type(expected["is_empty"]) is bool and type(expected["errors"]) is list
    assert type(expected["output_data"]) is list and expected["output_data"]
    for group in expected["output_data"]:
        assert type(group) is list
        assert all(type(row) is dict for row in cast(list[Any], group))
    attributes: dict[str, Any] = expected["output_attributes"]
    assert type(attributes) is dict
    assert attributes.keys() <= {"num_values_used", "num_rows_insert"}
    for value in attributes.values():
        assert type(value) is int and value >= 0
    if expected["errors"]:
        exact(expected["output_data"], [[]])
        exact(attributes, {})
        assert expected["is_empty"] is False
        for error in expected["errors"]:
            assert error in [
                {"code": "INVALID_INPUT", "stage": "VALIDATE"},
                {"code": "EXECUTION_FAILED", "stage": "EXECUTE"},
            ]
    else:
        assert expected["is_empty"] is (not any(expected["output_data"]))


def load_fixture(path: Path = FIXTURE) -> dict[str, Any]:
    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            assert key not in result, f"duplicate JSON key: {key}"
            result[key] = value
        return result

    fixture: dict[str, Any] = json.loads(path.read_text(), object_pairs_hook=unique_keys)
    assert fixture.keys() == {
        "schema_version",
        "operator_version",
        "baseline_core_version",
        "cases",
        "runner_requirements",
        "limitations",
    }
    exact(fixture["schema_version"], 1)
    assert fixture["operator_version"] == "3.0.0"
    assert fixture["baseline_core_version"] == "2.8.0"
    cases: list[dict[str, Any]] = fixture["cases"]
    assert type(cases) is list and len(cases) == 25
    assert len({case["id"] for case in cases}) == 25
    for operator_id, count in [("avg@3.0.0", 9), ("insert_table@3.0.0", 9), ("join@3.0.0", 7)]:
        assert sum(case["operator_id"] == operator_id for case in cases) == count
    for case in cases:
        validate_case(case)
    return fixture


def compare_result(case: dict[str, Any], result: tuple[Any, ...]) -> None:
    assert type(result) is tuple and len(result) == 3
    data, attributes, meta = result
    expected = case["expected"]
    average_path: tuple[str | int, ...] | None = None
    if case["operator_id"] == "avg@3.0.0" and any(expected["output_data"]):
        average_path = (0, 0, case["input_attributes"].get("output_key", "avg"))
    exact(data, expected["output_data"], average_path=average_path)
    exact(attributes, expected["output_attributes"])
    exact(meta.is_empty, expected["is_empty"])
    assert type(meta.errors) is list
    if not expected["errors"]:
        exact(cast("ResultErrors", meta).errors, [])
    else:
        for wanted in expected["errors"]:
            assert any(
                getattr(error.code, "value", error.code) == wanted["code"]
                and getattr(error.stage, "value", error.stage) == wanted["stage"]
                for error in cast("ResultErrors", meta).errors
            ), f"missing error pair: {wanted}"


@dataclass
class Observation:
    attempts: int = 0
    successful_batches: int = 0
    commits: int = 0
    connections: list[sqlite3.Connection] = field(
        default_factory=cast(Callable[[], list[sqlite3.Connection]], list)
    )


class ObservedCursor:
    def __init__(self, raw: sqlite3.Cursor, observation: Observation, unknown_count: bool) -> None:
        self.raw = raw
        self.observation = observation
        self.unknown_count = unknown_count

    @property
    def rowcount(self) -> int:
        return -1 if self.unknown_count else self.raw.rowcount

    def executemany(self, query: str, rows: Iterable[Sequence[Any] | Mapping[str, Any]]) -> Self:
        self.observation.attempts += 1
        self.raw.executemany(query, rows)
        self.observation.successful_batches += 1
        return self

    def execute(self, *args: Any, **kwargs: Any) -> Self:
        self.raw.execute(*args, **kwargs)
        return self

    def __getattr__(self, name: str) -> Any:
        return getattr(self.raw, name)


class ObservedConnection:
    def __init__(
        self, raw: sqlite3.Connection, observation: Observation, unknown_count: bool
    ) -> None:
        self.raw = raw
        self.observation = observation
        self.unknown_count = unknown_count

    def cursor(self, *args: Any, **kwargs: Any) -> ObservedCursor:
        return ObservedCursor(
            self.raw.cursor(*args, **kwargs), self.observation, self.unknown_count
        )

    def executemany(
        self, query: str, rows: Iterable[Sequence[Any] | Mapping[str, Any]]
    ) -> ObservedCursor:
        return self.cursor().executemany(query, rows)

    def execute(self, *args: Any, **kwargs: Any) -> ObservedCursor:
        return self.cursor().execute(*args, **kwargs)

    def commit(self) -> None:
        result = self.raw.commit()
        self.observation.commits += 1
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self.raw, name)


@dataclass
class BoundCall:
    input_data: list[Any]
    attributes: dict[str, Any]
    properties: dict[str, Any]
    observation: Observation
    database: Path | None = None

    def rows_after(self) -> list[dict[str, Any]]:
        assert self.database is not None
        connection = sqlite3.connect(f"{self.database.as_uri()}?mode=ro", uri=True)
        try:
            rows = connection.execute("SELECT id, value FROM sample ORDER BY id").fetchall()
            return [{"id": row[0], "value": row[1]} for row in rows]
        finally:
            connection.close()

    def compare_persistence(self, case: dict[str, Any]) -> None:
        persistence = case.get("persistence")
        if persistence is None:
            return
        if "rows_after" in persistence:
            exact(self.rows_after(), persistence["rows_after"])
        key = (
            "write_batches_attempted"
            if "write_batches_attempted" in persistence
            else "write_batches"
        )
        exact(self.observation.attempts, persistence[key])


@contextmanager
def bind_case(case: dict[str, Any], directory: Path) -> Generator[BoundCall, None, None]:
    validate_case(case)
    data = copy.deepcopy(case["input_data"])
    attributes = copy.deepcopy(case["input_attributes"])
    if "typed_input" in case:
        data[0][0]["score"] = Decimal(case["typed_input"][0]["constructor_arg"])
    bound = BoundCall(data, attributes, {}, Observation())
    setup = case.get("setup")
    if setup == SQLITE_SETUP:
        from blue_data.registry.data_registry import DataRegistry
        from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource

        from blue_data_ops.data import RegistrySeam

        directory.mkdir(parents=True, exist_ok=True)
        bound.database = directory.resolve() / "fixture.db"
        assert not bound.database.exists(), "SQLite case directory must be fresh"
        source = SQLiteDBSource(
            "sqlite_fixture",
            properties={
                "connection": {"protocol": "sqlite", "database_directory": str(directory)},
            },
        )
        seam = RegistrySeam(DataRegistry(name=case["id"], rebuild=True))
        seam.register_source(source)
        connection = cast(Callable[[str], sqlite3.Connection], getattr(source, "_db_connect"))(
            "fixture"
        )
        try:
            connection.execute(cast(dict[str, Any], setup)["schema_sql"])
            connection.commit()
        finally:
            cast(Callable[[sqlite3.Connection], None], getattr(source, "_db_disconnect"))(
                connection
            )
        real_connect = cast(Callable[[str], sqlite3.Connection], getattr(source, "_db_connect"))

        def observed_connect(database: str) -> ObservedConnection:
            raw = real_connect(database)
            bound.observation.connections.append(raw)
            return ObservedConnection(raw, bound.observation, "backend" in case)

        setattr(source, "_db_connect", observed_connect)
        bound.properties["data_registry"] = seam
    try:
        yield bound
    finally:
        for connection in bound.observation.connections:
            connection.close()


def resolve_operator(case: dict[str, Any]) -> Operator:
    from blue_data_ops.operators.registry import ResolveError, versioned_registry

    try:
        operator = versioned_registry().resolve(case["operator_id"])
    except ResolveError as error:
        raise AssertionError(f"required implementation absent: {case['operator_id']}") from error
    assert operator.operator_id == case["operator_id"]
    return operator

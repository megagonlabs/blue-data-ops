from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from blue_data.registry.data_registry import DataRegistry  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.sql.sqlite.sqlite_sql_source import (  # pyright: ignore[reportMissingTypeStubs]
    SQLiteDBSource,
)

from blue_data_ops.data import RegistrySeam
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.registry import default_registry, versioned_registry
from blue_data_ops.operators.types import Attributes, DataBundle


@pytest.fixture(params=["versioned", "override"])
def resolve(request: pytest.FixtureRequest) -> Callable[[str], Operator]:
    def get(name: str) -> Operator:
        registry = (
            versioned_registry()
            if request.param == "versioned"
            else default_registry(**{name: "3.0.0"})
        )
        return registry.resolve(f"{name}@3.0.0")

    return get


def sqlite_registry(directory: Path) -> tuple[RegistrySeam, SQLiteDBSource]:
    source = SQLiteDBSource(
        "local",
        properties={
            "connection": {"protocol": "sqlite", "database_directory": str(directory)},
        },
    )
    registry = RegistrySeam(DataRegistry(name="outcomes", rebuild=True))
    registry.register_source(source)
    source.create_database("sample")
    connection = cast(sqlite3.Connection, getattr(source, "_db_connect")("sample"))
    try:
        connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value INTEGER)")
        connection.commit()
    finally:
        cast(Callable[[sqlite3.Connection], None], getattr(source, "_db_disconnect"))(connection)
    return registry, source


def persisted_rows(directory: Path) -> list[tuple[int, int]]:
    connection = sqlite3.connect(f"{(directory / 'sample.db').as_uri()}?mode=ro", uri=True)
    try:
        return connection.execute("SELECT id, value FROM items ORDER BY id").fetchall()
    finally:
        connection.close()


def test_avg_coercion_and_custom_key(resolve: Callable[[str], Operator]) -> None:
    operator = resolve("avg")
    data, attributes, meta = operator.run(
        [[{"x": value} for value in [True, False, Decimal("8.9"), b"3", "2.5", None, "bad"]]],
        {"avg_key": "x", "output_key": "mean"},
    )
    assert data == [[{"mean": 2.9}]]
    assert attributes == {"num_values_used": 5}
    assert not meta.errors and not meta.is_empty


@pytest.mark.parametrize("value", [float("nan"), "nan"])
def test_avg_nan_is_an_accepted_contributor(
    resolve: Callable[[str], Operator], value: float | str
) -> None:
    data, attributes, meta = resolve("avg").run([[{"x": value}, {"x": 8}]], {"avg_key": "x"})
    assert math.isnan(data[0][0]["avg"])
    assert attributes == {"num_values_used": 2}
    assert not meta.errors and not meta.is_empty


@pytest.mark.parametrize("suffixes", [None, []])
def test_join_generated_suffixes(
    resolve: Callable[[str], Operator], suffixes: list[str] | None
) -> None:
    settings: Attributes = {"join_on": [["id"], ["id"]]}
    if suffixes is not None:
        settings["join_suffix"] = suffixes
    data, attributes, meta = resolve("join").run(
        [[{"id": 7, "value": 4}], [{"id": 7, "value": 6}]], settings
    )
    assert data == [[{"id": 7, "value_ds0": 4, "value_ds1": 6}]]
    assert attributes == {} and not meta.errors
    assert settings == {
        "join_on": [["id"], ["id"]],
        **({} if suffixes is None else {"join_suffix": []}),
    }


@pytest.mark.parametrize("groups", [[[], []], [[], [], []]])
def test_join_rejects_duplicate_suffixes_before_empty_execution(
    resolve: Callable[[str], Operator], groups: DataBundle
) -> None:
    data, attributes, meta = resolve("join").run(
        groups,
        {
            "join_on": [["id"] for _ in groups],
            "join_suffix": ["_same"] * len(groups),
        },
    )
    assert data == [[]] and attributes == {} and meta.is_empty is False
    assert [(error.code.value, error.stage.value) for error in meta.errors] == [
        ("INVALID_INPUT", "VALIDATE")
    ]


def test_insert_reordered_columns_across_groups(
    resolve: Callable[[str], Operator], tmp_path: Path
) -> None:
    registry, _source = sqlite_registry(tmp_path)
    rows = [
        [],
        [{"id": 2, "value": 12}, {"value": 30, "id": 3}],
        [],
        [{"value": 5, "id": 4}],
    ]
    data, attributes, meta = resolve("insert_table").run(
        rows,
        {
            "source": "local",
            "database": "sample",
            "table": "items",
            "batch_size": 1,
        },
        {"data_registry": registry},
    )
    assert data == rows and attributes == {"num_rows_insert": 3}
    assert not meta.errors
    assert persisted_rows(tmp_path) == [(2, 12), (3, 30), (4, 5)]


@pytest.mark.parametrize("counts", [[-1, 1], [1, None], [1, RuntimeError()], [True, 1], [1, 1.0]])
def test_insert_unknown_count_does_not_hide_success(
    resolve: Callable[[str], Operator],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    counts: list[int | float | None | Exception],
) -> None:
    registry, source = sqlite_registry(tmp_path)
    real_connect = cast(Callable[[str], sqlite3.Connection], getattr(source, "_db_connect"))
    observed = iter(counts)

    class Cursor:
        def __init__(self, raw: sqlite3.Cursor) -> None:
            self.raw = raw

        @property
        def rowcount(self) -> int | float | None:
            count = next(observed)
            if isinstance(count, Exception):
                raise count
            return count

        def executemany(self, query: str, rows: Iterable[Sequence[Any]]) -> sqlite3.Cursor:
            return self.raw.executemany(query, rows)

    class Connection:
        def __init__(self, raw: sqlite3.Connection) -> None:
            self.raw = raw

        def cursor(self) -> Cursor:
            return Cursor(self.raw.cursor())

        def __getattr__(self, name: str) -> Any:
            return getattr(self.raw, name)

    def connection_factory(database: str) -> Connection:
        return Connection(real_connect(database))

    monkeypatch.setattr(source, "_db_connect", connection_factory)
    rows = [[{"id": 1, "value": 4}], [{"value": 9, "id": 2}]]
    data, attributes, meta = resolve("insert_table").run(
        rows,
        {
            "source": "local",
            "database": "sample",
            "table": "items",
        },
        {"data_registry": registry},
    )
    assert data == rows and attributes == {} and not meta.errors
    assert persisted_rows(tmp_path) == [(1, 4), (2, 9)]


def test_insert_later_group_failure_has_no_receipt(
    resolve: Callable[[str], Operator], tmp_path: Path
) -> None:
    registry, _source = sqlite_registry(tmp_path)
    data, attributes, meta = resolve("insert_table").run(
        [[{"id": 1, "value": 4}], [{"value": 9, "id": 1}]],
        {"source": "local", "database": "sample", "table": "items"},
        {"data_registry": registry},
    )
    assert data == [[]] and attributes == {} and meta.is_empty is False
    assert [(error.code.value, error.stage.value) for error in meta.errors] == [
        ("EXECUTION_FAILED", "EXECUTE")
    ]
    assert persisted_rows(tmp_path) == [(1, 4)]


def test_sequential_result_attributes_are_independent(
    resolve: Callable[[str], Operator],
) -> None:
    operator = resolve("avg")
    first = operator.run([[{"x": 6}]], {"avg_key": "x"})
    first[1]["num_values_used"] = 100
    first[2].traces["caller"] = True
    second = operator.run([[]], {"avg_key": "x"})
    assert second[0] == [[]] and second[1] == {"num_values_used": 0}
    assert second[2].is_empty and not second[2].errors
    assert "caller" not in second[2].traces
    rejected = operator.run([[{"x": 3}]], {})
    assert rejected[1] == {} and rejected[2].errors

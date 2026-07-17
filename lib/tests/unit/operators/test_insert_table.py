"""Behavior, SQL-boundary, and SQLite integration tests for `insert_table`."""

# blue-data ships no py.typed; this file exercises the private SQL protocol
# (_db_connect/_db_disconnect) — that protocol IS the boundary under test:
# pyright: reportMissingTypeStubs=false
# pyright: reportPrivateUsage=false

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

blue_data = pytest.importorskip("blue_data")

from blue_data.registry.data_registry import DataRegistry  # noqa: E402
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource  # noqa: E402

from blue_data_ops.data import RegistrySeam  # noqa: E402
from blue_data_ops.operators.insert_table_operator import InsertTableOperator  # noqa: E402
from tests.doubles.data import RegistrySeamDouble, SQLSourceDouble  # noqa: E402

ROWS = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}, {"a": 3, "b": "z"}]
MINIMAL: dict[str, Any] = {"source": "src", "database": "db", "table": "t"}


class _RecordingSeam(RegistrySeamDouble, RegistrySeam):
    """The recording double, typed as a RegistrySeam so injection resolves it."""


@pytest.fixture
def op() -> InsertTableOperator:
    return InsertTableOperator()


def _seam_with_sql_source() -> tuple[_RecordingSeam, SQLSourceDouble]:
    seam = _RecordingSeam()
    sql = SQLSourceDouble("src")
    seam.sources["src"] = sql
    return seam, sql


def _props(seam: RegistrySeam) -> dict[str, Any]:
    return {"data_registry": seam}


# --- No registry: pass-through with zero calls ---
def test_no_registry_passes_through(op: InsertTableOperator) -> None:
    payload = [list(ROWS)]
    out = op.apply(payload, dict(MINIMAL), None)
    assert out is payload  # identity-preserving pass-through


# --- Empty guards inspect the first group only ---
@pytest.mark.parametrize("empty_input", [[], [[]]])
def test_empty_input_guard(
    op: InsertTableOperator, empty_input: list[list[dict[str, Any]]]
) -> None:
    seam, sql = _seam_with_sql_source()
    assert op.apply(empty_input, dict(MINIMAL), _props(seam)) == [[]]
    assert sql.connections == {}  # nothing inserted


def test_empty_first_group_aborts_even_with_later_rows(op: InsertTableOperator) -> None:
    # Only the first group controls the empty-input guard.
    seam, sql = _seam_with_sql_source()
    out = op.apply([[], list(ROWS)], dict(MINIMAL), _props(seam))
    assert out == [[]]
    assert sql.connections == {}


def test_later_empty_groups_are_skipped(op: InsertTableOperator) -> None:
    seam, sql = _seam_with_sql_source()
    out = op.apply([list(ROWS), []], dict(MINIMAL), _props(seam))
    assert out == [ROWS, []]  # pass-through; empty later group merely skipped
    assert len(sql.connections["db"].cursor_double.executed) == 1


# --- The collection probe does not change the insert target ---
def test_probe_runs_and_collection_unused(op: InsertTableOperator) -> None:
    seam = _RecordingSeam(source_properties={"connection": {"protocol": "sqlite"}})
    sql = SQLSourceDouble("src")
    seam.sources["src"] = sql
    out = op.apply([list(ROWS)], {**MINIMAL, "collection": "custom"}, _props(seam))
    assert out == [ROWS]
    assert seam.calls_to("get_source_properties") == [{"source": "src"}]
    query, _ = sql.connections["db"].cursor_double.executed[0]
    assert "custom" not in query and "public" not in query  # collection never reaches SQL


# --- Insert query, missing-value fill, commit, and disconnect ---
def test_exact_query_and_batch_data(op: InsertTableOperator) -> None:
    seam, sql = _seam_with_sql_source()
    payload = [list(ROWS)]
    out = op.apply(payload, dict(MINIMAL), _props(seam))
    assert out is payload  # success pass-through is identity-preserving
    connection = sql.connections["db"]
    query, rows = connection.cursor_double.executed[0]
    assert query == 'INSERT INTO "t" ("a", "b") VALUES (?, ?)'
    assert rows == [(1, "x"), (2, "y"), (3, "z")]
    assert connection.commits == 1
    assert sql.disconnects == 1


# --- Batching with one connection per batch ---
def test_batching_and_per_batch_reconnect(op: InsertTableOperator) -> None:
    seam, sql = _seam_with_sql_source()
    rows = [{"a": i} for i in range(5)]
    out = op.apply([rows], {**MINIMAL, "batch_size": 2}, _props(seam))
    assert out == [rows]
    executed = sql.connections["db"].cursor_double.executed
    assert [len(batch) for _q, batch in executed] == [2, 2, 1]
    # Each batch opens its own source and database connection.
    assert len(seam.calls_to("connect_source")) == 3
    assert sql.connect_calls == ["db", "db", "db"]
    assert sql.disconnects == 3


def test_rowcount_summation_across_batches(op: InsertTableOperator) -> None:
    # The summed per-batch rowcounts (2 + 2 + 1 = 5) are the group's insert count,
    # observed through the success log message.
    import logging

    seam, _sql = _seam_with_sql_source()
    rows = [{"a": i} for i in range(5)]
    records: list[logging.LogRecord] = []

    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    target = logging.getLogger("blue_data_ops.operators.insert_table_operator")
    target.addHandler(handler)
    target.setLevel(logging.INFO)
    try:
        op.apply([rows], {**MINIMAL, "batch_size": 2}, _props(seam))
    finally:
        target.removeHandler(handler)
    assert any(
        isinstance(r.args, tuple) and r.args and r.args[0] == 5
        for r in records
        if r.levelno == logging.INFO
    )


def test_outer_exception_identity_pass_through(op: InsertTableOperator) -> None:
    # A direct apply() with a string batch_size (validation bypassed) raises inside
    # range() BEFORE the per-batch try — the outer handler swallows it and returns
    # the exact input object.
    seam, _sql = _seam_with_sql_source()
    payload = [list(ROWS)]
    out = op.apply(payload, {**MINIMAL, "batch_size": "3"}, _props(seam))
    assert out is payload


# --- First-row columns govern heterogeneous batches ---
def test_heterogeneous_rows(op: InsertTableOperator) -> None:
    seam, sql = _seam_with_sql_source()
    rows: list[dict[str, Any]] = [{"a": 1, "b": 2}, {"a": 3, "c": 99}]
    op.apply([rows], dict(MINIMAL), _props(seam))
    query, batch = sql.connections["db"].cursor_double.executed[0]
    assert query == 'INSERT INTO "t" ("a", "b") VALUES (?, ?)'
    assert batch == [(1, 2), (3, None)]  # b None-filled; c dropped


# --- Connection and execution failures ---
def test_falsy_connect_source_signals_failure(op: InsertTableOperator) -> None:
    seam = _RecordingSeam()  # no source registered -> connect_source returns None
    assert op.apply([list(ROWS)], dict(MINIMAL), _props(seam)) == [[]]


def test_cursor_error_signals_failure(op: InsertTableOperator) -> None:
    seam, sql = _seam_with_sql_source()

    class _BoomCursor:
        def executemany(self, query: str, rows: list[Any]) -> None:
            raise RuntimeError("db down")

    class _BoomConnection:
        def cursor(self) -> _BoomCursor:
            return _BoomCursor()

        def commit(self) -> None:
            return None

    sql.connections["db"] = cast(Any, _BoomConnection())
    assert op.apply([list(ROWS)], dict(MINIMAL), _props(seam)) == [[]]


# --- A fully filtered group still produces a successful pass-through ---
def test_all_rows_filtered_group(op: InsertTableOperator) -> None:
    seam, sql = _seam_with_sql_source()
    junk: list[Any] = [{}, "not-a-dict", {}]
    out = op.apply([junk], dict(MINIMAL), _props(seam))
    assert out == [junk]
    assert sql.connections == {}


# --- Multi-group accumulation stops on a later failure ---
def test_multi_group_late_failure(op: InsertTableOperator) -> None:
    seam, _sql = _seam_with_sql_source()
    calls = {"n": 0}
    original = seam.connect_source

    def flaky(source: str) -> Any:
        calls["n"] += 1
        return original(source) if calls["n"] == 1 else None

    seam.connect_source = flaky  # type: ignore[method-assign]
    out = op.apply([list(ROWS), list(ROWS)], dict(MINIMAL), _props(seam))
    assert out == [[]]  # group 2's falsy connect fails the whole op


# --- IT-INT: real temp-file SQLite end-to-end ---
def test_sqlite_end_to_end(op: InsertTableOperator, tmp_path: Path) -> None:
    seam = RegistrySeam(DataRegistry(name="it", rebuild=True))
    source: Any = SQLiteDBSource(
        "src",
        properties={"connection": {"protocol": "sqlite", "database_directory": str(tmp_path)}},
    )
    seam.register_source(source)

    setup = source._db_connect("db")
    setup.cursor().execute('CREATE TABLE "t" ("a" INTEGER, "b" TEXT)')
    setup.commit()
    source._db_disconnect(setup)

    out = op.apply([list(ROWS)], dict(MINIMAL), {"data_registry": seam})
    assert out == [ROWS]

    check = source._db_connect("db")
    stored = check.cursor().execute('SELECT "a", "b" FROM "t" ORDER BY "a"').fetchall()
    source._db_disconnect(check)
    assert stored == [(1, "x"), (2, "y"), (3, "z")]


# --- Validator behavior, including bool-as-int handling ---
@pytest.mark.parametrize(
    "mutation,expected",
    [
        ({}, True),
        ({"source": " "}, False),
        ({"database": ""}, False),
        ({"table": "  "}, False),
        ({"batch_size": 0}, False),
        ({"batch_size": -1}, False),
        ({"batch_size": "3"}, False),  # base lax accepts; the isinstance check rejects
        ({"batch_size": 3.5}, False),
        ({"batch_size": True}, True),  # bool is int and True > 0
        ({"batch_size": 100}, True),
    ],
    ids=[
        "valid",
        "blank-source",
        "empty-db",
        "blank-table",
        "zero",
        "negative",
        "str",
        "float",
        "bool-is-positive-int",
        "explicit-100",
    ],
)
def test_validator(op: InsertTableOperator, mutation: dict[str, Any], expected: bool) -> None:
    assert op.validate([list(ROWS)], {**MINIMAL, **mutation}) is expected


# --- Explainer (custom; totals from input) ---
def test_explainer(op: InsertTableOperator) -> None:
    exp = op.explain([ROWS], [list(ROWS), [{"a": 9}]], dict(MINIMAL))
    assert exp["explanation"] == (
        "Insert table operator inserted 4 data rows from 2 data groups into table 't' "
        "in database 'db' collection 'public' of source 'src' using batch size 100."
    )


# --- Full four-field interface contract ---
def test_interface(op: InsertTableOperator) -> None:
    assert op.name == "insert_table"
    assert op.description == "Inserts data rows into database tables in a data source."
    expected: dict[str, tuple[str, str, bool, Any]] = {
        "source": (
            "str",
            "Name of the data source where the table is located",
            True,
            "default_source",
        ),
        "database": ("str", "Name of the database where the table is located", True, "default"),
        "collection": (
            "str",
            "Name of the collection where the table is located. For SQLite sources, "
            "defaults to 'public' if not specified",
            False,
            "public",
        ),
        "table": ("str", "Name of the table to insert data into", True, ""),
        "batch_size": ("int", "Number of rows to insert in each batch (default: 100)", False, 100),
    }
    assert set(op.attributes) == set(expected)
    for attr_name, (attr_type, attr_desc, required, default) in expected.items():
        spec = op.attributes[attr_name]
        assert spec.type == attr_type
        assert spec.description == attr_desc
        assert spec.required is required
        assert spec.default == default

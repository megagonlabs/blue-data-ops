from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from blue_data.registry.data_registry import DataRegistry  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.json.file_json_source import FileJSONSource  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource  # pyright: ignore[reportMissingTypeStubs]

from blue_data_ops.llm.sql_execution import ReadOnlySQLExecutor
from blue_data_ops.operators import active_registry, versioned_registry
from blue_data_ops.operators._nl2sql_outcome import NL2SQLOutcomeOperator
from tests.unit.data.test_sql_diagnostics import Reply, attrs, snapshot


@pytest.mark.parametrize(
    "case",
    [
        "reject-database",
        "reject-collection",
        "existing-empty",
        "stale-new-live",
        "unsynced",
        "missing-directory",
    ],
)
def test_generation_preserves_disk_store_and_complete_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    directory = tmp_path / "databases"
    directory.mkdir()
    (directory / "shop.db").touch()
    store = FileJSONSource(properties={"connection": {"path": str(tmp_path / "registry.json")}})
    registry: Any = DataRegistry(store=store, rebuild=False)
    source: Any = SQLiteDBSource(
        "local", properties={"connection": {"database_directory": str(directory)}}
    )
    registry.register_source(source)
    if case != "unsynced":
        registry.register_source_database("local", "shop")
        registry.register_source_database_collection("local", "shop", "public")
    target = attrs()
    if case in {"reject-database", "unsynced", "missing-directory"}:
        target["database"] = "absent"
    elif case == "reject-collection":
        target["collection"] = "absent"
    elif case == "stale-new-live":
        (directory / "fresh.sqlite").touch()
        (directory / "fresh.db").mkdir()
        target["database"] = "fresh"
    if case == "missing-directory":
        source.properties["connection"]["database_directory"] = str(tmp_path / "must-stay-absent")

    def deny(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("generation touched source backend or registry writes")

    for name in (
        "fetch_databases",
        "fetch_database_collections",
        "_get_database_directory",
        "_get_database_path",
        "_db_connect",
        "execute_query",
    ):
        monkeypatch.setattr(source, name, deny)
    for name in ("sync_source", "register_record", "connect_source"):
        monkeypatch.setattr(registry, name, deny)
    before = snapshot(tmp_path)
    records = json.dumps(registry.list_records(), sort_keys=True, default=str)
    state = json.dumps(vars(store), sort_keys=True, default=str)
    client = Reply()
    result = (
        active_registry()
        .resolve("nl2sql@4.0.0")
        .run([[]], target, {"data_registry": registry, "llm_client": client})
    )
    assert snapshot(tmp_path) == before
    assert json.dumps(registry.list_records(), sort_keys=True, default=str) == records
    assert json.dumps(vars(store), sort_keys=True, default=str) == state
    rejected = case in {"reject-database", "reject-collection"}
    assert client.calls == int(not rejected)
    assert bool(result[2].errors) is rejected


def test_execute_query_does_not_use_generation_name_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from blue_data_ops.operators import nl2sql_operator

    with sqlite3.connect(tmp_path / "shop.db") as connection:
        connection.execute("CREATE TABLE people (id INTEGER)")
    registry: Any = DataRegistry(
        store=FileJSONSource(properties={"connection": {"path": str(tmp_path / "registry.json")}}),
        rebuild=False,
    )
    source = SQLiteDBSource(
        "local", properties={"connection": {"database_directory": str(tmp_path)}}
    )
    registry.register_source(source)
    registry.sync_source("local", recursive=True)

    def deny(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("execute branch used generation proof")

    monkeypatch.setattr(nl2sql_operator, "diagnose_generation_target", deny, raising=False)
    executor = ReadOnlySQLExecutor(registry, frozenset({("local", "shop", "public")}))
    operator = NL2SQLOutcomeOperator(read_only_executor=executor)
    result = operator.run([[]], attrs(), {"execute_query": True, "llm_client": Reply()})
    assert not result[2].errors and result[2].is_empty


@pytest.mark.parametrize("identity", ["insert_table@2.0.0", "insert_table@3.0.0"])
def test_foreign_connect_file_not_found_is_not_missing_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    identity: str,
) -> None:
    registry: Any = DataRegistry(rebuild=False)
    source: Any = SQLiteDBSource(
        "local", properties={"connection": {"database_directory": str(tmp_path)}}
    )
    registry.register_source(source)

    def foreign(*args: Any, **kwargs: Any) -> Any:
        raise FileNotFoundError("synthetic unrelated file")

    monkeypatch.setattr(source, "_db_connect", foreign)

    # Keep the exact configured object at the boundary instead of restoring a new one.
    def same_source(*args: Any, **kwargs: Any) -> Any:
        return source

    monkeypatch.setattr(registry, "connect_source", same_source)
    result = (
        versioned_registry()
        .resolve(identity)
        .run(
            [[{"id": 2}]],
            {"source": "local", "database": "absent", "table": "people"},
            {"data_registry": registry},
        )
    )
    assert result[2].errors[0].message == "operator execution failed"

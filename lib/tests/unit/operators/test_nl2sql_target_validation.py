from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from blue_data.registry.data_registry import DataRegistry  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.json.memory_json_source import MemoryJSONSource  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource  # pyright: ignore[reportMissingTypeStubs]

from blue_data_ops.data.errors import RegistryFailure, RegistryReason
from blue_data_ops.data.registry_seam import RegistrySeam
from blue_data_ops.llm.sql_execution import ReadOnlySQLExecutor
from blue_data_ops.operators import NL2SQLOutcomeOperator, active_registry
from tests.unit.data.test_sql_diagnostics import Reply, attrs, snapshot


@pytest.fixture
def catalog(tmp_path: Path) -> Any:
    with sqlite3.connect(tmp_path / "shop.db") as connection:
        connection.execute("CREATE TABLE people (id INTEGER)")
        connection.execute("INSERT INTO people VALUES (1)")
    registry = DataRegistry(store=MemoryJSONSource(), rebuild=False)
    registry.register_source(
        SQLiteDBSource("local", properties={"connection": {"database_directory": str(tmp_path)}})
    )
    registry.sync_source("local", recursive=True)
    return registry


def run_target(registry: Any, target: dict[str, Any], client: Reply, route: str) -> Any:
    if route == "generation":
        return (
            active_registry()
            .resolve("nl2sql@4.0.0")
            .run([[]], target, {"data_registry": registry, "llm_client": client})
        )
    executor = ReadOnlySQLExecutor(
        registry, frozenset({(target["source"], target["database"], target["collection"])})
    )
    return NL2SQLOutcomeOperator(read_only_executor=executor).run(
        [[]], target, {"execute_query": True, "llm_client": client}
    )


@pytest.mark.parametrize("route", ["generation", "executor"])
@pytest.mark.parametrize(
    "field,message",
    [
        ("database", "database is not available in the declared source"),
        ("collection", "collection is not available in the declared database"),
    ],
)
def test_confirmed_absence_stops_before_client_and_backend(
    catalog: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    field: str,
    message: str,
) -> None:
    import blue_data_ops.operators.nl2sql_operator as module

    touched: list[str] = []

    def denied(*args: Any, **kwargs: Any) -> Any:
        touched.append("client or backend")
        raise AssertionError("target reached a later boundary")

    monkeypatch.setattr(module, "resolve_llm_client", denied)
    monkeypatch.setattr(SQLiteDBSource, "_db_connect", denied)
    before = snapshot(tmp_path)
    records = json.dumps(catalog.list_records(), sort_keys=True, default=str)
    client = Reply()
    result = run_target(catalog, {**attrs(), field: "missing"}, client, route)
    assert result[2].errors[0].message == message
    assert client.calls == 0 and touched == []
    assert snapshot(tmp_path) == before
    assert json.dumps(catalog.list_records(), sort_keys=True, default=str) == records


@pytest.mark.parametrize("route", ["generation", "executor"])
@pytest.mark.parametrize("listing", ["list_source_databases", "list_database_collections"])
@pytest.mark.parametrize("owned", [False, True])
def test_catalog_exceptions_are_safe_failures_before_client(
    catalog: Any,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    listing: str,
    owned: bool,
) -> None:
    marker = "SYNTHETIC_PRIVATE_CATALOG_DETAIL"

    def failed(*args: Any) -> Any:
        if owned:
            raise RegistryFailure(RegistryReason.CONNECTION_FAILED)
        raise RuntimeError(marker)

    monkeypatch.setattr(catalog, listing, failed)
    client = Reply()
    result = run_target(catalog, attrs(), client, route)
    assert result[2].errors[0].message == "read-only SQL execution failed"
    assert marker not in repr(result)
    assert client.calls == 0


@pytest.mark.parametrize("route", ["generation", "executor"])
@pytest.mark.parametrize("records", [[], None, {}, [None], [{"name": ""}], [{"name": 3}]])
def test_inconclusive_peer_listings_preserve_valid_targets(
    catalog: Any,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    records: Any,
) -> None:
    def listing(*args: Any) -> Any:
        return records

    monkeypatch.setattr(catalog, "list_source_databases", listing)
    monkeypatch.setattr(catalog, "list_database_collections", listing)
    client = Reply()
    result = run_target(catalog, attrs(), client, route)
    assert not result[2].errors and client.calls == 1


def test_executor_requires_refresh_for_a_new_live_database(
    catalog: Any,
    tmp_path: Path,
) -> None:
    with sqlite3.connect(tmp_path / "fresh.db") as connection:
        connection.execute("CREATE TABLE people (id INTEGER)")
        connection.execute("INSERT INTO people VALUES (2)")
    target = {**attrs(), "database": "fresh"}
    direct_client = Reply()
    assert not run_target(catalog, target, direct_client, "generation")[2].errors
    assert direct_client.calls == 1
    client = Reply()
    rejected = run_target(catalog, target, client, "executor")
    assert rejected[2].errors[0].message == "database is not available in the declared source"
    assert client.calls == 0
    catalog.sync_source("local", recursive=True)
    accepted = run_target(catalog, target, client, "executor")
    assert not accepted[2].errors and accepted[0] == [[{"id": 2}]]
    assert client.calls == 1


@pytest.mark.parametrize("route", ["generation", "executor"])
def test_exact_sqlite_custom_callback_is_the_schema_authority(
    catalog: Any,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
) -> None:
    calls: list[tuple[str, str, str]] = []

    def schema(source: str, database: str, collection: str) -> Any:
        calls.append((source, database, collection))
        return {"people": {"id": "integer"}}

    def denied(*args: Any) -> Any:
        raise AssertionError("custom schema used native catalog")

    authority = RegistrySeam(catalog) if route == "generation" else catalog
    monkeypatch.setattr(authority, "get_data_source_schema", schema)
    monkeypatch.setattr(catalog, "list_source_databases", denied)
    monkeypatch.setattr(catalog, "list_database_collections", denied)
    client = Reply()
    target = {**attrs(), "database": "missing"}
    result = run_target(authority, target, client, route)
    assert calls == [("local", "missing", "public")] and client.calls == 1
    if route == "generation":
        assert not result[2].errors
    else:
        assert result[2].errors
        assert not (
            Path(catalog.get_source("local").properties["connection"]["database_directory"])
            / "missing.db"
        ).exists()


def test_source_error_precedes_target_listing_failure(
    catalog: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    touched: list[bool] = []

    def denied(*args: Any) -> Any:
        touched.append(True)
        raise RuntimeError("SYNTHETIC_PRIVATE_CATALOG_DETAIL")

    monkeypatch.setattr(catalog, "list_source_databases", denied)
    client = Reply()
    result = run_target(catalog, {**attrs(), "source": "unknown"}, client, "generation")
    assert result[2].errors[0].message == "data source is not registered"
    assert touched == [] and client.calls == 0

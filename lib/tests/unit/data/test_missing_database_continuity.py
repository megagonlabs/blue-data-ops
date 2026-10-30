from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from blue_data.registry.data_registry import DataRegistry  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.json.memory_json_source import MemoryJSONSource  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource  # pyright: ignore[reportMissingTypeStubs]

from blue_data_ops.data import RegistrySeam
from blue_data_ops.operators import active_registry, versioned_registry
from tests.unit.data.test_sql_diagnostics import Reply, attrs, snapshot


def registry_at(directory: Path) -> tuple[Any, Any]:
    registry: Any = DataRegistry(store=MemoryJSONSource(), rebuild=False)
    source: Any = SQLiteDBSource(
        "local", properties={"connection": {"database_directory": str(directory)}}
    )
    registry.register_source(source)
    return registry, source


@pytest.mark.parametrize(
    "identity", ["insert_table@2.0.0", "insert_table@3.0.0", "create_table@2.0.0"]
)
def test_new_live_database_remains_writable_after_registry_sync(
    tmp_path: Path, identity: str
) -> None:
    with sqlite3.connect(tmp_path / "shop.db") as connection:
        connection.execute("CREATE TABLE old (id INTEGER)")
    registry, _ = registry_at(tmp_path)
    registry.sync_source("local", recursive=True)
    with sqlite3.connect(tmp_path / "fresh.db") as connection:
        if identity.startswith("insert_table"):
            connection.execute("CREATE TABLE people (id INTEGER)")
    result = (
        versioned_registry()
        .resolve(identity)
        .run(
            [[{"id": 2}]],
            {
                "source": "local",
                "database": "fresh",
                "table": "people",
                "columns": [{"name": "id", "type": "INTEGER"}],
            },
            {"data_registry": registry},
        )
    )
    assert not result[2].errors
    with sqlite3.connect(tmp_path / "fresh.db") as connection:
        rows = connection.execute("SELECT id FROM people").fetchall()
    assert rows == ([(2,)] if identity.startswith("insert_table") else [])


@pytest.mark.parametrize("identity", ["insert_table@2.0.0", "insert_table@3.0.0"])
def test_missing_database_reads_exact_connect_raising_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    identity: str,
) -> None:
    registered = tmp_path / "registered"
    raising = tmp_path / "raising"
    registered.mkdir()
    raising.mkdir()
    (registered / "absent.db").touch()
    registry, _ = registry_at(registered)
    exact: Any = SQLiteDBSource(
        "local", properties={"connection": {"database_directory": str(raising)}}
    )

    class ReturnedSource(RegistrySeam):
        def connect_source(self, source: str) -> Any:
            return exact

    seam = ReturnedSource(registry)
    result = (
        versioned_registry()
        .resolve(identity)
        .run(
            [[{"id": 2}]],
            {"source": "local", "database": "absent", "table": "people"},
            {"data_registry": seam},
        )
    )
    assert result[2].errors[0].message == "database does not exist"


@pytest.mark.parametrize(
    "listing",
    [PermissionError(), ValueError(), [None], [True], ["nul\x00name.db"], [".db"], ["good.db", ""]],
)
def test_unreadable_or_malformed_listing_is_inconclusive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    listing: Any,
) -> None:
    (tmp_path / "shop.db").touch()
    registry, _ = registry_at(tmp_path)
    registry.register_source_database("local", "shop")
    registry.register_source_database_collection("local", "shop", "public")

    def listdir(*args: Any, **kwargs: Any) -> Any:
        if isinstance(listing, Exception):
            raise listing
        return listing

    before = snapshot(tmp_path)
    monkeypatch.setattr(os, "listdir", listdir)
    client = Reply()
    result = (
        active_registry()
        .resolve("nl2sql@3.0.0")
        .run(
            [[]],
            {**attrs(), "database": "absent"},
            {"data_registry": registry, "llm_client": client},
        )
    )
    assert client.calls == 1 and not result[2].errors
    assert snapshot(tmp_path) == before


def test_directory_with_sqlite_suffix_is_only_a_name_proof(tmp_path: Path) -> None:
    (tmp_path / "shop.db").touch()
    (tmp_path / "later.db").mkdir()
    registry, _ = registry_at(tmp_path)
    registry.register_source_database("local", "shop")
    registry.register_source_database_collection("local", "shop", "public")
    client = Reply()
    result = (
        active_registry()
        .resolve("nl2sql@3.0.0")
        .run(
            [[]],
            {**attrs(), "database": "later"},
            {"data_registry": registry, "llm_client": client},
        )
    )
    assert client.calls == 1 and not result[2].errors

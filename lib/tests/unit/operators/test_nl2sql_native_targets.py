from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Iterator
from types import ModuleType
from typing import Any, cast
from unittest.mock import Mock

import pytest
from blue_data.registry.data_registry import DataRegistry  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.json.memory_json_source import MemoryJSONSource  # pyright: ignore[reportMissingTypeStubs]

from blue_data_ops.llm import LLMClient
from blue_data_ops.llm.sql_execution import ReadOnlySQLExecutor
from blue_data_ops.operators import NL2SQLOutcomeOperator, active_registry


class CatalogReply(LLMClient):
    def __init__(self, query: str = "SELECT id FROM people") -> None:
        self.calls = 0
        self.query = query
        self.schema: dict[str, Any] = {}

    def execute_api_call(
        self,
        input: Any,
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        assert additional_data is not None
        self.calls += 1
        self.schema = json.loads(additional_data["schema"])
        return {"query": self.query}


@pytest.fixture(params=["postgres", "mysql"])
def native_catalog(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[Any, str, Mock, Mock]]:
    protocol = cast(str, request.param)
    package = f"blue_data.source.sql.{protocol}"
    module_name = f"{package}.{protocol}_sql_source"
    class_name = "PostgresDBSource" if protocol == "postgres" else "MySQLDBSource"
    sql_package = importlib.import_module("blue_data.source.sql")
    prefixes = (package, "psycopg2", "mysql")

    # Reimport the concrete source against stand-ins even if a driver test ran first.
    # Restore both module and parent-package caches before the next driver test.
    with monkeypatch.context() as patch:
        for name in tuple(sys.modules):
            if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes):
                patch.delitem(sys.modules, name)
        patch.delattr(sql_package, protocol, raising=False)
        connection = Mock()
        cursor = connection.cursor.return_value
        cursor.description = [("id",)]
        cursor.fetchall.return_value = [(1,)]
        connect = Mock(return_value=connection)
        postgres = ModuleType("psycopg2")
        mysql = ModuleType("mysql")
        connector = ModuleType("mysql.connector")
        vars(postgres)["connect"] = connect
        vars(connector)["connect"] = connect
        vars(mysql)["connector"] = connector
        for driver in (postgres, mysql, connector):
            patch.setitem(sys.modules, driver.__name__, driver)
        try:
            module = importlib.import_module(module_name)
            assert vars(module)["psycopg2" if protocol == "postgres" else "cpy"] is (
                postgres if protocol == "postgres" else connector
            )
            source_class = cast(type[Any], getattr(module, class_name))
            source = source_class("local")
            assert type(source) is source_class
            registry: Any = DataRegistry(store=MemoryJSONSource(), rebuild=False)
            registry.register_source(source)
            for database in ("analytics", "emptydb"):
                registry.register_source_database("local", database)
                registry.register_source_database_collection("local", database, "public")
            registry.register_source_database_collection_entity(
                "local", "analytics", "public", "people"
            )
            registry.register_source_database_collection_entity_attribute(
                "local",
                "analytics",
                "public",
                "people",
                "id",
                properties={"info": {"type": "INTEGER"}},
            )
            connect.reset_mock()
            connection.reset_mock()
            yield registry, protocol, connect, connection
        finally:
            for name in tuple(sys.modules):
                if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes):
                    sys.modules.pop(name)
            vars(sql_package).pop(protocol, None)


def run_native_target(
    registry: Any, protocol: str, database: str, collection: str, route: str, client: CatalogReply
) -> Any:
    target = {
        "question": "List people",
        "source": "local",
        "protocol": protocol,
        "database": database,
        "collection": collection,
    }
    if route == "generation":
        return (
            active_registry()
            .resolve("nl2sql@4.0.0")
            .run([[]], target, {"data_registry": registry, "llm_client": client})
        )
    executor = ReadOnlySQLExecutor(registry, frozenset({("local", database, collection)}))
    return NL2SQLOutcomeOperator(read_only_executor=executor).run(
        [[]], target, {"execute_query": True, "llm_client": client}
    )


@pytest.mark.parametrize("route", ["generation", "executor"])
@pytest.mark.parametrize(
    "database,collection,message",
    [
        ("missing", "public", "database is not available in the declared source"),
        ("analytics", "missing", "collection is not available in the declared database"),
        ("analytics", "analytics", "collection is not available in the declared database"),
    ],
)
def test_native_missing_target_stops_before_model_and_connection(
    native_catalog: tuple[Any, str, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    database: str,
    collection: str,
    message: str,
) -> None:
    import blue_data_ops.operators.nl2sql_operator as module

    registry, protocol, connect, connection = native_catalog
    resolve = Mock(side_effect=AssertionError("missing target reached client resolution"))
    monkeypatch.setattr(module, "resolve_llm_client", resolve)
    before = json.dumps(registry.list_records(), sort_keys=True)
    client = CatalogReply()
    result = run_native_target(registry, protocol, database, collection, route, client)
    assert result[0] == [[]]
    assert result[2].errors[0].message == message
    hint = result[2].errors[0].suggestion
    assert hint and "sync the source" in hint
    assert ("registered databases" if database == "missing" else "public") in hint
    assert client.calls == 0
    resolve.assert_not_called()
    connect.assert_not_called()
    assert connection.mock_calls == []
    assert json.dumps(registry.list_records(), sort_keys=True) == before


@pytest.mark.parametrize("route", ["generation", "executor"])
@pytest.mark.parametrize("control", ["rows", "zero-rows", "empty-schema"])
def test_native_valid_and_empty_targets_reach_model(
    native_catalog: tuple[Any, str, Mock, Mock],
    route: str,
    control: str,
) -> None:
    registry, protocol, connect, connection = native_catalog
    database = "emptydb" if control == "empty-schema" else "analytics"
    connection.cursor.return_value.fetchall.return_value = [] if control == "zero-rows" else [(1,)]
    query = "SELECT 1 AS id" if control == "empty-schema" else "SELECT id FROM people"
    client = CatalogReply(query)
    result = run_native_target(registry, protocol, database, "public", route, client)
    assert not result[2].errors and client.calls == 1
    assert client.schema == {
        "entities": []
        if control == "empty-schema"
        else [{"name": "people", "attributes": {"id": {"type": "INTEGER"}}}],
        "relations": [],
    }
    if route == "generation":
        assert result[0] == [[{"sql": query}]]
        connect.assert_not_called()
    else:
        connect.assert_called_once()
        assert connect.call_args is not None
        assert connect.call_args.kwargs["database"] == database
        assert result[0] == ([[]] if control == "zero-rows" else [[{"id": 1}]])
        connection.cursor.return_value.execute.assert_any_call(query)
        if protocol == "postgres":
            connection.set_session.assert_called_once_with(readonly=True)
        else:
            connection.cursor.return_value.execute.assert_any_call(
                "SET SESSION TRANSACTION READ ONLY"
            )

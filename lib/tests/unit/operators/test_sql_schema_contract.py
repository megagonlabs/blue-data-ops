from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from blue_data.registry.data_registry import DataRegistry  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.json.memory_json_source import MemoryJSONSource  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource  # pyright: ignore[reportMissingTypeStubs]

from blue_data_ops.data import RegistrySeam
from blue_data_ops.llm import LLMClient, LLMError
from blue_data_ops.llm.sql_execution import ReadOnlySQLExecutor
from blue_data_ops.operators import NL2SQLOperator, versioned_registry

TARGET = ("demo", "db", "public")
ATTRS = dict(zip(("source", "database", "collection"), TARGET)) | {
    "question": "list records",
    "protocol": "sqlite",
    "schema": "untrusted schema",
}
EXPECTED: dict[str, Any] = {
    "entities": [
        {
            "name": "orders",
            "attributes": {"id": {"type": "INTEGER"}, "unknown": {}, '列"': {"type": "TEXT"}},
        },
        {"name": "table_only", "attributes": {}},
    ],
    "relations": [{"name": "orders_link", "source": "orders", "target": "table_only"}],
}


class CaptureClient(LLMClient):
    def __init__(self):
        self.schemas: list[dict[str, Any]] = []

    def execute_api_call(self, input: Any, properties: Any = None, additional_data: Any = None):
        self.schemas.append(json.loads(additional_data["schema"]))
        return {"query": "SELECT 1 AS n"}


@pytest.fixture
def registry(tmp_path: Path):
    with sqlite3.connect(tmp_path / "db.db") as connection:
        connection.execute("CREATE TABLE records (id INTEGER)")
    reg: Any = DataRegistry(store=MemoryJSONSource(), rebuild=False)
    reg.register_source(
        SQLiteDBSource("demo", properties={"connection": {"database_directory": str(tmp_path)}})
    )
    reg.register_source_database("demo", "db")
    reg.register_source_database_collection(*TARGET)
    for name in ("orders", "table_only"):
        reg.register_source_database_collection_entity(
            *TARGET, name, properties={"samples": ["PRIVATE_MARKER"]}
        )
    for name, info in [("id", {"type": "INTEGER"}), ("unknown", {}), ('列"', {"type": "TEXT"})]:
        reg.register_source_database_collection_entity_attribute(
            *TARGET, "orders", name, properties={"info": info, "samples": ["PRIVATE_MARKER"]}
        )
    reg.register_record(
        "link",
        "relation",
        scope="/source/demo/database/db/collection/public",
        properties={
            "name": "orders_link",
            "source": "orders",
            "target": "table_only",
            "properties": {"raw": "PRIVATE_MARKER"},
        },
    )
    reg.register_source_database_collection("demo", "db", "unrelated")
    reg.register_source_database_collection_entity("demo", "db", "unrelated", "PRIVATE_MARKER")
    return reg


@pytest.mark.parametrize("host_bound", [False, True])
def test_exact_prompt_projection(registry: Any, host_bound: bool, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG, logger="blue_data_ops.operators.nl2sql_operator")
    client = CaptureClient()
    executor = ReadOnlySQLExecutor(registry, frozenset({TARGET})) if host_bound else None
    op = NL2SQLOperator(read_only_executor=executor)
    properties: dict[str, Any] = {"llm_client": client}
    if host_bound:
        properties["execute_query"] = True
        assert op.apply([[]], ATTRS, properties) == [[{"n": 1}]]
    else:
        properties["data_registry"] = RegistrySeam(registry)
        assert op.apply([[]], ATTRS, properties) == [[{"sql": "SELECT 1 AS n"}]]
    assert client.schemas == [EXPECTED]
    assert "PRIVATE_MARKER" not in json.dumps(client.schemas)
    debug_output = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name == "blue_data_ops.operators.nl2sql_operator"
    )
    for field in ("orders", "table_only", "INTEGER", "TEXT"):
        assert field not in debug_output


@pytest.mark.parametrize("host_bound", [False, True])
def test_lookup_failure_is_fixed_error(
    registry: Any, monkeypatch: pytest.MonkeyPatch, host_bound: bool
):
    def broken(*args: Any):
        raise RuntimeError("PRIVATE_MARKER")

    monkeypatch.setattr(registry, "list_entity_attributes", broken)
    client = CaptureClient()
    executor = ReadOnlySQLExecutor(registry, frozenset({TARGET})) if host_bound else None
    op = NL2SQLOperator(read_only_executor=executor)
    props = {"execute_query": True} if host_bound else {"data_registry": RegistrySeam(registry)}
    with pytest.raises(LLMError) as error:
        op.apply([[]], ATTRS, props | {"llm_client": client})
    assert error.value.code == "sql_execution_failed"
    assert str(error.value) == "read-only SQL execution failed"
    assert client.schemas == []


@pytest.mark.parametrize("instance_override", [False, True])
@pytest.mark.parametrize("version", ["1.0.0", "2.0.0", "3.0.0", "4.0.0"])
@pytest.mark.parametrize("path", ["apply", "run"])
def test_custom_schema_dispatch_keeps_only_prompt_fields(
    monkeypatch: pytest.MonkeyPatch, instance_override: bool, version: str, path: str
):
    calls: list[Any] = []

    def schema(*args: Any, **kwargs: Any):
        calls.append((args, kwargs))
        return {
            "entities": [
                {
                    "name": "orders",
                    "attributes": {"id": {"type": "INTEGER", "samples": ["PRIVATE_MARKER"]}},
                    "properties": {"credential": "PRIVATE_MARKER"},
                }
            ],
            "relations": [
                {
                    "name": "link",
                    "source": "orders",
                    "target": "items",
                    "source_entity": "orders",
                    "target_entity": "items",
                    "foreign_keys_source_columns": ["customer_id"],
                    "foreign_keys_target_columns": ["id"],
                    "properties": {"raw": "PRIVATE_MARKER"},
                }
            ],
            "metadata": "PRIVATE_MARKER",
        }

    class Custom(RegistrySeam):
        def get_data_source_schema(self, *args: Any, **kwargs: Any) -> Any:
            return schema(*args, **kwargs)

    if instance_override:
        seam = RegistrySeam(DataRegistry(store=MemoryJSONSource(), rebuild=False))
        monkeypatch.setattr(seam, "get_data_source_schema", schema)
    else:
        seam = Custom(DataRegistry(store=MemoryJSONSource(), rebuild=False))
    client = CaptureClient()
    op = versioned_registry().resolve("nl2sql@" + version)
    props = {"data_registry": seam, "llm_client": client}
    if path == "apply":
        output = op.apply([[]], ATTRS, props)
    else:
        output, _, meta = op.run([[]], ATTRS, props)
        assert not meta.errors
    assert output == [[{"sql": "SELECT 1 AS n"}]]
    assert len(calls) == 1 and calls[0][0] == TARGET
    assert client.schemas == [
        {
            "entities": [{"name": "orders", "attributes": {"id": {"type": "INTEGER"}}}],
            "relations": [
                {
                    "name": "link",
                    "source": "orders",
                    "target": "items",
                    "source_entity": "orders",
                    "target_entity": "items",
                    "foreign_keys_source_columns": ["customer_id"],
                    "foreign_keys_target_columns": ["id"],
                }
            ],
        }
    ]
    assert "PRIVATE_MARKER" not in json.dumps(client.schemas)


@pytest.mark.parametrize("instance_override", [False, True])
@pytest.mark.parametrize("version", ["1.0.0", "2.0.0", "3.0.0", "4.0.0"])
@pytest.mark.parametrize("path", ["apply", "run"])
@pytest.mark.parametrize(
    ("schema", "entities"),
    [
        (
            {"incidents": {"service": "text", "open": "integer"}},
            [
                {
                    "name": "incidents",
                    "attributes": {"open": {"type": "integer"}, "service": {"type": "text"}},
                }
            ],
        ),
        (
            {"jobs": {"columns": ["role"]}},
            [{"name": "jobs", "attributes": {"role": dict[str, str]()}}],
        ),
    ],
    ids=["legacy-column-types", "shipped-column-names"],
)
def test_custom_legacy_schema_reaches_generation_prompt(
    monkeypatch: pytest.MonkeyPatch,
    instance_override: bool,
    version: str,
    path: str,
    schema: Any,
    entities: Any,
):
    calls: list[Any] = []

    def lookup(*args: Any, **kwargs: Any):
        calls.append((args, kwargs))
        return schema

    class Custom(RegistrySeam):
        def get_data_source_schema(self, *args: Any, **kwargs: Any) -> Any:
            return lookup(*args, **kwargs)

    seam = (
        RegistrySeam(DataRegistry(store=MemoryJSONSource(), rebuild=False))
        if instance_override
        else Custom(DataRegistry(store=MemoryJSONSource(), rebuild=False))
    )
    if instance_override:
        monkeypatch.setattr(seam, "get_data_source_schema", lookup)
    client = CaptureClient()
    op = versioned_registry().resolve("nl2sql@" + version)
    props = {"data_registry": seam, "llm_client": client}
    if path == "apply":
        output = op.apply([[]], ATTRS, props)
    else:
        output, _, meta = op.run([[]], ATTRS, props)
        assert not meta.errors
    assert output == [[{"sql": "SELECT 1 AS n"}]]
    assert calls == [(TARGET, {})]
    assert client.schemas == [{"entities": entities, "relations": []}]


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0", "3.0.0", "4.0.0"])
@pytest.mark.parametrize(
    "schema",
    [
        {"metadata": "PRIVATE_MARKER"},
        {"jobs": {"columns": ["role"], "connection": "PRIVATE_MARKER"}},
        {"jobs": {"role": {"samples": ["PRIVATE_MARKER"]}}},
        {"entities": {}, "metadata": "PRIVATE_MARKER"},
        {"entities": [{"name": "jobs", "attributes": ["role"]}]},
        {"entities": [], "relations": {}},
        {"jobs": {"columns": [123]}},
    ],
    ids=[
        "metadata-only",
        "extra-table-fields",
        "column-metadata",
        "bad-entities",
        "bad-attributes",
        "bad-relations",
        "bad-column-name",
    ],
)
def test_unsupported_custom_schema_fails_before_prompt(version: str, schema: Any):
    class Custom(RegistrySeam):
        def get_data_source_schema(self, *args: Any, **kwargs: Any) -> Any:
            return schema

    client = CaptureClient()
    op = versioned_registry().resolve("nl2sql@" + version)
    props = {
        "data_registry": Custom(DataRegistry(store=MemoryJSONSource(), rebuild=False)),
        "llm_client": client,
    }
    with pytest.raises(LLMError) as error:
        op.apply([[]], ATTRS, props)
    assert error.value.code == "sql_execution_failed"
    assert str(error.value) == "read-only SQL execution failed"
    output, _, meta = op.run([[]], ATTRS, props)
    assert output == [[]]
    assert len(meta.errors) == 1
    assert meta.errors[0].message == "read-only SQL execution failed"
    assert "PRIVATE_MARKER" not in str(meta.errors)
    assert client.schemas == []


def test_public_catalog_projects_postgres_relation_endpoints(registry: Any):
    registry.register_record(
        "orders_fk",
        "relation",
        scope="/source/demo/database/db/collection/public",
        properties={
            "source_entity": "orders",
            "target_entity": "table_only",
            "constraint_name": "PRIVATE_MARKER",
            "foreign_keys_source_columns": ["id"],
            "foreign_keys_target_columns": ["id"],
            "connection": "PRIVATE_MARKER",
            "samples": ["PRIVATE_MARKER"],
        },
    )
    client = CaptureClient()
    NL2SQLOperator().apply(
        [[]], ATTRS, {"data_registry": RegistrySeam(registry), "llm_client": client}
    )
    assert client.schemas == [
        EXPECTED
        | {
            "relations": [
                {
                    "name": "orders_fk",
                    "source_entity": "orders",
                    "target_entity": "table_only",
                    "foreign_keys_source_columns": ["id"],
                    "foreign_keys_target_columns": ["id"],
                },
                *EXPECTED["relations"],
            ]
        }
    ]
    assert "PRIVATE_MARKER" not in json.dumps(client.schemas)


@pytest.mark.parametrize("custom", [False, True])
def test_fk_column_projection_copies_lists(registry: Any, custom: bool):
    from blue_data_ops.data.sql_schema import project_sql_schema

    columns = ["customer_id", "tenant_id"]
    target_columns = ["id", "tenant_id"]
    relation = {
        "name": "orders_fk",
        "source_entity": "orders",
        "target_entity": "customers",
        "foreign_keys_source_columns": columns,
        "foreign_keys_target_columns": target_columns,
    }

    class Custom(RegistrySeam):
        def get_data_source_schema(self, *args: Any, **kwargs: Any) -> Any:
            return {"entities": [], "relations": [relation]}

    if custom:
        seam = Custom(registry)
    else:
        registry.register_record(
            relation["name"],
            "relation",
            scope="/source/demo/database/db/collection/public",
            properties=relation,
        )
        seam = RegistrySeam(registry)
    projected = project_sql_schema(seam, *TARGET)
    fk = next(item for item in projected["relations"] if item["name"] == "orders_fk")
    assert fk == relation
    columns.append("later")
    target_columns.append("later")
    assert fk["foreign_keys_source_columns"] == ["customer_id", "tenant_id"]
    assert fk["foreign_keys_target_columns"] == ["id", "tenant_id"]


@pytest.mark.parametrize("custom", [False, True])
@pytest.mark.parametrize("field", ["foreign_keys_source_columns", "foreign_keys_target_columns"])
@pytest.mark.parametrize(
    "value", [None, "PRIVATE_MARKER", ("id",), {"id": "PRIVATE_MARKER"}, [1], ["id", False]]
)
def test_invalid_fk_columns_fail_with_fixed_diagnostics(
    registry: Any, custom: bool, field: str, value: Any
):
    relation = {
        "name": "orders_fk",
        "source_entity": "orders",
        "target_entity": "items",
        field: value,
    }

    class Custom(RegistrySeam):
        def get_data_source_schema(self, *args: Any, **kwargs: Any) -> Any:
            return {"entities": [], "relations": [relation]}

    if custom:
        seam = Custom(registry)
    else:
        registry.register_record(
            relation["name"],
            "relation",
            scope="/source/demo/database/db/collection/public",
            properties=relation,
        )
        seam = RegistrySeam(registry)
    client = CaptureClient()
    op = NL2SQLOperator()
    props = {"data_registry": seam, "llm_client": client}
    with pytest.raises(LLMError) as error:
        op.apply([[]], ATTRS, props)
    assert error.value.code == "sql_execution_failed"
    assert str(error.value) == "read-only SQL execution failed"
    output, _, meta = op.run([[]], ATTRS, props)
    assert output == [[]]
    assert len(meta.errors) == 1
    assert meta.errors[0].message == "read-only SQL execution failed"
    assert "PRIVATE_MARKER" not in str(meta.errors)
    assert client.schemas == []


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("instance_override", [False, True])
def test_native_schema_override_reaches_public_prompt(
    registry: Any, monkeypatch: pytest.MonkeyPatch, wrapped: bool, instance_override: bool
):
    calls: list[Any] = []

    def schema(source: str, database: str, collection: str, format: str = "dict"):
        calls.append((source, database, collection, format))
        return {"jobs": {"columns": ["role"]}}

    class Custom(DataRegistry):
        def get_data_source_schema(
            self, source: str, database: str, collection: str, format: str = "dict"
        ):
            return schema(source, database, collection, format)

    native: Any = (DataRegistry if instance_override else Custom)(
        store=MemoryJSONSource(), rebuild=False
    )
    native.register_source(registry.get_source("demo"))
    if instance_override:
        monkeypatch.setattr(native, "get_data_source_schema", schema)
    client = CaptureClient()
    props = {"data_registry": RegistrySeam(native) if wrapped else native, "llm_client": client}
    output, _, meta = NL2SQLOperator().run([[]], ATTRS, props)
    assert not meta.errors
    assert output == [[{"sql": "SELECT 1 AS n"}]]
    assert calls == [(*TARGET, "dict")]
    assert client.schemas == [
        {"entities": [{"name": "jobs", "attributes": {"role": {}}}], "relations": []}
    ]


@pytest.mark.parametrize("instance_override", [False, True])
def test_explicit_seam_schema_override_precedes_native(
    registry: Any, monkeypatch: pytest.MonkeyPatch, instance_override: bool
):
    native_calls: list[Any] = []
    seam_calls: list[Any] = []

    def native_schema(*args: Any, **kwargs: Any):
        native_calls.append((args, kwargs))
        raise RuntimeError("PRIVATE_MARKER")

    def schema(*args: Any, **kwargs: Any):
        seam_calls.append((args, kwargs))
        return {"jobs": {"columns": ["role"]}}

    monkeypatch.setattr(registry, "get_data_source_schema", native_schema)

    class Custom(RegistrySeam):
        def get_data_source_schema(self, *args: Any, **kwargs: Any) -> Any:
            return schema(*args, **kwargs)

    seam = RegistrySeam(registry) if instance_override else Custom(registry)
    if instance_override:
        monkeypatch.setattr(seam, "get_data_source_schema", schema)
    client = CaptureClient()
    assert NL2SQLOperator().apply([[]], ATTRS, {"data_registry": seam, "llm_client": client}) == [
        [{"sql": "SELECT 1 AS n"}]
    ]
    assert native_calls == []
    assert seam_calls == [(TARGET, {})]
    assert client.schemas == [
        {"entities": [{"name": "jobs", "attributes": {"role": {}}}], "relations": []}
    ]


def test_host_native_schema_override_projects_after_preflight(
    registry: Any, monkeypatch: pytest.MonkeyPatch
):
    calls: list[Any] = []
    columns = ["customer_id", "tenant_id"]
    target_columns = ["id", "tenant_id"]

    def schema(source: str, database: str, collection: str, format: str = "dict"):
        calls.append((source, database, collection, format))
        return {
            "entities": [{"name": "jobs", "attributes": {"role": {"samples": "PRIVATE_MARKER"}}}],
            "relations": [
                {
                    "name": "jobs_fk",
                    "source_entity": "jobs",
                    "target_entity": "customers",
                    "foreign_keys_source_columns": columns,
                    "foreign_keys_target_columns": target_columns,
                    "connection": "PRIVATE_MARKER",
                }
            ],
            "metadata": "PRIVATE_MARKER",
        }

    monkeypatch.setattr(registry, "get_data_source_schema", schema)
    executor = ReadOnlySQLExecutor(registry, frozenset({TARGET}))
    with pytest.raises(LLMError) as denied:
        executor.get_schema(("demo", "db", "unrelated"))
    assert denied.value.code == "sql_target_denied"
    assert calls == []
    client = CaptureClient()
    op = NL2SQLOperator(read_only_executor=executor)
    props = {"llm_client": client, "execute_query": True}
    with pytest.raises(LLMError) as invalid:
        op.apply([[]], ATTRS, props | {"data_registry": registry})
    assert invalid.value.code == "sql_policy_invalid"
    assert calls == []
    assert client.schemas == []
    assert op.apply([[]], ATTRS, props) == [[{"n": 1}]]
    assert calls == [(*TARGET, "dict")]
    assert client.schemas == [
        {
            "entities": [{"name": "jobs", "attributes": {"role": {}}}],
            "relations": [
                {
                    "name": "jobs_fk",
                    "source_entity": "jobs",
                    "target_entity": "customers",
                    "foreign_keys_source_columns": ["customer_id", "tenant_id"],
                    "foreign_keys_target_columns": ["id", "tenant_id"],
                }
            ],
        }
    ]
    columns.append("later")
    target_columns.append("later")
    assert client.schemas[0]["relations"][0]["foreign_keys_source_columns"] == [
        "customer_id",
        "tenant_id",
    ]
    assert client.schemas[0]["relations"][0]["foreign_keys_target_columns"] == ["id", "tenant_id"]
    assert "PRIVATE_MARKER" not in json.dumps(client.schemas)


@pytest.mark.parametrize("host_bound", [False, True])
@pytest.mark.parametrize("raises", [False, True])
def test_native_schema_override_fails_closed(
    registry: Any, monkeypatch: pytest.MonkeyPatch, host_bound: bool, raises: bool
):
    calls: list[Any] = []

    def schema(source: str, database: str, collection: str, format: str = "dict"):
        calls.append((source, database, collection, format))
        if raises:
            raise RuntimeError("PRIVATE_MARKER")
        return {"metadata": "PRIVATE_MARKER"}

    monkeypatch.setattr(registry, "get_data_source_schema", schema)
    client = CaptureClient()
    executor = ReadOnlySQLExecutor(registry, frozenset({TARGET})) if host_bound else None
    op = NL2SQLOperator(read_only_executor=executor)
    props: dict[str, Any] = {"execute_query": True} if host_bound else {"data_registry": registry}
    props["llm_client"] = client
    with pytest.raises(LLMError) as error:
        op.apply([[]], ATTRS, props)
    assert error.value.code == "sql_execution_failed"
    assert str(error.value) == "read-only SQL execution failed"
    assert calls == [(*TARGET, "dict")]
    output, _, meta = op.run([[]], ATTRS, props)
    assert output == [[]]
    assert len(meta.errors) == 1
    assert meta.errors[0].message == "read-only SQL execution failed"
    assert "PRIVATE_MARKER" not in str(meta.errors)
    assert calls == [(*TARGET, "dict"), (*TARGET, "dict")]
    assert client.schemas == []


@pytest.mark.parametrize("signature", ["named", "renamed", "positional_only"])
@pytest.mark.parametrize("instance_override", [False, True])
def test_host_native_schema_preserves_three_argument_callbacks(
    registry: Any, monkeypatch: pytest.MonkeyPatch, signature: str, instance_override: bool
):
    from types import MethodType

    calls: list[tuple[str, str, str]] = []

    def record(a: str, b: str, c: str) -> dict[str, Any]:
        calls.append((a, b, c))
        return {"jobs": {"columns": ["role"]}}

    def named(self: Any, source: str, database: str, collection: str) -> dict[str, Any]:
        return record(source, database, collection)

    def renamed(self: Any, a: str, b: str, c: str) -> dict[str, Any]:
        return record(a, b, c)

    def positional_only(self: Any, a: str, b: str, c: str, /) -> dict[str, Any]:
        return record(a, b, c)

    class Custom(DataRegistry):
        pass

    schema = {"named": named, "renamed": renamed, "positional_only": positional_only}[signature]
    native: Any = Custom(store=MemoryJSONSource(), rebuild=False)
    native.register_source(registry.get_source("demo"))
    if instance_override:
        monkeypatch.setattr(native, "get_data_source_schema", MethodType(schema, native))
    else:
        monkeypatch.setattr(Custom, "get_data_source_schema", schema)
    executor = ReadOnlySQLExecutor(native, frozenset({TARGET}))
    with pytest.raises(LLMError) as denied:
        executor.get_schema(("demo", "db", "unrelated"))
    assert denied.value.code == "sql_target_denied"
    assert calls == []
    client = CaptureClient()
    result, _, meta = NL2SQLOperator(read_only_executor=executor).run(
        [[]], ATTRS, {"llm_client": client, "execute_query": True}
    )
    assert not meta.errors
    assert result == [[{"n": 1}]]
    assert calls == [TARGET]
    assert client.schemas == [
        {"entities": [{"name": "jobs", "attributes": {"role": {}}}], "relations": []}
    ]


@pytest.mark.parametrize("signature", ["named", "renamed", "positional_only"])
@pytest.mark.parametrize("instance_override", [False, True])
def test_seam_schema_preserves_three_argument_callbacks(
    registry: Any, monkeypatch: pytest.MonkeyPatch, signature: str, instance_override: bool
):
    from types import MethodType

    calls: list[tuple[str, str, str]] = []

    def record(a: str, b: str, c: str) -> dict[str, Any]:
        calls.append((a, b, c))
        return {"jobs": {"columns": ["role"]}}

    def named(self: Any, source: str, database: str, collection: str) -> dict[str, Any]:
        return record(source, database, collection)

    def renamed(self: Any, a: str, b: str, c: str) -> dict[str, Any]:
        return record(a, b, c)

    def positional_only(self: Any, a: str, b: str, c: str, /) -> dict[str, Any]:
        return record(a, b, c)

    class Custom(RegistrySeam):
        pass

    schema = {"named": named, "renamed": renamed, "positional_only": positional_only}[signature]
    seam: Any = Custom(registry)
    if instance_override:
        monkeypatch.setattr(seam, "get_data_source_schema", MethodType(schema, seam))
    else:
        monkeypatch.setattr(Custom, "get_data_source_schema", schema)
    client = CaptureClient()
    result, _, meta = NL2SQLOperator().run(
        [[]], ATTRS, {"llm_client": client, "data_registry": seam}
    )
    assert not meta.errors
    assert result == [[{"sql": "SELECT 1 AS n"}]]
    assert calls == [TARGET]
    assert client.schemas == [
        {"entities": [{"name": "jobs", "attributes": {"role": {}}}], "relations": []}
    ]

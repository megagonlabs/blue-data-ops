"""Integration contract for RegistrySeam against blue-data.

Covers indexing behavior and its negative control, delegation round-trips on a memory
store, a temporary SQLite source, the record listings the planning data context reads,
and the dependency methods used by the facade.

Source pin: blue-data `1b796fe911c1c94b683f72b8d0881e3252d4447c`. Against the previous
`0eac5d3` pin the three direct-read methods are byte-identical; `execute_query_nl_tools`
and `export_data` are new and deliberately unused here; `connect_source()` now requires
stored `_class` provenance to rehydrate a persisted source.
"""

# blue-data ships no py.typed:
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, cast

import pytest

blue_data = pytest.importorskip("blue_data")

from blue_data.registry.data_registry import DataRegistry  # noqa: E402
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource  # noqa: E402
from blue_data.source.vector.memory_vector_source import MemoryVectorSource  # noqa: E402

from blue_data_ops.data import RegistrySeam  # noqa: E402
from blue_data_ops.data.errors import RegistryFailure, RegistryReason  # noqa: E402
from blue_data_ops.data.registry_seam import (  # noqa: E402
    _diagnose_source,  # pyright: ignore[reportPrivateUsage]
)


def _stub_embedding(texts: list[str]) -> list[list[float]]:
    return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


def _vector_registry(rebuild: bool) -> tuple[RegistrySeam, MemoryVectorSource]:
    vector_source = MemoryVectorSource("vs")
    registry = DataRegistry(
        name="contract_registry",
        vector_source=vector_source,
        embedding_fn=_stub_embedding,
        rebuild=rebuild,
        vector_dim=4,
    )
    registry.register_source(_memory_sql_stub("src"))
    return RegistrySeam(registry), vector_source


def _memory_sql_stub(name: str) -> Any:
    # A stateful stub source: create_source_database's post-create sync_source
    # reconciles the registry against fetch_databases(), so created databases must be
    # reported back (and sync descends into new databases).
    class _Stub:
        def __init__(self, stub_name: str) -> None:
            self.name = stub_name
            self.properties: dict[str, Any] = {"connection": {"protocol": "memory"}}
            self.databases: list[str] = []

        def create_database(self, database: str, **_kwargs: Any) -> dict[str, str]:
            self.databases.append(database)
            return {"status": "success"}

        def fetch_databases(self) -> list[str]:
            return list(self.databases)

        def fetch_metadata(self) -> dict[str, Any]:
            return {}

        def fetch_database_metadata(self, database: str) -> dict[str, Any]:
            return {}

        def fetch_database_collections(self, database: str) -> list[str]:
            return []

    return _Stub(name)


def _index_size(vector_source: MemoryVectorSource) -> int:
    # MemoryVectorSource._store is keyed first by collection and then by document ID,
    # so the index size is the number of nested documents, not collections.
    store: dict[str, dict[str, Any]] = getattr(vector_source, "_store")
    return sum(len(docs) for docs in store.values())


# --- Rebuild-sensitive indexing ----------------------------------------------------- #
def test_create_with_rebuild_true_instance_indexes_records() -> None:
    seam, vector_source = _vector_registry(rebuild=True)
    baseline = _index_size(vector_source)
    seam.create_source_database("src", "db1", properties={}, overwrite=False, rebuild=True)
    assert _index_size(vector_source) > baseline  # membership IN THE INDEX, not search


def test_create_emulates_rebuild_for_rebuild_false_instance() -> None:
    # A per-call rebuild request must populate the index even when the injected
    # registry was constructed with rebuild disabled.
    seam, vector_source = _vector_registry(rebuild=False)
    baseline = _index_size(vector_source)
    seam.create_source_database("src", "db2", properties={}, overwrite=False, rebuild=True)
    assert _index_size(vector_source) > baseline


def test_negative_control_no_emulation_leaves_index_empty() -> None:
    # With rebuild disabled both on the registry and the call, the same flow must not
    # populate the index.
    seam, vector_source = _vector_registry(rebuild=False)
    baseline = _index_size(vector_source)
    seam.create_source_database("src", "db3", properties={}, overwrite=False, rebuild=False)
    assert _index_size(vector_source) == baseline


# --- Delegation round-trips on a memory store -------------------------------------- #
def test_describe_record_data_get_record_roundtrip() -> None:
    seam = RegistrySeam(DataRegistry(name="rt", rebuild=True))
    seam.register_source(_memory_sql_stub("src"))
    seam.create_source_database("src", "db", properties={}, overwrite=False, rebuild=True)
    seam.set_source_database_description("src", "db", "a database", rebuild=True)
    seam.set_record_data(
        name="db", type="database", scope="/source/src", key="created_by", value="ops", rebuild=True
    )
    record = seam.get_record("db", "database", "/source/src")
    assert record is not None
    assert seam.get_source_properties("src")["connection"]["protocol"] == "memory"


# --- Temporary SQLite source -------------------------------------------------------- #
def test_sqlite_returned_source_private_protocol(tmp_path: Path) -> None:
    seam = RegistrySeam(DataRegistry(name="sql", rebuild=True))
    source = SQLiteDBSource(
        "sqlite_src",
        properties={"connection": {"protocol": "sqlite", "database_directory": str(tmp_path)}},
    )
    seam.register_source(source)

    connected = seam.connect_source("sqlite_src")
    assert connected is source  # registered sources are returned directly

    connected.create_database("smoke")
    db_connection = connected._db_connect("smoke")
    cursor = db_connection.cursor()
    cursor.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    cursor.executemany("INSERT INTO t VALUES (?, ?)", [(1, "x"), (2, "y")])
    db_connection.commit()
    assert cursor.rowcount == 2
    connected._db_disconnect(db_connection)
    assert (tmp_path / "smoke.db").exists()


# --- Dependency method contracts ---------------------------------------------------- #
EXPECTED_PARAMS = {
    "create_source_database": ["source", "database", "properties", "overwrite", "recursive"],
    "create_source_database_collection_entity": [
        "source",
        "database",
        "collection",
        "entity",
        "properties",
        "creation_properties",
        "overwrite",
        "recursive",
    ],
    "set_source_database_description": ["source", "database", "description", "rebuild"],
    "set_source_database_collection_entity_description": [
        "source",
        "database",
        "collection",
        "entity",
        "description",
        "rebuild",
    ],
    "set_record_data": ["name", "type", "scope", "key", "value", "rebuild"],
    "get_record": ["name", "type", "scope"],
    "get_source_properties": ["source"],
    "connect_source": ["source"],
    "register_source": ["source"],
    "list_collection_entities": ["source", "database", "collection"],
    "list_entity_attributes": ["source", "database", "collection", "entity"],
}


@pytest.mark.parametrize("method_name", sorted(EXPECTED_PARAMS))
def test_blue_data_method_signatures(method_name: str) -> None:
    method = getattr(DataRegistry, method_name)
    parameters = [p for p in inspect.signature(method).parameters if p != "self"]
    assert parameters == EXPECTED_PARAMS[method_name]


# --- Record listings used by the planning data context ------------------------------ #
def test_record_listings_delegate_positionally(tmp_path: Path) -> None:
    class _Recorder:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

        def list_collection_entities(self, *args: Any, **kwargs: Any) -> list[Any]:
            self.calls.append(("list_collection_entities", args, kwargs))
            return []

        def list_entity_attributes(self, *args: Any, **kwargs: Any) -> list[Any]:
            self.calls.append(("list_entity_attributes", args, kwargs))
            return []

    del tmp_path
    recorder = _Recorder()
    seam = RegistrySeam(cast(Any, recorder))

    assert seam.list_collection_entities("src", "db", "col") == []
    assert seam.list_entity_attributes("src", "db", "col", "ent") == []
    assert recorder.calls == [
        ("list_collection_entities", ("src", "db", "col"), {}),
        ("list_entity_attributes", ("src", "db", "col", "ent"), {}),
    ]


def test_record_listings_return_registered_entity_and_attribute_records(tmp_path: Path) -> None:
    # The direct-read path the planning data context uses. It returns the raw records,
    # including the fields the context projection is required to drop.
    seam = RegistrySeam(DataRegistry(name="listings", rebuild=True))
    source = SQLiteDBSource(
        "listing_src",
        properties={"connection": {"database_directory": str(tmp_path)}},
    )
    seam.register_source(source)
    seam.create_source_database("listing_src", "db", overwrite=True)
    seam.create_source_database_collection_entity(
        "listing_src",
        "db",
        "public",
        "orders",
        creation_properties={
            "cols_definition": [
                {"name": "order_id", "type": "INTEGER"},
                {"name": "total", "type": "REAL"},
            ],
            "primary_key": ["order_id"],
        },
        overwrite=True,
    )

    entities = seam.list_collection_entities("listing_src", "db", "public")
    attributes = seam.list_entity_attributes("listing_src", "db", "public", "orders")

    assert [record["name"] for record in entities] == ["orders"]
    assert {record["name"] for record in attributes} == {"order_id", "total"}
    assert {record["properties"]["info"]["type"] for record in attributes} == {"INTEGER", "REAL"}
    assert "created_by" in entities[0]
    assert seam.list_collection_entities("listing_src", "db", "absent") == []


def test_source_properties_report_the_protocol_the_source_declares() -> None:
    # The planning data context copies connection.protocol verbatim, so what matters is
    # that the seam reports exactly what the source declares. The literal itself is a
    # blue-data detail that has changed across commits, so it is not pinned here.
    seam = RegistrySeam(DataRegistry(name="protocol_probe", rebuild=True))
    source = SQLiteDBSource("protocol_src", properties={"connection": {}})
    properties: dict[str, Any] = getattr(source, "properties")
    declared = properties["connection"]["protocol"]
    seam.register_source(source)

    assert isinstance(declared, str) and declared
    assert seam.get_source_properties("protocol_src")["connection"]["protocol"] == declared


# --- connect_source provenance: newly created versus previously persisted ----------- #
def _store_of(registry: DataRegistry) -> Any:
    return getattr(registry, "store")


def _persisted_orders_registry(tmp_path: Path) -> DataRegistry:
    registry = DataRegistry(name="seam_persisted", rebuild=True)
    seam = RegistrySeam(registry)
    seam.register_source(
        SQLiteDBSource(
            "persist_src", properties={"connection": {"database_directory": str(tmp_path)}}
        )
    )
    seam.create_source_database("persist_src", "db", overwrite=True)
    seam.create_source_database_collection_entity(
        "persist_src",
        "db",
        "public",
        "orders",
        creation_properties={
            "cols_definition": [{"name": "order_id", "type": "INTEGER"}],
            "primary_key": ["order_id"],
        },
        overwrite=True,
    )
    return registry


def test_connect_source_returns_the_live_object_for_a_newly_created_record(
    tmp_path: Path,
) -> None:
    registry = _persisted_orders_registry(tmp_path)
    seam = RegistrySeam(registry)

    connected = seam.connect_source("persist_src")

    assert connected is registry.sources["persist_src"]


def test_connect_source_rehydrates_a_persisted_record_from_class_provenance(
    tmp_path: Path,
) -> None:
    # A second registry over the same store models a previously persisted record: no
    # source object exists until connect_source() instantiates one from `_class`.
    registry = _persisted_orders_registry(tmp_path)
    reopened = DataRegistry(name="seam_persisted", store=_store_of(registry), rebuild=False)
    assert reopened.sources == {}
    seam = RegistrySeam(reopened)

    assert seam.get_source_properties("persist_src")["_class"].endswith("SQLiteDBSource")
    connected = seam.connect_source("persist_src")

    assert isinstance(connected, SQLiteDBSource)
    assert list(reopened.sources) == ["persist_src"]


def test_connect_source_fails_for_a_persisted_record_without_class_provenance(
    tmp_path: Path,
) -> None:
    registry = _persisted_orders_registry(tmp_path)
    reopened = DataRegistry(name="seam_persisted", store=_store_of(registry), rebuild=False)
    seam = RegistrySeam(reopened)
    cast("dict[str, Any]", seam.get_source_properties("persist_src")).pop("_class", None)

    with pytest.raises(ValueError):
        seam.connect_source("persist_src")
    with pytest.raises(RegistryFailure, match="data source is unavailable") as caught:
        _diagnose_source(seam, "persist_src")
    assert caught.value.reason is RegistryReason.SOURCE_UNAVAILABLE
    assert reopened.sources == {}

    # The record listings the planning data context uses are unaffected either way.
    assert [r["name"] for r in seam.list_collection_entities("persist_src", "db", "public")] == [
        "orders"
    ]


def test_record_listings_agree_for_newly_created_and_persisted_records(tmp_path: Path) -> None:
    registry = _persisted_orders_registry(tmp_path)
    fresh = RegistrySeam(registry)
    persisted = RegistrySeam(DataRegistry(name="seam_persisted", store=_store_of(registry)))

    for seam in (fresh, persisted):
        assert [
            r["name"] for r in seam.list_collection_entities("persist_src", "db", "public")
        ] == ["orders"]
        assert [
            r["name"] for r in seam.list_entity_attributes("persist_src", "db", "public", "orders")
        ] == ["order_id"]


# --- Query argument translation ----------------------------------------------------- #
def test_execute_query_translates_argument_order() -> None:
    # Distinct values make an argument-order regression visible: the facade receives
    # (query, source) and delegates blue-data's (source=..., query=...) keywords.
    class _Recorder:
        def __init__(self) -> None:
            self.kwargs: dict[str, Any] = {}

        def execute_query(self, **kwargs: Any) -> str:
            self.kwargs = kwargs
            return "rows"

    recorder = _Recorder()
    seam = RegistrySeam(cast(Any, recorder))
    out = seam.execute_query("SELECT 1", "my_source", database="db", collection="c")
    assert out == "rows"
    assert recorder.kwargs == {
        "source": "my_source",
        "query": "SELECT 1",
        "database": "db",
        "collection": "c",
        "optional_properties": {},
    }


@pytest.mark.parametrize("optional_properties", [{}, None])
def test_execute_query_optional_properties_normalization(
    optional_properties: dict[str, Any] | None,
) -> None:
    # blue-data normalizes optional_properties with `x or {}`, so both {} and None are
    # safe pass-through values.
    class _Recorder:
        def __init__(self) -> None:
            self.kwargs: dict[str, Any] = {}

        def execute_query(self, **kwargs: Any) -> list[Any]:
            self.kwargs = kwargs
            return []

    recorder = _Recorder()
    seam = RegistrySeam(cast(Any, recorder))
    seam.execute_query("q", "s", optional_properties=optional_properties)
    assert recorder.kwargs["optional_properties"] == optional_properties


def test_execute_query_blue_data_signature() -> None:
    # Assert blue-data's parameter order so dependency drift fails loudly.
    method: Any = cast(
        Any,
        DataRegistry.execute_query,  # pyright: ignore[reportUnknownMemberType]
    )
    parameters = [p for p in inspect.signature(method).parameters if p != "self"]
    assert parameters[:2] == ["source", "query"]
    assert parameters[2:] == ["database", "collection", "optional_properties"]


# --- Schema protocol handling ------------------------------------------------------- #
def test_get_data_source_schema_drops_protocol() -> None:
    # The facade keeps the caller-supplied protocol parameter; the delegate derives
    # protocol from source properties and has no such parameter — it must never be
    # forwarded, whatever the caller passes.
    class _Recorder:
        def __init__(self) -> None:
            self.kwargs: dict[str, Any] = {}

        def get_data_source_schema(self, **kwargs: Any) -> dict[str, Any]:
            self.kwargs = kwargs
            return {"entities": [], "relations": []}

    recorder = _Recorder()
    seam = RegistrySeam(cast(Any, recorder))
    out = seam.get_data_source_schema("my_source", "db", "c", "bn", format="dict")
    assert out == {"entities": [], "relations": []}
    assert recorder.kwargs == {
        "source": "my_source",
        "database": "db",
        "collection": "c",
        "format": "dict",
    }


def test_get_data_source_schema_blue_data_signature() -> None:
    # blue-data derives protocol from source connection properties and therefore has
    # no protocol parameter. A signature change requires revisiting this translation.
    method: Any = cast(
        Any,
        DataRegistry.get_data_source_schema,  # pyright: ignore[reportUnknownMemberType]
    )
    parameters = [p for p in inspect.signature(method).parameters if p != "self"]
    assert parameters == ["source", "database", "collection", "format"]


def test_get_data_source_schema_real_shapes() -> None:
    # The facade preserves an empty schema for an unknown source; the owned check fails.
    # A bn-protocol source reports graph_structure at the top level rather than under metadata.
    seam = RegistrySeam(DataRegistry(name="schema_probe", rebuild=True))
    assert seam.get_data_source_schema("absent", "db", "c") == {"entities": [], "relations": []}
    with pytest.raises(RegistryFailure) as caught:
        _diagnose_source(seam, "absent")
    assert caught.value.reason is RegistryReason.SOURCE_NOT_REGISTERED

    bn_source = _memory_sql_stub("bn_src")
    bn_source.properties = {"connection": {"protocol": "bn"}}
    seam.register_source(bn_source)
    schema = seam.get_data_source_schema("bn_src", "db", "c", "bn")
    assert "graph_structure" in schema  # top-level, the shape consumers must fall back to
    assert "metadata" not in schema

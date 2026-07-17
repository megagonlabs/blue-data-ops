"""Integration contract for RegistrySeam against blue-data.

Covers indexing behavior and its negative control, delegation round-trips on a memory
store, a temporary SQLite source, and the dependency methods used by the facade.
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
}


@pytest.mark.parametrize("method_name", sorted(EXPECTED_PARAMS))
def test_blue_data_method_signatures(method_name: str) -> None:
    method = getattr(DataRegistry, method_name)
    parameters = [p for p in inspect.signature(method).parameters if p != "self"]
    assert parameters == EXPECTED_PARAMS[method_name]


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
    # An unknown source resolves to an empty entity/relation schema. A bn-protocol
    # source reports graph_structure at the top level rather than under metadata.
    seam = RegistrySeam(DataRegistry(name="schema_probe", rebuild=True))
    assert seam.get_data_source_schema("absent", "db", "c") == {"entities": [], "relations": []}

    bn_source = _memory_sql_stub("bn_src")
    bn_source.properties = {"connection": {"protocol": "bn"}}
    seam.register_source(bn_source)
    schema = seam.get_data_source_schema("bn_src", "db", "c", "bn")
    assert "graph_structure" in schema  # top-level, the shape consumers must fall back to
    assert "metadata" not in schema

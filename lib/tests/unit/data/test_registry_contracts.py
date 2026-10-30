from __future__ import annotations

import hashlib
import importlib.util
import json
from collections.abc import Callable
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any, cast

import pytest
from blue_data.registry.data_registry import DataRegistry
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource

from blue_data_ops.data import RegistrySeam, registry_seam, resolve_registry
from blue_data_ops.data.errors import RegistryFailure, RegistryReason
from blue_data_ops.llm import LLMClient
from blue_data_ops.operators import versioned_registry

_diagnose_source = cast(Any, registry_seam)._diagnose_source

_BASELINE_COMMIT = "7b4b111b722442e1852133f4042d02e42eda68f6"
_BASELINE_MANIFEST_SHA256 = "1887d4be7710cff2fe46e2baef7e129ceb3fede287bae78a18db592881c65aa7"
_BASELINE_ROOT = Path(__file__).resolve().parents[2] / "fixtures/registry_compatibility_baseline"


def baseline_class(relative: str, name: str) -> Any:
    manifest_bytes = (_BASELINE_ROOT / "manifest.json").read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != _BASELINE_MANIFEST_SHA256:
        raise ValueError("baseline manifest digest mismatch")
    manifest = json.loads(manifest_bytes)
    if manifest["source_commit"] != _BASELINE_COMMIT:
        raise ValueError("baseline commit mismatch")
    paths: dict[str, Path] = {}
    for entry in manifest["files"]:
        path = _BASELINE_ROOT / entry["fixture_path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("baseline fixture digest mismatch")
        paths[entry["source_path"]] = path
    loader = SourceFileLoader("original_" + name, str(paths[relative]))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, name)


def source(registry: Any, directory: Path) -> Any:
    live = SQLiteDBSource(
        "local", properties={"connection": {"database_directory": str(directory)}}
    )
    registry.register_source(live)
    return live


def observe(call: Any) -> Any:
    try:
        return "return", call()
    except Exception as error:
        return "raise", type(error).__name__, str(error)


CALLS: list[Callable[[Any], Any]] = [
    lambda seam: seam.connect_source("local"),
    lambda seam: seam.get_data_source_schema("local", "db", "public", "ignored"),
    lambda seam: seam.get_data_source_schema("local", "db", "public", format="json"),
    lambda seam: seam.get_data_source_schema("local", "db", "public", format="yaml"),
    lambda seam: seam.execute_query("SELECT 1", "local", "db", "public", None),
    lambda seam: seam.create_source_database("local", "db", rebuild=True),
    lambda seam: seam.create_source_database_collection_entity(
        "local", "db", "public", "items", rebuild=True
    ),
]


@pytest.mark.parametrize(
    "state",
    ["absent", "malformed", "unavailable", "live", "lazy", "backend_failure", "malformed_nonempty"],
)
@pytest.mark.parametrize("call", CALLS)
def test_facade_matches_original_calls_and_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str, call: Any
) -> None:
    original = baseline_class("lib/src/blue_data_ops/data/registry_seam.py", "RegistrySeam")
    observations: list[Any] = []
    for cls in (original, RegistrySeam):
        registry: Any = DataRegistry(rebuild=False)
        if state in {"live", "lazy"}:
            source(registry, tmp_path)
            if state == "lazy":
                registry.sources.clear()
        elif state != "absent":
            properties = {} if state == "malformed" else {"status": "unavailable"}
            if state == "malformed_nonempty":
                properties = {"connection": {"protocol": "sqlite"}}
            registry.register_record("local", "source", "/", properties=properties)
        trace: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        for name in (
            "connect_source",
            "get_source",
            "get_source_record",
            "get_source_properties",
            "get_data_source_schema",
            "execute_query",
            "create_source_database",
            "create_source_database_collection_entity",
            "build_index",
        ):
            bound = getattr(registry, name)

            def record(*args: Any, _name: str = name, _bound: Any = bound, **kwargs: Any) -> Any:
                trace.append((_name, args, kwargs))
                if state == "backend_failure" and _name == "get_source_properties":
                    raise PermissionError("synthetic backend detail")
                if _name.startswith("create_source_") or _name == "execute_query":
                    if state in {"live", "lazy"}:
                        registry.connect_source("local")
                        return []
                return _bound(*args, **kwargs)

            monkeypatch.setattr(registry, name, record)
        result = observe(lambda: call(cls(registry)))
        if result[0] == "return" and isinstance(result[1], SQLiteDBSource):
            result = ("return", "live-source")
        observations.append((result, trace, sorted(registry.sources)))
    assert observations[0] == observations[1]


def test_absent_facade_return_contract() -> None:
    seam = RegistrySeam(DataRegistry(rebuild=False))
    assert seam.connect_source("absent") is None
    assert seam.get_data_source_schema("absent", "db", "public") == {
        "entities": [],
        "relations": [],
    }
    for call in CALLS[4:]:
        with pytest.raises(ValueError):
            call(seam)


@pytest.mark.parametrize("state", ["absent", "malformed", "unavailable", "lazy", "live"])
def test_owned_check_moves_strict_state_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    registry: Any = DataRegistry(rebuild=False)
    seam = RegistrySeam(registry)
    if state in {"live", "lazy"}:
        source(registry, tmp_path)
        if state == "lazy":
            registry.sources.clear()
    elif state != "absent":
        registry.register_record(
            "local",
            "source",
            "/",
            properties={} if state == "malformed" else {"status": "unavailable"},
        )
    if state in {"absent", "malformed", "unavailable"}:

        def deny(*args: Any, **kwargs: Any) -> Any:
            pytest.fail("invalid source was restored")

        monkeypatch.setattr(registry, "connect_source", deny)
        with pytest.raises(RegistryFailure) as caught:
            _diagnose_source(seam, "local")
        expected = (
            RegistryReason.SOURCE_NOT_REGISTERED
            if state == "absent"
            else RegistryReason.SOURCE_UNAVAILABLE
        )
        assert caught.value.reason is expected
        assert "local" not in str(caught.value)
    else:
        assert _diagnose_source(seam, "local") is registry.sources["local"]
        assert isinstance(registry.sources["local"], SQLiteDBSource)


class Reply(LLMClient):
    def __init__(self, bn: bool = False):
        self.calls = 0
        self.bn = bn

    def execute_api_call(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        if self.bn:
            return {"target_node": "x", "target_state": "yes", "context": {}}
        return {"query": "SELECT 1"}


def attrs(name: str) -> dict[str, Any]:
    return {
        "source": "local",
        "database": "db",
        "collection": "public",
        "table": "items",
        "columns": [{"name": "id", "type": "INTEGER"}],
        "question": "query",
        "protocol": "sqlite",
        "protocol_variant": "pgmpy",
        **({"schema": "supplied schema"} if name == "nl2bn" else {}),
    }


@pytest.mark.parametrize(
    "identity",
    [
        "nl2sql@1.0.0",
        "nl2sql@2.0.0",
        "nl2sql@3.0.0",
        "nl2bn@1.0.0",
        "nl2bn@2.0.0",
        "nl2bn@3.0.0",
        "insert_table@1.0.0",
        "insert_table@2.0.0",
        "insert_table@3.0.0",
        "create_database@1.0.0",
        "create_database@2.0.0",
        "create_table@1.0.0",
        "create_table@2.0.0",
    ],
)
@pytest.mark.parametrize("state", ["absent", "malformed", "unavailable"])
def test_canonical_missing_source_no_model_or_store_effects(
    tmp_path: Path, identity: str, state: str
):
    name = identity.split("@")[0]
    registry: Any = DataRegistry(rebuild=False)
    source(registry, tmp_path)
    target = attrs(name)
    target["source"] = "absent"
    if state != "absent":
        registry.register_record(
            "absent",
            "source",
            "/",
            properties={} if state == "malformed" else {"status": "unavailable"},
        )
    before = json.dumps(registry.list_records(), sort_keys=True, default=str)
    client = Reply(name == "nl2bn")
    data = [[{"id": 1}]]
    result = (
        versioned_registry()
        .resolve(identity)
        .run(data, target, {"data_registry": registry, "llm_client": client})
    )
    expected = (
        "data source is not registered" if state == "absent" else "data source is unavailable"
    )
    assert result[2].errors[0].message == expected
    assert result[2].errors[0].retryable is False
    assert client.calls == 0
    assert list(tmp_path.iterdir()) == []
    assert json.dumps(registry.list_records(), sort_keys=True, default=str) == before


@pytest.mark.parametrize("identity", ["nl2sql@2.0.0", "nl2sql@3.0.0", "nl2bn@2.0.0", "nl2bn@3.0.0"])
def test_custom_seam_identity_dispatch_and_empty_success(identity: str):
    class Custom(RegistrySeam):
        def __init__(self):
            self.calls: list[Any] = []

        def get_data_source_schema(self, *args: Any, **kwargs: Any) -> Any:
            self.calls.append("schema")
            return {"entities": [], "relations": []}

        def execute_query(self, *args: Any, **kwargs: Any) -> Any:
            self.calls.append("query")
            return []

    seam = Custom()
    props: dict[str, Any] = {"data_registry": seam, "llm_client": Reply("bn" in identity)}
    assert resolve_registry(props) is seam
    assert _diagnose_source(seam, "absent") is None
    assert seam.calls == []
    target = attrs(identity.split("@")[0])
    target.pop("schema", None)
    result = versioned_registry().resolve(identity).run([[]], target, props)
    assert not result[2].errors
    assert seam.calls == (["schema", "query"] if "bn" in identity else ["schema"])
    assert props["llm_client"].calls == 1


@pytest.mark.parametrize("identity", ["nl2sql@2.0.0", "nl2sql@3.0.0", "create_database@2.0.0"])
def test_lazy_canonical_restore_and_rebuild_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, identity: str
):
    registry: Any = DataRegistry(rebuild=False)
    source(registry, tmp_path)
    registry.sources.clear()
    original_connect = registry.connect_source
    counts = {"restore": 0, "rebuild": 0}

    def connect(name: str):
        if name not in registry.sources:
            counts["restore"] += 1
        return original_connect(name)

    def rebuild(*args: Any, **kwargs: Any) -> Any:
        counts["rebuild"] += 1

    monkeypatch.setattr(registry, "connect_source", connect)
    monkeypatch.setattr(registry, "build_index", rebuild)
    result = (
        versioned_registry()
        .resolve(identity)
        .run(
            [[]], attrs(identity.split("@")[0]), {"data_registry": registry, "llm_client": Reply()}
        )
    )
    # v3 generation may reject an absent database after the one historical restore.
    if identity != "nl2sql@3.0.0":
        assert not result[2].errors
    assert counts == {"restore": 1, "rebuild": int(identity.startswith("create"))}


@pytest.mark.parametrize(
    "name,cls_name",
    [
        ("insert_table", "InsertTableOperator"),
        ("create_database", "CreateDatabaseOperator"),
        ("create_table", "CreateTableOperator"),
        ("nl2bn", "NL2BNOperator"),
    ],
)
def test_raw_apply_original_dispatch_and_results(name: str, cls_name: str):
    original = baseline_class(f"lib/src/blue_data_ops/operators/{name}_operator.py", cls_name)
    observations: list[Any] = []
    for operator in (original(), versioned_registry().resolve(name + "@2.0.0")):

        class Custom(RegistrySeam):
            def __init__(self):
                self.calls: list[Any] = []

            def get_source_properties(self, *args: Any, **kwargs: Any) -> Any:
                self.calls.append(("properties", args, kwargs))
                return {}

            def connect_source(self, *args: Any, **kwargs: Any) -> Any:
                self.calls.append(("connect", args, kwargs))
                return None

            def create_source_database(self, *args: Any, **kwargs: Any) -> Any:
                self.calls.append(("create_database", args, kwargs))
                raise ValueError("absent")

            def create_source_database_collection_entity(self, *args: Any, **kwargs: Any) -> Any:
                self.calls.append(("create_table", args, kwargs))
                raise FileNotFoundError("foreign file")

            def execute_query(self, *args: Any, **kwargs: Any) -> Any:
                self.calls.append(("query", args, kwargs))
                return []

        seam = Custom()
        reply = Reply(True)
        result = observe(
            lambda: operator.apply(
                [[{"id": 1}]], attrs(name), {"data_registry": seam, "llm_client": reply}
            )
        )
        observations.append((result, seam.calls, reply.calls))
    assert observations[0] == observations[1]


def test_owned_metadata_failure_is_generic_without_model_work(monkeypatch: pytest.MonkeyPatch):
    registry: Any = DataRegistry(rebuild=False)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise PermissionError("synthetic backend detail")

    monkeypatch.setattr(registry, "get_source_record", broken)
    seam = RegistrySeam(registry)
    with pytest.raises(PermissionError):
        _diagnose_source(seam, "local")
    reply = Reply()
    result = (
        versioned_registry()
        .resolve("nl2sql@3.0.0")
        .run([[]], attrs("nl2sql"), {"data_registry": seam, "llm_client": reply})
    )
    assert result[2].errors[0].message == "operator execution failed"
    assert result[2].errors[0].retryable is False
    assert reply.calls == 0
    assert "synthetic backend detail" not in repr(result[2])


def test_genuine_empty_schema_and_query(tmp_path: Path):
    import sqlite3

    registry: Any = DataRegistry(rebuild=False)
    source(registry, tmp_path)
    seam = RegistrySeam(registry)
    seam.create_source_database("local", "db", rebuild=False)
    assert seam.get_data_source_schema("local", "db", "public") == {"entities": [], "relations": []}
    with sqlite3.connect(tmp_path / "db.db") as connection:
        connection.execute("CREATE TABLE items (id INTEGER)")
    assert seam.execute_query("SELECT * FROM items", "local", "db", "public") == []
    result = (
        versioned_registry()
        .resolve("nl2sql@3.0.0")
        .run([[]], attrs("nl2sql"), {"data_registry": registry, "llm_client": Reply()})
    )
    assert not result[2].errors


@pytest.mark.parametrize("identity", ["create_table@1.0.0", "create_table@2.0.0"])
def test_missing_sqlite_database_owned_boundary_and_raw_failure(tmp_path: Path, identity: str):
    registry: Any = DataRegistry(rebuild=False)
    source(registry, tmp_path)
    operator = versioned_registry().resolve(identity)
    data = [[{"id": 1}]]
    result = operator.run(data, attrs("create_table"), {"data_registry": registry})
    assert result[2].errors[0].message == "database does not exist"
    assert result[2].errors[0].retryable is False
    assert operator.apply(data, attrs("create_table"), {"data_registry": registry}) == data
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("state", ["missing_source", "missing_database", "no_registry"])
def test_raw_insert_outcome_keeps_original_exception_type(tmp_path: Path, state: str):
    registry: Any = DataRegistry(rebuild=False)
    if state == "missing_database":
        source(registry, tmp_path)
    props = {} if state == "no_registry" else {"data_registry": registry}
    operator = versioned_registry().resolve("insert_table@3.0.0")
    with pytest.raises(Exception) as caught:
        operator.apply([[{"id": 1}]], attrs("insert_table"), props)
    expected = FileNotFoundError if state == "missing_database" else RuntimeError
    assert type(caught.value) is expected
    assert list(tmp_path.iterdir()) == []


def test_custom_registry_check_skips_owned_inspection():
    class CustomRegistry(DataRegistry):
        def get_source(self, *args: Any, **kwargs: Any) -> Any:
            pytest.fail("custom registry was inspected")

        def connect_source(self, *args: Any, **kwargs: Any) -> Any:
            return None

    seam = RegistrySeam(CustomRegistry(rebuild=False))
    assert _diagnose_source(seam, "absent") is None
    assert seam.connect_source("absent") is None


def test_bn_facade_keeps_top_level_graph_shape():
    registry: Any = DataRegistry(rebuild=False)
    registry.register_record("bn", "source", "/", properties={"connection": {"protocol": "bn"}})
    schema = RegistrySeam(registry).get_data_source_schema("bn", "db", "public", "ignored")
    assert schema["graph_structure"] == {}
    assert "metadata" not in schema


def test_instance_custom_seam_method_keeps_dispatch(monkeypatch: pytest.MonkeyPatch):
    seam = RegistrySeam(DataRegistry(rebuild=False))
    calls: list[bool] = []

    def schema(*args: Any, **kwargs: Any) -> Any:
        calls.append(True)
        return {"entities": [], "relations": []}

    monkeypatch.setattr(seam, "get_data_source_schema", schema)
    assert _diagnose_source(seam, "absent") is None
    assert resolve_registry({"data_registry": seam}) is seam
    result = (
        versioned_registry()
        .resolve("nl2sql@2.0.0")
        .run([[]], attrs("nl2sql"), {"data_registry": seam, "llm_client": Reply()})
    )
    assert not result[2].errors
    assert calls == [True]


@pytest.mark.parametrize(
    "identity,method",
    [
        ("insert_table@2.0.0", "connect_source"),
        ("insert_table@3.0.0", "connect_source"),
        ("create_database@2.0.0", "create_source_database"),
        ("create_table@2.0.0", "create_source_database_collection_entity"),
    ],
)
def test_custom_write_seam_dispatch_is_preserved(identity: str, method: str):
    from tests.doubles.data import RegistrySeamDouble, SQLSourceDouble

    class Custom(RegistrySeamDouble, RegistrySeam):
        pass

    seam = Custom()
    seam.sources["local"] = SQLSourceDouble("local")
    assert _diagnose_source(seam, "local") is None
    result = (
        versioned_registry()
        .resolve(identity)
        .run([[{"id": 1}]], attrs(identity.split("@")[0]), {"data_registry": seam})
    )
    assert not result[2].errors
    assert len(seam.calls_to(method)) == 1


def test_missing_class_keeps_facade_metadata_and_owned_diagnosis(tmp_path: Path):
    registry: Any = DataRegistry(rebuild=False)
    source(registry, tmp_path)
    seam = RegistrySeam(registry)
    seam.create_source_database("local", "db", rebuild=False)
    seam.create_source_database_collection_entity(
        "local",
        "db",
        "public",
        "items",
        creation_properties={"cols_definition": [{"name": "id", "type": "INTEGER"}]},
        rebuild=False,
    )
    registry.sources.clear()
    seam.get_source_properties("local").pop("_class")
    before = json.dumps(registry.list_records(), sort_keys=True, default=str)
    with pytest.raises(ValueError):
        seam.connect_source("local")
    with pytest.raises(RegistryFailure) as caught:
        _diagnose_source(seam, "local")
    assert caught.value.reason is RegistryReason.SOURCE_UNAVAILABLE
    assert [row["name"] for row in seam.list_collection_entities("local", "db", "public")] == [
        "items"
    ]
    assert [
        row["name"] for row in seam.get_data_source_schema("local", "db", "public")["entities"]
    ] == ["items"]
    assert registry.sources == {}
    assert json.dumps(registry.list_records(), sort_keys=True, default=str) == before


@pytest.mark.parametrize(
    "identity",
    [
        "insert_table@2.0.0",
        "insert_table@3.0.0",
        "create_database@2.0.0",
        "create_table@2.0.0",
    ],
)
def test_missing_source_write_preserves_persisted_registry_and_sqlite(
    tmp_path: Path, identity: str
):
    import hashlib
    import sqlite3

    from blue_data.source.json.file_json_source import FileJSONSource

    directory = tmp_path / "databases"
    directory.mkdir()
    with sqlite3.connect(directory / "db.db") as connection:
        connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO items VALUES (1)")
    registry: Any = DataRegistry(
        store=FileJSONSource(properties={"connection": {"path": str(tmp_path / "registry.json")}}),
        rebuild=False,
    )
    source(registry, directory)
    registry.sync_source("local", recursive=True)

    def snapshot():
        return {
            p.relative_to(tmp_path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in tmp_path.rglob("*")
            if p.is_file()
        }

    before = snapshot()
    target = attrs(identity.split("@")[0])
    target["source"] = "absent"
    if identity.startswith("create_database"):
        target["database"] = "newdb"
    elif identity.startswith("create_table"):
        target["table"] = "newtable"
    result = (
        versioned_registry()
        .resolve(identity)
        .run([[{"id": 2}]], target, {"data_registry": registry})
    )
    assert result[2].errors[0].message == "data source is not registered"
    assert snapshot() == before
    with sqlite3.connect(directory / "db.db") as connection:
        assert connection.execute("SELECT id FROM items").fetchall() == [(1,)]

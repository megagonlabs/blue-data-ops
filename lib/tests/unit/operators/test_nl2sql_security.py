from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, Never, Protocol, cast

import pytest
from blue_data.registry.data_registry import DataRegistry  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.json.memory_json_source import MemoryJSONSource  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource  # pyright: ignore[reportMissingTypeStubs]

import blue_data_ops.llm.sql_execution as sql_execution
from blue_data_ops.llm import LLMError
from blue_data_ops.llm.sql_execution import ReadOnlySQLExecutor
from blue_data_ops.operators import NL2SQLOperator, OperatorRegistry, versioned_registry
from blue_data_ops.operators.types import DataBundle, Properties
from tests.unit.operators.test_v2_llm_nl2 import ScriptedClient

_GUARDED_METHODS = cast(frozenset[str], vars(sql_execution)["_GUARDED_METHODS"])


class _Patch(Protocol):
    def setattr(self, target: object, name: str, value: Callable[..., Any]) -> None: ...


class _Connect(Protocol):
    def __call__(self, **kwargs: Any) -> object: ...


class _ConnectPatch(Protocol):
    def setattr(self, target: object, name: str, value: _Connect) -> None: ...


ATTRS = {
    "source": "approved",
    "database": "db",
    "collection": "public",
    "protocol": "sqlite",
    "question": "list rows",
}
TARGET = ("approved", "db", "public")
Host = tuple[DataRegistry, SQLiteDBSource, ReadOnlySQLExecutor]


@pytest.fixture
def host(tmp_path: Path) -> Host:
    with sqlite3.connect(tmp_path / "db.db") as conn:
        conn.execute("CREATE TABLE records (id INTEGER, value TEXT)")
        conn.execute("INSERT INTO records VALUES (1, 'synthetic')")
    registry = DataRegistry(store=MemoryJSONSource(), rebuild=False)
    source = SQLiteDBSource(
        "approved", properties={"connection": {"database_directory": str(tmp_path)}}
    )
    registry.register_source(source)
    executor = ReadOnlySQLExecutor(registry, frozenset({TARGET}))
    return registry, source, executor


def execute(executor: ReadOnlySQLExecutor, query: Any, version: str | None = None) -> DataBundle:
    op = NL2SQLOperator(read_only_executor=executor)
    if version:
        registry = OperatorRegistry()
        registry.register(op, version=version)
        op = cast(NL2SQLOperator, registry.resolve("nl2sql@" + version))
    client = ScriptedClient([{"query": query}])
    return op.apply([[]], ATTRS, {"execute_query": True, "llm_client": client})


@pytest.mark.parametrize("version", [None, "1.0.0", "2.0.0", "3.0.0", "4.0.0"])
def test_real_configured_select(host: Host, version: str | None):
    assert execute(host[2], "SELECT id, value FROM records", version) == [
        [{"id": 1, "value": "synthetic"}]
    ]


@pytest.mark.parametrize(
    "properties",
    [
        {"execute_query": None},
        {"execute_query": 1},
        {"execute_query": "true"},
        {"validate_query_prefixes": None},
        {"validate_query_prefixes": "SELECT"},
        {"validate_query_prefixes": ("SELECT",)},
        {"validate_query_prefixes": []},
        {"validate_query_prefixes": [" SELECT"]},
        {"validate_query_prefixes": ["SELECT "]},
        {"validate_query_prefixes": ["ſelect"]},
        {"validate_query_prefixes": ["SELECT", "WITH"]},
        {"validate_query_prefixes": [1]},
        {"read_only_executor": None},
        *(
            {"execute_query": True, key: None}
            for key in ("data_registry", "platform.name", "data_registry.name")
        ),
        {"execute_query": True},
        {"input_template": None},
        {"openai.api_key": None},
    ],
)
def test_preflight_denies_before_registry_schema_client_cache(
    monkeypatch: pytest.MonkeyPatch, properties: Properties
):
    import blue_data_ops.operators.nl2sql_operator as module

    def forbidden(*a: object, **k: object) -> Never:
        raise AssertionError("effect before policy")

    cast(_Patch, monkeypatch).setattr(module, "resolve_registry", forbidden)
    cast(_Patch, monkeypatch).setattr(module, "resolve_llm_client", forbidden)
    for question in ("list rows", ""):
        with pytest.raises(LLMError) as raised:
            NL2SQLOperator().apply([[]], {**ATTRS, "question": question}, properties)
        assert raised.value.code in (
            "sql_policy_invalid",
            "sql_execution_unavailable",
            "reserved_field",
        )


@pytest.mark.parametrize("prefix", [["SELECT"], ["select"], ["SeLeCt"]])
def test_legacy_select_policy_is_narrow(host: Host, prefix: list[str]):
    assert (
        cast(Any, NL2SQLOperator(read_only_executor=host[2]))._preflight_execution(
            ATTRS, {"execute_query": True, "validate_query_prefixes": prefix}
        )
        is True
    )


@pytest.mark.parametrize(
    "target",
    [("elsewhere", "db", "public"), ("approved", "other", "public"), ("approved", "db", "other")],
)
def test_exact_target_denial_before_schema(
    host: Host, target: tuple[str, str, str], monkeypatch: pytest.MonkeyPatch
):
    def forbidden(*a: object, **k: object) -> Never:
        raise AssertionError("schema access")

    cast(_Patch, monkeypatch).setattr(host[0], "get_data_source_schema", forbidden)
    attrs = {**ATTRS, **dict(zip(("source", "database", "collection"), target))}
    with pytest.raises(LLMError) as raised:
        cast(Any, NL2SQLOperator(read_only_executor=host[2]))._preflight_execution(
            attrs, {"execute_query": True}
        )
    assert raised.value.code == "sql_target_denied"


@pytest.mark.parametrize("replacement", [None, "other"])
def test_registry_replacement_does_not_rebind(host: Host, replacement: str | None):
    cast(dict[str, SQLiteDBSource | None], host[0].sources)["approved"] = (
        None if replacement is None else SQLiteDBSource("approved")
    )
    with pytest.raises(LLMError) as raised:
        execute(host[2], "SELECT 1")
    assert raised.value.code == "sql_target_denied"


@pytest.mark.parametrize(
    "method",
    [
        "execute_query",
        "_set_read_only",
        "_db_connect",
        "_db_disconnect",
        "_is_multi_statement",
        "_is_read_only_error",
        "_read_only_authorizer",
    ],
)
def test_instance_guard_execution_and_connection_overrides_denied(host: Host, method: str):
    assert method in _GUARDED_METHODS
    cast(Callable[[object, str, Callable[..., None]], None], setattr)(
        host[1], method, lambda *a, **k: None
    )
    with pytest.raises(LLMError) as raised:
        execute(host[2], "SELECT 1")
    assert raised.value.code == "sql_execution_unavailable"


@pytest.mark.parametrize(
    "query",
    [
        None,
        {},
        {"op": "SQL.FETCH_ALL"},
        [],
        1,
        "",
        "  ",
        "SELECTED 1",
        "SELECTé 1",
        "ſELECT 1",
        "/*comment*/ SELECT 1",
        "WITH c AS (SELECT 1) SELECT * FROM c",
        "DELETE FROM records",
    ],
)
def test_invalid_generated_query_is_typed_and_never_executes(host: Host, query: Any):
    with pytest.raises(LLMError) as raised:
        execute(host[2], query)
    assert raised.value.code == "sql_query_rejected"


def snapshot(directory: Path) -> tuple[list[Any], list[Any], list[str]]:
    with sqlite3.connect(directory / "db.db") as conn:
        return (
            conn.execute("SELECT * FROM records").fetchall(),
            conn.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall(),
            sorted(p.name for p in directory.iterdir()),
        )


@pytest.mark.parametrize(
    "query",
    [
        "CREATE TABLE evil (id INTEGER)",
        "DROP TABLE records",
        'INSERT INTO records VALUES (2, "bad")',
        'UPDATE records SET value="bad"',
        "DELETE FROM records",
        'ATTACH DATABASE "escape.db" AS evil',
        "DETACH DATABASE main",
        'VACUUM INTO "escape.db"',
        "PRAGMA user_version=9",
        "SELECT 1; DELETE FROM records",
        "SELECT 1; /*hidden*/ DROP TABLE records",
        "SELECT * INTO evil FROM records",
        'SELECT load_extension("missing")',
    ],
)
def test_real_sqlite_adversarial_no_effects(host: Host, tmp_path: Path, query: str):
    before = snapshot(tmp_path)
    # Qualify path-bearing attacks to this synthetic scratch directory.
    query = query.replace('"escape.db"', "'" + str(tmp_path / "escape.db") + "'")
    with pytest.raises(LLMError) as raised:
        execute(host[2], query)
    assert raised.value.code in ("sql_query_rejected", "sql_execution_failed")
    assert "commit=True" not in str(raised.value)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize(
    "query",
    [
        "CREATE TABLE evil (id INTEGER)",
        'INSERT INTO records VALUES (2, "bad")',
        'ATTACH DATABASE "escape.db" AS evil',
        "DETACH DATABASE main",
        'VACUUM INTO "escape.db"',
        "SELECT 1; DELETE FROM records",
    ],
)
def test_real_sqlite_guard_itself_blocks_effects(host: Host, tmp_path: Path, query: str):
    before = snapshot(tmp_path)
    query = query.replace('"escape.db"', "'" + str(tmp_path / "escape.db") + "'")
    with pytest.raises(LLMError) as raised:
        host[2].execute(query, TARGET)
    assert raised.value.code == "sql_query_rejected"
    assert snapshot(tmp_path) == before


def test_guard_installation_failure_never_runs_query(host: Host, monkeypatch: pytest.MonkeyPatch):
    events: list[str] = []

    class Cursor:
        def execute(self, query: str) -> None:
            events.append("execute")

        def close(self):
            events.append("cursor-close")

    class Connection:
        def cursor(self):
            events.append("cursor")
            return Cursor()

        def execute(self, query: str) -> None:
            events.append("guard")
            raise RuntimeError("commit=True private")

        def close(self):
            events.append("close")

    cast(_Patch, monkeypatch).setattr(SQLiteDBSource, "_db_connect", lambda *a: Connection())
    with pytest.raises(LLMError) as raised:
        host[2].execute("SELECT 1", TARGET)
    assert str(raised.value) == "read-only SQL execution failed"
    assert events == ["cursor", "guard", "cursor-close", "close"]


def test_pipeline_uses_the_same_host_instance(host: Host):
    from blue_data_ops.plan import DataPipeline, PipelineExecutor

    registry = OperatorRegistry()
    op = NL2SQLOperator(read_only_executor=host[2])
    registry.register(op, version="3.0.0")
    pipeline = DataPipeline()
    source = pipeline.define_input()
    action = pipeline.define_operator("nl2sql@3.0.0", attributes=ATTRS)
    output = pipeline.define_output()
    pipeline.set_plan_input(source)
    pipeline.set_plan_output(output)
    pipeline.connect_nodes(source, action)
    pipeline.connect_nodes(action, output)
    props = {
        "execute_query": True,
        "llm_client": ScriptedClient([{"query": "SELECT id FROM records"}]),
    }
    result = PipelineExecutor(registry).execute(pipeline, [[]], props)
    assert result.succeeded and result.output_data == [[{"id": 1}]]
    assert registry.resolve("nl2sql@3.0.0") is op
    for version in ("1.0.0", "2.0.0", "3.0.0", "4.0.0"):
        alias = versioned_registry().resolve("nl2sql@" + version)
        with pytest.raises(LLMError) as raised:
            cast(Any, alias)._preflight_execution(ATTRS, {"execute_query": True})
        assert raised.value.code == "sql_execution_unavailable"


@pytest.mark.parametrize("backend", ["postgres", "mysql"])
@pytest.mark.parametrize("fail_guard", [False, True])
def test_remote_driver_order_double_only(
    monkeypatch: pytest.MonkeyPatch, backend: str, fail_guard: bool
):
    import importlib

    module = importlib.import_module(
        "blue_data.source.sql." + backend + "." + backend + "_sql_source"
    )
    cls = getattr(module, "PostgresDBSource" if backend == "postgres" else "MySQLDBSource")
    events: list[str] = []

    class Cursor:
        description = [("n",)]

        def execute(self, query: str) -> None:
            if query == "SET SESSION TRANSACTION READ ONLY":
                events.append("guard")
                if fail_guard:
                    raise RuntimeError("guard failed")
            else:
                events.append("query")

        def fetchall(self):
            return [(1,)]

        def close(self):
            events.append("cursor-close")

    class Connection:
        def cursor(self):
            events.append("cursor")
            return Cursor()

        def set_session(self, **kwargs: bool) -> None:
            assert kwargs == {"readonly": True}
            events.append("guard")
            if fail_guard:
                raise RuntimeError("guard failed")

        def close(self):
            events.append("close")

        def commit(self):
            raise AssertionError("commit forbidden")

    driver = module.psycopg2 if backend == "postgres" else module.cpy
    cast(_ConnectPatch, monkeypatch).setattr(driver, "connect", lambda **kwargs: Connection())
    source = cls("approved")
    registry = DataRegistry(store=MemoryJSONSource(), rebuild=False)
    registry.register_source(source)
    executor = ReadOnlySQLExecutor(registry, frozenset({TARGET}))
    if fail_guard:
        with pytest.raises(LLMError) as raised:
            executor.execute("SELECT 1", TARGET)
        assert raised.value.code == "sql_execution_failed"
        assert "query" not in events
    else:
        assert executor.execute("SELECT 1", TARGET) == [{"n": 1}]
        assert events.index("guard") < events.index("query")
    assert events[-1] == "close"


def test_custom_rule_planner_and_executor_share_the_host_instance(host: Host):
    from blue_data_ops.plan import (
        DataScope,
        DiscoveryQuery,
        PipelinePlanner,
        PlanDraft,
        PlanningRequest,
        PlanStep,
        RulePlanGenerator,
    )

    registry = OperatorRegistry()
    op = NL2SQLOperator(read_only_executor=host[2])
    registry.register(op, version="2.0.0")
    draft = PlanDraft((PlanStep("read", "nl2sql@2.0.0", ATTRS),))
    from blue_data_ops.data import RegistrySeam
    from blue_data_ops.plan import RegistryDataContextProvider

    host[0].sync_source("approved", recursive=True)
    planner = PipelinePlanner(
        registry,
        cast(
            Callable[[tuple[Callable[..., PlanDraft], ...]], RulePlanGenerator], RulePlanGenerator
        )((lambda *args: draft,)),
        data_context_provider=RegistryDataContextProvider(RegistrySeam(host[0])),
    )
    request = PlanningRequest(
        goal="Read records",
        data_scope=DataScope(*TARGET),
        discovery_queries=(DiscoveryQuery("nl2sql"),),
        allowed_operator_ids=("nl2sql@2.0.0",),
    )
    result = planner.run(
        request,
        [[]],
        {
            "execute_query": True,
            "llm_client": ScriptedClient([{"query": "SELECT id FROM records"}]),
        },
    )
    assert result.execution.succeeded
    assert result.execution.output_data == [[{"id": 1}]]
    assert registry.resolve("nl2sql@2.0.0") is op


@pytest.mark.parametrize(
    "targets",
    [
        cast(frozenset[tuple[str, str, str]], frozenset()),
        {TARGET},
        frozenset({("*", "db", "public")}),
        frozenset({("approved", "", "public")}),
        frozenset({("approved", "db")}),
    ],
)
def test_invalid_host_target_sets_are_refused(host: Host, targets: Any):
    with pytest.raises(LLMError) as raised:
        ReadOnlySQLExecutor(host[0], targets)
    assert raised.value.code == "sql_policy_invalid"


def test_missing_source_and_unknown_subclass_are_refused(host: Host):
    with pytest.raises(LLMError) as raised:
        ReadOnlySQLExecutor(host[0], frozenset({("missing", "db", "public")}))
    assert raised.value.code == "sql_target_denied"

    class CustomSQLite(SQLiteDBSource):
        pass

    host[0].sources["approved"] = CustomSQLite("approved")
    with pytest.raises(LLMError) as raised:
        ReadOnlySQLExecutor(host[0], frozenset({TARGET}))
    assert raised.value.code == "sql_execution_unavailable"


def test_noop_guard_and_replaced_execution_are_refused(host: Host, monkeypatch: pytest.MonkeyPatch):
    from blue_data.source.sql.sql_source import SQLSource  # pyright: ignore[reportMissingTypeStubs]

    with monkeypatch.context() as patch:
        cast(_Patch, patch).setattr(
            SQLiteDBSource, "_set_read_only", cast(Any, SQLSource)._set_read_only
        )
        with pytest.raises(LLMError) as raised:
            execute(host[2], "SELECT 1")
        assert raised.value.code == "sql_execution_unavailable"
    with monkeypatch.context() as patch:
        cast(_Patch, patch).setattr(SQLiteDBSource, "execute_query", lambda *a, **k: [])
        with pytest.raises(LLMError) as raised:
            execute(host[2], "SELECT 1")
        assert raised.value.code == "sql_execution_unavailable"


def test_bound_capability_preflight_and_execution_survive_version_alias(host: Host):
    registry = OperatorRegistry()
    operator = NL2SQLOperator(read_only_executor=host[2])
    registry.register(operator, version="2.0.0")
    registry.register(operator, version="3.0.0")
    alias = registry.resolve("nl2sql@3.0.0")
    assert alias is not operator
    assert cast(Any, alias)._preflight_execution(ATTRS, {"execute_query": True}) is True
    output, _, meta = alias.run(
        [[]],
        ATTRS,
        {
            "execute_query": True,
            "llm_client": ScriptedClient([{"query": "SELECT id FROM records"}]),
        },
    )
    assert output == [[{"id": 1}]]
    assert meta.errors == []

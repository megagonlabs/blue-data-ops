from __future__ import annotations

import sqlite3
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal, NoReturn, Protocol, TypeAlias, cast

import pytest
from blue_data.registry.data_registry import DataRegistry
from blue_data.source.json.memory_json_source import MemoryJSONSource
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource
from blue_data_ops.data import RegistrySeam
from blue_data_ops.llm import LLMClient
from blue_data_ops.llm.sql_execution import ReadOnlySQLExecutor
from blue_data_ops.operators import (
    FunctionResult,
    NL2SQLOperator,
    OperatorRegistry,
    versioned_registry,
)
from blue_data_ops.operators._nl2sql_outcome import NL2SQLOutcomeOperator
from blue_data_ops.operators.types import Attributes, DataBundle, Properties
from mcp.shared.memory import create_connected_server_and_client_session

from blue_data_ops_mcp.data_registry import DeploymentRegistry
from blue_data_ops_mcp.registration import freeze_deployment, make_run_handler
from blue_data_ops_mcp.server import create_server

ATTRS = {
    "source": "approved",
    "database": "db",
    "collection": "public",
    "protocol": "sqlite",
    "question": "list rows",
}
DIAGNOSTICS = {
    "reserved_field": (
        "operator template and transport controls are reserved",
        "Remove caller template, extraction and transport controls; "
        "use a host-configured operator.",
    ),
    "sql_policy_invalid": (
        "invalid SQL execution policy",
        "Use a boolean execute_query and omit validate_query_prefixes "
        "or use a one-item SELECT list; "
        "remove caller execution capabilities and registry selectors when requesting execution.",
    ),
    "sql_execution_unavailable": (
        "read-only SQL execution is not configured",
        "Request generation only, or ask the deployment owner to configure a supported "
        "read-only SQL executor.",
    ),
    "sql_target_denied": (
        "SQL target is outside the configured execution scope",
        "Use a target approved by the deployment owner, or request generation only.",
    ),
    "sql_query_rejected": (
        "generated SQL does not satisfy the read-only query contract",
        "Request one SELECT statement as a nonempty string; execution also requires "
        "the database read-only guard.",
    ),
    "sql_execution_failed": (
        "generated SQL failed against the approved schema",
        "Rephrase the question or check the declared target and schema.",
    ),
}


class Client(LLMClient):
    def __init__(self) -> None:
        self.response: dict[str, Any] = {"query": "SELECT id, value FROM records"}
        self.calls: list[tuple[dict[str, Any] | None, dict[str, Any] | None]] = []

    def execute_api_call(
        self,
        input: Any,
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append((properties, additional_data))
        return deepcopy(self.response)


Host: TypeAlias = tuple[ReadOnlySQLExecutor, Client, list[str]]
SQLImplementation: TypeAlias = NL2SQLOperator | NL2SQLOutcomeOperator


class EnvironmentBuilder(Protocol):
    def __call__(self, **kwargs: object) -> RegistrySeam: ...


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Host:
    import blue_data_ops.operators.nl2sql_operator as module

    import blue_data_ops_mcp.data_registry as deployment_module

    with sqlite3.connect(tmp_path / "db.db") as connection:
        connection.execute("CREATE TABLE records (id INTEGER, value TEXT)")
        connection.execute("INSERT INTO records VALUES (1, 'synthetic')")
    registry = DataRegistry(store=MemoryJSONSource(), rebuild=False)
    source = SQLiteDBSource(
        "approved", properties={"connection": {"database_directory": str(tmp_path)}}
    )
    registry.register_source(source)
    capability = ReadOnlySQLExecutor(registry, frozenset({("approved", "db", "public")}))
    client = Client()
    cast(
        Callable[
            [object, str, Callable[[dict[str, Any] | None], Client]],
            None,
        ],
        monkeypatch.setattr,
    )(module, "resolve_llm_client", lambda properties: client)
    effects: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        effects.append("ordinary registry")
        raise AssertionError("ordinary registry must not be requested")

    monkeypatch.setattr(deployment_module, "build_environment_registry", forbidden)
    monkeypatch.setattr(module, "resolve_registry", forbidden)
    return capability, client, effects


def configured(host: Host, selection: str) -> tuple[OperatorRegistry, SQLImplementation, str]:
    registry = OperatorRegistry()
    operator = (
        NL2SQLOutcomeOperator(read_only_executor=host[0])
        if selection == "outcome"
        else NL2SQLOperator(read_only_executor=host[0])
    )
    if selection == "alias":
        cast(Any, registry)._register_builtin(operator, "1.0.0")
    if selection == "custom":
        cast(Any, operator).name = "host_sql"
        registry.register(operator, "2.0.0", tags=("requires-data-registry",))
    else:
        cast(Any, registry)._register_builtin(
            operator,
            "3.0.0" if selection == "outcome" else "2.0.0",
            tags=("requires-data-registry",),
        )
    operator_id = operator.name + ("@3.0.0" if selection == "outcome" else "@2.0.0")
    return registry, operator, operator_id


@pytest.mark.parametrize("selection", ["direct", "alias", "outcome", "custom"])
async def test_freeze_and_real_bound_select_without_ordinary_registry(
    host: Host,
    selection: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, implementation, operator_id = configured(host, selection)
    snapshot = freeze_deployment(registry, (operator_id,))
    assert snapshot[0].operator is registry.resolve(operator_id)
    seen: list[Properties] = []
    original = cast(Any, implementation)._execute

    def recording(
        data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        seen.append(dict(properties or {}))
        return original(data, attributes, properties)

    monkeypatch.setattr(implementation, "_execute", recording)
    server = create_server(registry=registry, operator_ids=(operator_id,))
    async with create_connected_server_and_client_session(cast(Any, server)._mcp_server) as client:
        result = await client.call_tool(
            "ops_" + implementation.name,
            {
                "input_data": [[]],
                "attributes": ATTRS,
                "properties": {"execute_query": True, "validate_query_prefixes": ["select"]},
            },
        )
    assert not result.isError
    payload = cast(dict[str, Any], result.structuredContent)
    assert payload["output_data"] == [[{"id": 1, "value": "synthetic"}]]
    assert payload["exec_meta"]["errors"] == []
    assert len(host[1].calls) == 1
    assert host[2] == []
    assert len(seen) == 1
    assert not {"data_registry", "platform.name", "data_registry.name"}.intersection(seen[0])


@pytest.mark.parametrize("version", ["2.0.0", "3.0.0"])
@pytest.mark.parametrize(
    "properties,expected",
    [
        ({"execute_query": True}, "sql_execution_unavailable"),
        ({"execute_query": "true"}, "sql_policy_invalid"),
        ({"input_template": "synthetic caller detail"}, "reserved_field"),
        *[
            ({"execute_query": True, key: None}, "sql_policy_invalid")
            for key in ("data_registry", "platform.name", "data_registry.name")
        ],
    ],
)
async def test_original_stock_policy_precedes_lazy_build(
    host: Host,
    version: str,
    properties: Properties,
    expected: str,
) -> None:
    selected = versioned_registry().resolve("nl2sql@" + version)
    deployment = DeploymentRegistry()
    before = deepcopy(properties)
    result = await make_run_handler(selected, deployment=deployment, requires_registry=True)(
        [[]], ATTRS, properties
    )
    error = result.exec_meta.errors[0]
    assert (error.message, error.suggestion) == DIAGNOSTICS[expected]
    assert properties == before
    assert deployment.state == "UNINITIALIZED"
    assert host[1].calls == []
    assert host[2] == []


@pytest.mark.parametrize("state", ["UNINITIALIZED", "MISSING", "FAILED"])
async def test_bound_execution_ignores_ordinary_builder_state(
    host: Host,
    state: Literal["UNINITIALIZED", "MISSING", "FAILED"],
) -> None:
    registry, _, operator_id = configured(host, "alias")
    deployment = DeploymentRegistry()
    deployment.state = state
    result = await make_run_handler(
        registry.resolve(operator_id), deployment=deployment, requires_registry=True
    )([[]], ATTRS, {"execute_query": True})
    assert result.output_data == [[{"id": 1, "value": "synthetic"}]]
    assert result.exec_meta.errors == []
    assert deployment.state == state
    assert host[2] == []


@pytest.mark.parametrize("preflight_case", [None, "raises", "nonboolean"])
async def test_missing_raising_nonboolean_preflight_on_real_alias(
    host: Host,
    monkeypatch: pytest.MonkeyPatch,
    preflight_case: str | None,
) -> None:
    registry, operator, operator_id = configured(host, "alias")
    preflight: Callable[..., object] | None = None
    if preflight_case == "raises":

        def raising_preflight(*args: object) -> NoReturn:
            raise RuntimeError("synthetic backend detail")

        preflight = raising_preflight
    elif preflight_case == "nonboolean":

        def nonboolean_preflight(*args: object) -> int:
            return 1

        preflight = nonboolean_preflight

    monkeypatch.setattr(operator, "_preflight_execution", preflight)
    deployment = DeploymentRegistry()
    result = await make_run_handler(
        freeze_deployment(registry, (operator_id,))[0].operator,
        deployment=deployment,
        requires_registry=True,
    )([[]], ATTRS, {"execute_query": True})
    error = result.exec_meta.errors[0]
    assert (error.message, error.suggestion) == DIAGNOSTICS["sql_execution_unavailable"]
    assert "synthetic backend detail" not in str(result)
    assert deployment.state == "UNINITIALIZED"
    assert host[1].calls == [] and host[2] == []


@pytest.mark.parametrize("code", list(DIAGNOSTICS))
async def test_actual_sql_denial_has_exact_wire_diagnostic(host: Host, code: str) -> None:
    registry, _, operator_id = configured(host, "alias")
    properties: Properties = {"execute_query": True}
    attributes: Attributes = dict(ATTRS)
    if code == "reserved_field":
        properties["input_template"] = "synthetic caller detail"
    elif code == "sql_policy_invalid":
        properties["platform.name"] = "synthetic caller detail"
    elif code == "sql_execution_unavailable":
        registry = versioned_registry()
    elif code == "sql_target_denied":
        attributes["source"] = "outside"
    elif code == "sql_query_rejected":
        host[1].response = {"query": "DELETE FROM records"}
    elif code == "sql_execution_failed":
        host[1].response = {"query": "SELECT * FROM synthetic_missing_table"}
    server = create_server(registry=registry, operator_ids=(operator_id,))
    async with create_connected_server_and_client_session(cast(Any, server)._mcp_server) as client:
        result = await client.call_tool(
            "ops_nl2sql",
            {
                "input_data": [[]],
                "attributes": attributes,
                "properties": properties,
            },
        )
    assert not result.isError
    payload = cast(dict[str, Any], result.structuredContent)
    assert payload["output_data"] == [[]]
    error = payload["exec_meta"]["errors"][0]
    assert (error["message"], error["suggestion"]) == DIAGNOSTICS[code]
    assert error["retryable"] is False
    assert "synthetic caller detail" not in str(result)
    assert "synthetic_missing_table" not in str(result)
    assert host[2] == []


@pytest.mark.parametrize("version", ["2.0.0", "3.0.0"])
@pytest.mark.parametrize("prefix", ["openai", "host_service"])
async def test_bn_original_transport_controls_precede_lazy_build(
    monkeypatch: pytest.MonkeyPatch,
    version: str,
    prefix: str,
) -> None:
    import blue_data_ops_mcp.data_registry as module

    selected = versioned_registry().resolve("nl2bn@" + version)
    implementation = getattr(selected, "_target", selected)
    monkeypatch.setattr(
        implementation,
        "DEFAULT_PROPERTIES",
        {
            **cast(Any, implementation).DEFAULT_PROPERTIES,
            "service_prefix": prefix,
        },
    )
    effects: list[str] = []

    def build(**kwargs: Any) -> NoReturn:
        effects.append("build")
        raise AssertionError("caller controls must precede lazy build")

    monkeypatch.setattr(module, "build_environment_registry", build)
    deployment = DeploymentRegistry()
    properties: Properties = {prefix + ".service_url": "synthetic caller detail"}
    result = await make_run_handler(selected, deployment=deployment, requires_registry=True)(
        [[]], {}, properties
    )
    error = result.exec_meta.errors[0]
    assert (error.message, error.suggestion) == DIAGNOSTICS["reserved_field"]
    assert properties == {prefix + ".service_url": "synthetic caller detail"}
    assert deployment.state == "UNINITIALIZED" and effects == []


async def test_bn_admission_does_not_apply_sql_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import blue_data_ops.operators._nl2bn_outcome as module

    import blue_data_ops_mcp.data_registry as deployment_module

    class Seam(RegistrySeam):
        def __init__(self) -> None:
            pass

        def get_data_source_schema(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {
                "graph_structure": {
                    "nodes": {"rain": {"states": ["yes", "no"]}},
                    "edges": {},
                }
            }

        def execute_query(self, *args: Any, **kwargs: Any) -> list[dict[str, float]]:
            return [{"probability": 0.75}]

    client = Client()
    client.response = {"target_node": "rain", "target_state": "yes", "context": {}}
    cast(
        Callable[
            [object, str, Callable[[dict[str, Any] | None], Client]],
            None,
        ],
        monkeypatch.setattr,
    )(module, "resolve_llm_client", lambda properties: client)
    seam = Seam()
    builds: list[int] = []

    cast(Callable[[object, str, EnvironmentBuilder], None], monkeypatch.setattr)(
        deployment_module,
        "build_environment_registry",
        lambda **kwargs: builds.append(1) or seam,
    )
    selected = versioned_registry().resolve("nl2bn@3.0.0")
    deployment = DeploymentRegistry()
    result = await make_run_handler(selected, deployment=deployment, requires_registry=True)(
        [[]],
        {
            "question": "chance of rain?",
            "source": "bn",
            "database": "default",
            "collection": "weather",
            "protocol_variant": "pgmpy",
        },
        {"execute_query": "yes", "validate_query_prefixes": ["WITH"], "explanation": False},
    )
    assert result.exec_meta.errors == []
    assert len(client.calls) == 1 and builds == [1]


@pytest.mark.parametrize("key", ["data_registry", "platform.name", "data_registry.name"])
async def test_bound_original_selectors_are_rejected_without_overwrite(
    host: Host,
    key: str,
) -> None:
    registry, _, operator_id = configured(host, "alias")
    deployment = DeploymentRegistry()
    properties: Properties = {"execute_query": True, key: None}
    result = await make_run_handler(
        registry.resolve(operator_id), deployment=deployment, requires_registry=True
    )([[]], ATTRS, properties)
    error = result.exec_meta.errors[0]
    assert (error.message, error.suggestion) == DIAGNOSTICS["sql_policy_invalid"]
    assert properties == {"execute_query": True, key: None}
    assert deployment.state == "UNINITIALIZED"
    assert host[1].calls == [] and host[2] == []


async def test_sql_generation_uses_deployment_registry_after_original_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import blue_data_ops.operators.nl2sql_operator as module

    import blue_data_ops_mcp.data_registry as deployment_module

    class Seam(RegistrySeam):
        def __init__(self) -> None:
            pass

        def get_data_source_schema(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"tables": {"records": {"id": "INTEGER"}}}

        def execute_query(self, *args: Any, **kwargs: Any) -> NoReturn:
            raise AssertionError("generation must not execute")

    seam = Seam()
    builds: list[int] = []

    cast(Callable[[object, str, EnvironmentBuilder], None], monkeypatch.setattr)(
        deployment_module,
        "build_environment_registry",
        lambda **kwargs: builds.append(1) or seam,
    )
    client = Client()
    cast(
        Callable[
            [object, str, Callable[[dict[str, Any] | None], Client]],
            None,
        ],
        monkeypatch.setattr,
    )(module, "resolve_llm_client", lambda properties: client)
    selected = versioned_registry().resolve("nl2sql@3.0.0")
    deployment = DeploymentRegistry()
    properties: Properties = {"data_registry.name": "ignored-for-generation"}
    result = await make_run_handler(selected, deployment=deployment, requires_registry=True)(
        [[]], ATTRS, properties
    )
    assert result.exec_meta.errors == []
    assert result.output_data == [[{"sql": "SELECT id, value FROM records"}]]
    assert builds == [1] and len(client.calls) == 1
    assert properties == {"data_registry.name": "ignored-for-generation"}

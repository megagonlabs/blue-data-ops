from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any, NoReturn, Protocol, cast

import pytest
from blue_data.registry.data_registry import DataRegistry
from blue_data_ops.data import RegistrySeam
from blue_data_ops.operators import FunctionResult, Operator, versioned_registry
from blue_data_ops.operators.types import Attributes, DataBundle, Properties
from mcp.shared.memory import create_connected_server_and_client_session

from blue_data_ops_mcp.data_registry import DeploymentRegistry
from blue_data_ops_mcp.registration import make_run_handler
from blue_data_ops_mcp.server import create_server


class VariadicFailure(Protocol):
    def __call__(self, *args: object) -> NoReturn: ...


async def until(predicate: Callable[[], bool]) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(poll(), 3)


class Blocking(Operator):
    name = "blocking"

    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self.finish = Event()
        self.calls = 0
        self.properties_seen: list[Properties | None] = []

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        return input_data

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        self.calls += 1
        self.properties_seen.append(properties)
        self.started.set()
        assert self.finish.wait(5)
        return FunctionResult(input_data, {})


class Immediate(Operator):
    name = "immediate"

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        return input_data

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        return FunctionResult(input_data, {})


async def test_queued_cancellation_never_executes_and_untagged_progress():
    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=2))
    op = Blocking()
    deployment = DeploymentRegistry(DataRegistry())
    handler = make_run_handler(op, deployment=deployment, requires_registry=True)
    first = asyncio.create_task(handler([[{}]]))
    await until(op.started.is_set)
    queued = [asyncio.create_task(handler([[{}]])) for _ in range(12)]
    try:
        await asyncio.sleep(0.02)
        queued[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued[0]
        result = await asyncio.wait_for(make_run_handler(Immediate())([[{"progress": True}]]), 0.5)
        assert result.output_data == [[{"progress": True}]]
        assert op.calls == 1
    finally:
        op.finish.set()
        await first
        await asyncio.gather(*queued[1:])
    assert op.calls == 12


async def test_running_cancellation_keeps_admission_until_completion():
    op = Blocking()
    deployment = DeploymentRegistry(DataRegistry())
    handler = make_run_handler(op, deployment=deployment, requires_registry=True)
    running = asyncio.create_task(handler([[{}]]))
    await until(op.started.is_set)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    queued = asyncio.create_task(handler([[{}]]))
    try:
        await asyncio.sleep(0.03)
        assert op.calls == 1
        assert not queued.done()
    finally:
        op.finish.set()
    await queued
    assert op.calls == 2


async def test_terminal_build_state_is_rechecked_after_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import blue_data_ops_mcp.data_registry as module

    started, finish = Event(), Event()
    calls: list[int] = []

    def fail(**kwargs: Any) -> None:
        calls.append(1)
        started.set()
        assert finish.wait(5)
        raise RuntimeError("synthetic backend detail")

    monkeypatch.setattr(module, "build_environment_registry", fail)
    op = Immediate()
    deployment = DeploymentRegistry()
    handler = make_run_handler(op, deployment=deployment, requires_registry=True)
    first = asyncio.create_task(handler([[{}]]))
    await until(started.is_set)
    queued = [asyncio.create_task(handler([[{}]])) for _ in range(6)]
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    finish.set()
    results = await asyncio.gather(*queued)
    assert len(calls) == 1
    assert deployment.state == "FAILED"
    assert all(
        result.exec_meta.errors[0].message == "data registry configuration failed"
        for result in results
    )
    assert "synthetic backend detail" not in str(results)


async def test_owned_injection_ignores_names_without_mutating_caller():
    op = Blocking()
    op.finish.set()
    seam = RegistrySeam(DataRegistry())
    properties = {
        "platform.name": "caller",
        "data_registry.name": "caller",
        "data_registry": {"fake": True},
    }
    original = dict(properties)
    handler = make_run_handler(op, deployment=DeploymentRegistry(seam), requires_registry=True)
    assert not (await handler([[{}]], properties=properties)).exec_meta.errors
    assert properties == original
    assert op.properties_seen[0] == {"data_registry": seam}


async def test_real_protocol_missing_registry_is_owned_failure_no_provider_cache_growth():
    import blue_data_ops.data.provider as provider_module

    _default_provider = cast(Any, provider_module)._default_provider
    before = len(_default_provider._cache)
    server = create_server(operator_ids=("data_discover@2.0.0",))
    async with create_connected_server_and_client_session(cast(Any, server)._mcp_server) as client:
        for index in range(3):
            result = await client.call_tool(
                "ops_data_discover",
                {
                    "input_data": [[]],
                    "attributes": {"search_query": "none", "approximate": False},
                    "properties": {"platform.name": "caller", "data_registry.name": str(index)},
                },
            )
            assert result.isError is False
            payload = cast(dict[str, Any], result.structuredContent)
            assert payload["output_data"] == [[]]
            assert payload["output_attributes"] == {}
            assert payload["exec_meta"]["is_empty"] is False
            assert payload["exec_meta"]["errors"][0]["message"] == "data registry is not configured"
    assert len(_default_provider._cache) == before


async def test_missing_preflight_denies_by_implementation_even_without_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from blue_data_ops.operators.nl2sql_operator import NL2SQLOperator

    op = NL2SQLOperator()
    monkeypatch.setattr(op, "_preflight_execution", None, raising=False)
    result = await make_run_handler(op)([[]], {}, {"execute_query": True})
    assert result.exec_meta.errors[0].message == "read-only SQL execution is not configured"

    cast(Callable[[object, str, VariadicFailure], None], monkeypatch.setattr)(
        op,
        "_preflight_execution",
        lambda *args: (_ for _ in ()).throw(RuntimeError("synthetic backend detail")),
    )
    result = await make_run_handler(op)([[]], {}, {"execute_query": True})
    assert result.exec_meta.errors[0].message == "read-only SQL execution is not configured"
    assert "synthetic backend detail" not in str(result)


async def test_shared_vector_instance_mcp_without_registry_serialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = versioned_registry()
    op = registry.resolve("vector_search@3.0.0")
    data = [[{"embedding": [1.0, 0.0], "embed.model": "all-MiniLM-L6-v2"}]]
    attrs = {"query": {"embedding": [1.0, 0.0]}}
    expected = op.run(data, attrs)
    monkeypatch.setattr(
        op,
        "_refresh_attribute_projection",
        cast(Callable[[], None], lambda: pytest.fail("shared refresh")),
    )
    server = create_server(registry=registry, operator_ids=("vector_search@3.0.0",))
    async with create_connected_server_and_client_session(cast(Any, server)._mcp_server) as client:
        results = await asyncio.gather(
            *(
                client.call_tool("ops_vector_search", {"input_data": data, "attributes": attrs})
                for _ in range(16)
            )
        )
    assert all(
        cast(dict[str, Any], result.structuredContent)["output_data"] == expected[0]
        for result in results
    )
    assert all(
        cast(dict[str, Any], result.structuredContent)["exec_meta"]["errors"] == []
        for result in results
    )


async def test_operator_deadline_does_not_bound_initial_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import blue_data_ops_mcp.data_registry as module

    started, finish = Event(), Event()
    seam = RegistrySeam(DataRegistry())

    def build(**kwargs: Any) -> RegistrySeam:
        started.set()
        assert finish.wait(5)
        return seam

    monkeypatch.setattr(module, "build_environment_registry", build)
    task = asyncio.create_task(
        make_run_handler(Immediate(), deployment=DeploymentRegistry(), requires_registry=True)(
            [[{}]], properties={"execution.timeout_seconds": 0.02}
        )
    )
    await until(started.is_set)
    try:
        await asyncio.sleep(0.05)
        assert not task.done()
    finally:
        finish.set()
    assert (await task).exec_meta.errors == []


async def test_real_write_tools_persist_and_partial_failure_is_visible(tmp_path: Path) -> None:
    from blue_data.source.json.file_json_source import FileJSONSource
    from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource

    registry = DataRegistry(
        store=FileJSONSource(properties={"connection": {"path": str(tmp_path / "registry.json")}})
    )
    registry.register_source(
        SQLiteDBSource("sqlite", properties={"connection": {"database_directory": str(tmp_path)}})
    )
    server = create_server(
        data_registry=registry,
        operator_ids=("create_database@2.0.0", "create_table@2.0.0", "insert_table@3.0.0"),
    )
    async with create_connected_server_and_client_session(cast(Any, server)._mcp_server) as client:
        for tool, attrs in (
            ("ops_create_database", {"source": "sqlite", "database": "db"}),
            (
                "ops_create_table",
                {
                    "source": "sqlite",
                    "database": "db",
                    "collection": "public",
                    "table": "items",
                    "columns": [{"name": "id", "type": "INTEGER", "misc": "PRIMARY KEY"}],
                },
            ),
        ):
            result = await client.call_tool(tool, {"input_data": [[]], "attributes": attrs})
            assert result.isError is False
            assert cast(dict[str, Any], result.structuredContent)["exec_meta"]["errors"] == []
        result = await client.call_tool(
            "ops_insert_table",
            {
                "input_data": [[{"id": 1}, {"id": 1}]],
                "attributes": {
                    "source": "sqlite",
                    "database": "db",
                    "collection": "public",
                    "table": "items",
                    "batch_size": 1,
                },
            },
        )
        assert result.isError is False
        assert (
            cast(dict[str, Any], result.structuredContent)["exec_meta"]["errors"][0]["message"]
            == "database constraint rejected the operation"
        )
    rows = RegistrySeam(registry).execute_query("SELECT id FROM items", "sqlite", "db", "public")
    assert rows == [{"id": 1}]
    reopened = DataRegistry(
        store=FileJSONSource(properties={"connection": {"path": str(tmp_path / "registry.json")}})
    )
    assert reopened.get_source_record("sqlite") is not None


@pytest.mark.parametrize(
    "code",
    [
        "reserved_field",
        "sql_policy_invalid",
        "sql_execution_unavailable",
        "sql_target_denied",
        "sql_query_rejected",
        "sql_execution_failed",
    ],
)
async def test_owned_llm_failure_through_mcp_contains_no_backend_text(code: str) -> None:
    from blue_data_ops.llm.errors import LLMError
    from blue_data_ops.operators import OperatorRegistry
    from blue_data_ops.operators import operator as operator_module

    _execution_error = cast(Any, operator_module)._execution_error

    class Failure(Operator):
        name = "failure"

        def apply(
            self,
            input_data: DataBundle,
            attributes: Attributes,
            properties: Properties | None = None,
        ) -> DataBundle:
            raise LLMError("synthetic backend detail", code=code)

    registry = OperatorRegistry()
    registry.register(Failure(), "2.0.0")
    server = create_server(registry=registry, operator_ids=("failure@2.0.0",))
    async with create_connected_server_and_client_session(cast(Any, server)._mcp_server) as client:
        result = await client.call_tool("ops_failure", {"input_data": [[]]})
    assert result.isError is False
    error = cast(dict[str, Any], result.structuredContent)["exec_meta"]["errors"][0]
    expected = _execution_error("failure@2.0.0", LLMError("untrusted", code=code))
    assert error["message"] == expected.message
    assert error["suggestion"] == expected.suggestion
    assert "synthetic backend detail" not in str(result)


def test_closed_builtin_implementation_accepts_only_real_version_aliases() -> None:
    from blue_data_ops.operators import OperatorRegistry
    from blue_data_ops.operators.nl2sql_operator import NL2SQLOperator

    from blue_data_ops_mcp.registration import freeze_deployment

    registry = OperatorRegistry()
    operator = NL2SQLOperator()
    cast(Any, registry)._register_builtin(operator, "1.0.0")
    cast(Any, registry)._register_builtin(operator, "2.0.0", tags=("requires-data-registry",))
    snapshot = freeze_deployment(registry, ("nl2sql@2.0.0",))
    assert snapshot[0].operator.operator_id == "nl2sql@2.0.0"
    assert cast(Any, snapshot[0].operator)._target is operator


async def test_lazy_success_is_initialized_once_for_queued_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import blue_data_ops_mcp.data_registry as module

    started, finish = Event(), Event()
    calls: list[int] = []
    seam = RegistrySeam(DataRegistry())

    def build(**kwargs: Any) -> RegistrySeam:
        calls.append(1)
        started.set()
        assert finish.wait(5)
        return seam

    monkeypatch.setattr(module, "build_environment_registry", build)
    deployment = DeploymentRegistry()
    handler = make_run_handler(Immediate(), deployment=deployment, requires_registry=True)
    first = asyncio.create_task(handler([[{}]]))
    await until(started.is_set)
    queued = [asyncio.create_task(handler([[{}]])) for _ in range(4)]
    finish.set()
    results = await asyncio.gather(first, *queued)
    assert all(result.exec_meta.errors == [] for result in results)
    assert calls == [1]
    assert deployment.state == "READY"
    assert deployment.seam is seam


async def test_explicit_empty_environment_registry_is_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BLUE_DATA_REGISTRY_STORE", "memory")
    server = create_server(operator_ids=("data_discover@2.0.0",))
    async with create_connected_server_and_client_session(cast(Any, server)._mcp_server) as client:
        result = await client.call_tool(
            "ops_data_discover",
            {"input_data": [[]], "attributes": {"search_query": "none", "approximate": False}},
        )
    assert result.isError is False
    assert cast(dict[str, Any], result.structuredContent)["output_data"] == [[]]
    assert cast(dict[str, Any], result.structuredContent)["exec_meta"]["errors"] == []
    assert cast(dict[str, Any], result.structuredContent)["exec_meta"]["is_empty"] is True


@pytest.mark.parametrize("value", [{}, "registry", 1])
def test_host_registry_input_is_validated(value: object) -> None:
    with pytest.raises(TypeError, match="data_registry must be"):
        create_server(data_registry=cast(Any, value), operator_ids=())

from __future__ import annotations

import asyncio
import importlib
import json
from typing import Any

import pytest
from blue_data.registry.data_registry import DataRegistry  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.json.memory_json_source import MemoryJSONSource  # pyright: ignore[reportMissingTypeStubs]
from blue_data_ops.operators import Operator, OperatorRegistry
from blue_data_ops.operators.types import Attributes, DataBundle, Properties
from blue_data_ops.plan import DataPipeline, PipelineExecutor
from mcp.shared.memory import create_connected_server_and_client_session

from blue_data_ops_mcp.data_registry import DeploymentRegistry
from blue_data_ops_mcp.registration import make_run_handler
from blue_data_ops_mcp.server import create_server

MARKER = "SYNTHETIC_PRIVATE_ESCAPED_EXCEPTION"


class BadRun(Operator):
    name = "escaped_diagnostic"
    description = "Local escaped run fixture."
    attributes = {}

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def apply(
        self, input_data: DataBundle, attributes: Attributes, properties: Properties | None = None
    ) -> DataBundle:
        return input_data

    def run(
        self, input_data: DataBundle, attributes: Attributes, properties: Properties | None = None
    ) -> Any:
        raise self.error


def pipeline(operator_id: str) -> DataPipeline:
    value = DataPipeline(id="escaped")
    entry = value.define_input("input")
    step = value.define_operator(operator_id, label="step", attributes={})
    out = value.define_output("output")
    value.set_plan_input(entry)
    value.set_plan_output(out)
    value.connect_nodes(entry, step)
    value.connect_nodes(step, out)
    return value


def exception(kind: str) -> Exception:
    if kind == "typed":
        module = importlib.import_module("blue_data_ops.operators.types")
        cls = vars(module).get("OperatorExecutionError")
        assert isinstance(cls, type), "new custom diagnostic export is absent"
        return cls("fixed author text", suggestion="fixed author action", retryable=True)
    return TimeoutError(MARKER) if kind == "timeout" else RuntimeError(MARKER)


@pytest.mark.parametrize("admitted", [False, True])
@pytest.mark.parametrize("kind", ["ordinary", "timeout", "typed"])
async def test_body_exception_matches_pipeline_generic(admitted: bool, kind: str) -> None:
    op = BadRun(exception(kind))
    registry = OperatorRegistry()
    registry.register(op, "2.0.0")
    expected = (
        PipelineExecutor(registry).execute(pipeline(op.operator_id), [[]]).node_runs[0].exec_meta
    )
    deployment = DeploymentRegistry(DataRegistry(store=MemoryJSONSource(), rebuild=False))
    handler = make_run_handler(op, deployment=deployment, requires_registry=admitted)
    result = await handler([[]])
    meta = result.exec_meta.model_dump(mode="json")
    assert meta == {
        "is_empty": False,
        "errors": [dict(expected.errors[0]._asdict())],
        "logs": [],
        "traces": {},
    }
    assert meta["errors"][0]["suggestion"] is None
    assert MARKER not in json.dumps(meta)
    assert result.output_data == [[]] and result.output_attributes == {}
    again = await handler([[]])
    assert again.exec_meta == result.exec_meta


@pytest.mark.parametrize("kind", ["ordinary", "timeout", "typed"])
async def test_escaped_error_safe_on_json_rpc(kind: str) -> None:
    op = BadRun(exception(kind))
    registry = OperatorRegistry()
    registry.register(op, "2.0.0")
    async with create_connected_server_and_client_session(
        create_server(registry=registry, operator_ids=(op.operator_id,))
    ) as client:
        result = await client.call_tool("ops_escaped_diagnostic", {"input_data": [[]]})
    assert result.isError is False
    assert MARKER not in result.model_dump_json()
    assert result.structuredContent is not None
    error = result.structuredContent["exec_meta"]["errors"][0]
    assert error["message"] == "operator execution failed"
    assert error["suggestion"] is None and error["retryable"] is False


async def test_cancellation_base_is_not_contained() -> None:
    class CancelRun(BadRun):
        def run(
            self,
            input_data: DataBundle,
            attributes: Attributes,
            properties: Properties | None = None,
        ) -> Any:
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await make_run_handler(CancelRun(RuntimeError()), requires_registry=False)([[]])

from __future__ import annotations

from typing import Any, ClassVar

from blue_data_ops.operators import AttributeSpec, ExecMeta, Operator, OperatorRegistry
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

import blue_data_ops_mcp.schema as schema_module
from blue_data_ops_mcp.registration import ACTIVE_OPERATOR_IDS, freeze_deployment
from blue_data_ops_mcp.schema import RunResult
from blue_data_ops_mcp.server import create_server

LIFECYCLE_META_KEYS = {"operator_id", "version", "tags", "deprecated"}
CATEGORY_VALUES = {"RECOVERABLE", "FAILED", "TIMEOUT"}
STAGE_VALUES = {"DEFAULTS", "VALIDATE", "EXECUTE", "NORMALIZE", "REFINE"}
CODE_VALUES = {
    "DEFAULTS_FAILED",
    "INVALID_INPUT",
    "VALIDATION_FAILED",
    "VALIDATION_RESULT_INVALID",
    "EXECUTION_FAILED",
    "EXECUTION_RESULT_INVALID",
    "REFINEMENT_FAILED",
    "REFINEMENT_RESULT_INVALID",
    "OPERATOR_TIMEOUT",
}


class CaptureOperator(Operator):
    name: ClassVar[str] = "capture"
    description: ClassVar[str] = "Capture adapter arguments."
    shared_default: ClassVar[list[str]] = []
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "required_value": AttributeSpec("str", "Required value", True),
        "items": AttributeSpec("list[str]", "Items to process", False, shared_default),
        "enabled": AttributeSpec("bool", "Whether processing is enabled", False, False),
        "unmaterialized": AttributeSpec("str", "Never materialized", False, "x", False),
    }

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        del input_data, properties
        return [[attributes]]


class RunSpyOperator(Operator):
    name: ClassVar[str] = "run_spy"
    description: ClassVar[str] = "Record the attributes each call receives."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        del input_data, properties
        return [[attributes]]

    def run(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> tuple[list[list[dict[str, Any]]], dict[str, Any], ExecMeta]:
        del input_data, properties
        self.seen.append(attributes)
        return [[dict(attributes)]], {}, ExecMeta(is_empty=False, errors=[], logs=[], traces={})


def _single_server(operator: Operator) -> FastMCP[Any]:
    registry = OperatorRegistry()
    registry.register(operator, "2.0.0")
    return create_server(registry=registry, operator_ids=(f"{operator.name}@2.0.0",))


async def test_meta_matches_exact_mixed_active_selection() -> None:
    tools = await create_server().list_tools()
    assert len(tools) == 33
    assert [(tool.meta or {})["operator_id"] for tool in tools] == list(ACTIVE_OPERATOR_IDS)
    assert {(tool.meta or {})["version"] for tool in tools} == {"2.0.0", "3.0.0"}
    for tool in tools:
        assert set(tool.meta or {}) == {"operator_id", "version", "tags"}
        assert not tool.name.endswith("__refine")


async def test_description_composes_invocation_and_card_text() -> None:
    tools = {tool.name: tool for tool in await create_server().list_tools()}
    cards = {binding.card.name: binding.card for binding in freeze_deployment()}
    for name, card in cards.items():
        expected = "\n\n".join(
            part for part in (card.when_to_invoke.strip(), card.description) if part
        )
        assert tools[name].description == expected


async def test_every_input_schema_requires_only_input_data() -> None:
    tools = await create_server().list_tools()
    assert len(tools) == 33
    for tool in tools:
        schema = tool.inputSchema
        assert schema["required"] == ["input_data"]
        assert schema["properties"]["input_data"]["type"] == "array"
        attributes = schema["properties"]["attributes"]
        assert attributes["additionalProperties"] is True
        assert attributes["default"] == {}
        assert "required" not in attributes
        assert schema["properties"]["properties"]["default"] is None


async def test_capture_input_schema_shape() -> None:
    [tool] = await _single_server(CaptureOperator()).list_tools()
    attributes = tool.inputSchema["properties"]["attributes"]
    assert attributes["additionalProperties"] is True
    assert attributes["default"] == {}
    assert all("type" not in entry for entry in attributes["properties"].values())


def test_required_and_unmaterialized_attributes_omit_defaults() -> None:
    saw_unmaterialized = False
    for binding in freeze_deployment():
        published = _attribute_schema(binding.operator)
        for name, spec in binding.operator.attributes.items():
            entry = published[name]
            if spec.required or not spec.materialize_default:
                assert "default" not in entry, f"{binding.card.name}.{name} must omit its default"
            elif spec.has_default:
                assert entry["default"] == spec.default
            saw_unmaterialized = saw_unmaterialized or not spec.materialize_default
    assert saw_unmaterialized


def test_ordinary_optional_default_is_copied_without_aliasing() -> None:
    operator = CaptureOperator()
    CaptureOperator.shared_default.clear()
    [tool] = _sync_list(_single_server(operator))
    items = _attrs_of(tool)["items"]
    assert items["default"] == []
    items["default"].append("mutated")
    assert CaptureOperator.shared_default == []
    assert operator.attributes["items"].default == []


async def test_all_output_schemas_match_run_result_vocabulary() -> None:
    tools = await create_server().list_tools()
    expected = RunResult.model_json_schema()
    assert len(tools) == 33
    for tool in tools:
        assert tool.outputSchema == expected
    assert expected["required"] == ["output_data", "output_attributes", "exec_meta"]
    assert expected["additionalProperties"] is False
    _assert_error_record_vocabulary(expected)


def test_refine_result_schema_is_absent_but_historical_error_values_remain() -> None:
    assert not hasattr(schema_module, "RefineResult")
    expected = RunResult.model_json_schema()
    _assert_error_record_vocabulary(expected)
    assert "REFINE" in expected["$defs"]["ErrorStage"]["enum"]
    assert "REFINEMENT_FAILED" in expected["$defs"]["ErrorCode"]["enum"]


async def test_omitted_attributes_are_fresh_per_call() -> None:
    operator = RunSpyOperator()
    async with create_connected_server_and_client_session(_single_server(operator)) as client:
        await client.call_tool("run_spy", {"input_data": [[]]})
        await client.call_tool("run_spy", {"input_data": [[]]})
    assert operator.seen == [{}, {}]
    assert operator.seen[0] is not operator.seen[1]


async def test_json_string_preparse_keeps_boolean_string_and_ignores_unknown() -> None:
    operator = RunSpyOperator()
    async with create_connected_server_and_client_session(_single_server(operator)) as client:
        result = await client.call_tool(
            "run_spy",
            {
                "input_data": "[[]]",
                "attributes": '{"enabled":"true"}',
                "properties": "null",
                "ignored_top_level": "dropped",
            },
        )
    assert result.isError is False
    assert operator.seen == [{"enabled": "true"}]
    assert result.structuredContent is not None
    assert result.structuredContent["output_data"] == [[{"enabled": "true"}]]


def _sync_list(server: FastMCP[Any]) -> list[Any]:
    return server._tool_manager.list_tools()  # pyright: ignore[reportPrivateUsage]


def _attrs_of(tool: Any) -> dict[str, Any]:
    return tool.parameters["properties"]["attributes"]["properties"]


def _attribute_schema(operator: Operator) -> dict[str, Any]:
    from blue_data_ops_mcp.schema import attributes_json_schema

    return attributes_json_schema(operator)["properties"]


def _assert_error_record_vocabulary(schema: dict[str, Any]) -> None:
    defs = schema["$defs"]
    error = defs["ErrorRecordModel"]
    assert set(error["required"]) == {
        "category",
        "code",
        "operator_id",
        "stage",
        "message",
        "retryable",
        "suggestion",
    }
    assert error["additionalProperties"] is False
    assert set(defs["ErrorCategory"]["enum"]) == CATEGORY_VALUES
    assert set(defs["ErrorStage"]["enum"]) == STAGE_VALUES
    assert set(defs["ErrorCode"]["enum"]) == CODE_VALUES
    exec_meta = defs["ExecMetaModel"]
    assert set(exec_meta["required"]) == {"is_empty", "errors", "logs", "traces"}

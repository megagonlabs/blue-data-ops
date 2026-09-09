from __future__ import annotations

from typing import Any, ClassVar

from blue_data_ops.operators import (
    AttributeSpec,
    ExecMeta,
    Operator,
    OperatorRegistry,
    versioned_registry,
)
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from blue_data_ops_mcp.registration import freeze_deployment
from blue_data_ops_mcp.schema import RefineResult, RunResult
from blue_data_ops_mcp.server import create_server

REFINE_NAMES = frozenset(
    {
        "multipart_query__refine",
        "nl2query_router__refine",
        "plan_discover__refine",
        "query_breakdown__refine",
    }
)
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


def _single_server(
    operator: Operator, *, tags: tuple[str, ...] = (), when: str = ""
) -> FastMCP[Any]:
    registry = OperatorRegistry()
    registry.register(operator, "2.0.0", tags=tags, when_to_invoke=when)
    return create_server(registry=registry, operator_ids=(f"{operator.name}@2.0.0",))


# Tool metadata


async def test_meta_is_operator_id_version_tags_plus_the_lifecycle_flag() -> None:
    tools = await create_server().list_tools()
    by_name = {tool.name: tool for tool in tools}
    for tool in tools:
        keys = set(tool.meta or {})
        assert keys in ({"operator_id", "version", "tags"}, LIFECYCLE_META_KEYS)
        assert (tool.meta or {})["version"] == "2.0.0"
    select = by_name["select"]
    assert select.meta == {
        "operator_id": "select@2.0.0",
        "version": "2.0.0",
        "tags": [
            "domain-relational",
            "flow-transform",
            "accepts-data",
            "produces-data",
            "capability-filter",
        ],
    }
    # a companion's metadata agrees with its primary — both are annotated here, because this
    # primary's own card is deprecated as well as its seam
    assert by_name["multipart_query__refine"].meta == by_name["multipart_query"].meta
    assert (by_name["multipart_query"].meta or {})["deprecated"] is True


# Tool description


async def test_description_composes_invocation_refinement_and_lifecycle_text() -> None:
    tools = {tool.name: tool for tool in await create_server().list_tools()}
    cards = {card.operator_id: card for card in versioned_registry().list_cards()}
    select_card = cards["select@2.0.0"]
    assert tools["select"].description == (
        f"{select_card.when_to_invoke}\n\n{select_card.description}"
    )
    mq_card = cards["multipart_query@2.0.0"]
    base = f"{mq_card.when_to_invoke}\n\n{mq_card.description}"
    assert tools["multipart_query"].description == (
        f"Deprecated in blue-data-ops 2.8.0; removed in 3.0.0.\n\n{base}"
    )
    assert tools["multipart_query__refine"].description == (
        "Build candidate data-pipeline plans.\n\n"
        "Deprecated in blue-data-ops 2.8.0; removed in 3.0.0. The refinement seam is deprecated "
        f"for every operator.\n\n{base}"
    )


# Input schema


async def test_every_input_schema_requires_only_input_data() -> None:
    tools = await create_server().list_tools()
    assert len(tools) == 40
    for tool in tools:
        schema = tool.inputSchema
        assert schema["required"] == ["input_data"]
        assert schema["properties"]["input_data"]["type"] == "array"
        attributes = schema["properties"]["attributes"]
        assert attributes["additionalProperties"] is True
        assert attributes["default"] == {}
        assert "required" not in attributes
        properties = schema["properties"]["properties"]
        assert properties["default"] is None


async def test_capture_input_schema_shape() -> None:
    [tool] = await _single_server(CaptureOperator()).list_tools()
    attributes = tool.inputSchema["properties"]["attributes"]
    assert attributes["additionalProperties"] is True
    assert attributes["default"] == {}
    assert all("type" not in entry for entry in attributes["properties"].values())


# Default omission


def test_required_and_unmaterialized_attributes_omit_defaults() -> None:
    snapshot = freeze_deployment(versioned_registry())
    unmaterialized = 0
    for binding in snapshot:
        if binding.kind != "primary":
            continue
        published = _attribute_schema(binding.operator)
        for name, spec in binding.operator.attributes.items():
            entry = published[name]
            if spec.required or not spec.materialize_default:
                assert "default" not in entry, f"{binding.card.name}.{name} must omit its default"
            elif spec.has_default:
                assert entry["default"] == spec.default
            if not spec.materialize_default:
                unmaterialized += 1
    # Seven materialize_default=False declarations are defined in this catalog.
    assert unmaterialized == 7


def test_named_seven_publish_no_default() -> None:
    tools = {tool.name: tool for tool in _sync_list(create_server())}
    create_db = _attrs_of(tools["create_database"])
    create_table = _attrs_of(tools["create_table"])
    discover = _attrs_of(tools["data_discover"])
    breakdown = _attrs_of(tools["query_breakdown"])
    assert "default" not in create_db["properties"]
    assert "default" not in create_table["properties"]
    assert "default" not in breakdown["schema"]
    scope_components = [name for name, entry in discover.items() if "default" not in entry]
    assert len(scope_components) >= 4


def test_ordinary_optional_default_is_copied_without_aliasing() -> None:
    operator = CaptureOperator()
    CaptureOperator.shared_default.clear()
    [tool] = _sync_list(_single_server(operator))
    items = _attrs_of(tool)["items"]
    assert items["default"] == []
    items["default"].append("mutated")
    assert CaptureOperator.shared_default == []
    assert operator.attributes["items"].default == []


# Output schema


async def test_primary_output_schema_matches_run_result_vocabulary() -> None:
    tools = [tool for tool in await create_server().list_tools() if tool.name not in REFINE_NAMES]
    expected = RunResult.model_json_schema()
    for tool in tools:
        assert tool.outputSchema == expected
    assert expected["required"] == ["output_data", "output_attributes", "exec_meta"]
    assert expected["additionalProperties"] is False
    _assert_error_record_vocabulary(expected)


async def test_companion_output_schema_matches_refine_result_vocabulary() -> None:
    tools = [tool for tool in await create_server().list_tools() if tool.name in REFINE_NAMES]
    assert len(tools) == 4
    expected = RefineResult.model_json_schema()
    for tool in tools:
        assert tool.outputSchema == expected
    assert expected["required"] == ["plans", "exec_meta"]
    assert expected["additionalProperties"] is False
    plans = expected["properties"]["plans"]
    assert plans["type"] == "array"
    # a plan is the open DataPipeline.to_dict() record, not a constrained shape
    assert plans["items"] == {"type": "object", "additionalProperties": True}
    _assert_error_record_vocabulary(expected)


# v1.2 argument rows


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
    assert operator.seen == [{"enabled": "true"}]  # string, not coerced; unknown key dropped
    assert result.structuredContent is not None
    assert result.structuredContent["output_data"] == [[{"enabled": "true"}]]


# Helpers


def _sync_list(server: FastMCP[Any]) -> list[Any]:
    return server._tool_manager.list_tools()  # pyright: ignore[reportPrivateUsage]


def _attrs_of(tool: Any) -> dict[str, Any]:
    # internal FastMCP tool: the live input schema is `parameters` (mutable, tests aliasing)
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

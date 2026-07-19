from __future__ import annotations

import copy
import json
from typing import Any, ClassVar

from blue_data_ops.operators import AttributeSpec, Operator, OperatorCard
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from blue_data_ops_mcp.registration import OperatorBinding, register_snapshot
from blue_data_ops_mcp.server import create_server


def _text(result: Any) -> str:
    assert len(result.content) == 1
    return str(result.content[0].text)


class CaptureOperator(Operator):
    name: ClassVar[str] = "capture"
    description: ClassVar[str] = "Capture adapter arguments."
    shared_default: ClassVar[list[str]] = []
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "required_value": AttributeSpec("str", "Required value", True),
        "items": AttributeSpec("list[str]", "Items to process", False, shared_default),
        "enabled": AttributeSpec("bool", "Whether processing is enabled", False, False),
    }
    seen: ClassVar[list[dict[str, Any]]] = []

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        self.seen.append(attributes)
        attributes["mutated"] = True
        return [[{"input_data": input_data, "attributes": attributes, "properties": properties}]]


def _capture_server() -> FastMCP[Any]:
    operator = CaptureOperator()
    server: FastMCP[Any] = FastMCP("schema")
    register_snapshot(
        server,
        (
            OperatorBinding(
                OperatorCard("capture@1.0.0", "capture", "1.0.0", operator.description),
                operator,
            ),
        ),
    )
    return server


async def test_schema_requires_only_input_data_and_annotates_known_attributes() -> None:
    [tool] = await _capture_server().list_tools()
    schema = tool.inputSchema
    assert schema["required"] == ["input_data"]
    assert "additionalProperties" not in schema
    assert schema["properties"]["input_data"]["type"] == "array"
    attributes = schema["properties"]["attributes"]
    assert attributes["default"] == {}
    assert attributes["additionalProperties"] is True
    assert "required" not in attributes
    assert attributes["properties"] == {
        "required_value": {"default": None, "description": "Required value"},
        "items": {"default": [], "description": "Items to process"},
        "enabled": {"default": False, "description": "Whether processing is enabled"},
    }
    assert all("type" not in value for value in attributes["properties"].values())
    properties = schema["properties"]["properties"]
    assert properties["default"] is None


async def test_omitted_attributes_are_fresh_and_do_not_alias_core_defaults() -> None:
    CaptureOperator.seen.clear()
    CaptureOperator.shared_default.clear()
    server = _capture_server()
    async with create_connected_server_and_client_session(server) as client:
        first = await client.call_tool("capture", {"input_data": [[]]})
        second = await client.call_tool("capture", {"input_data": [[]]})
    assert first.isError is False and second.isError is False
    assert len(CaptureOperator.seen) == 2
    assert CaptureOperator.seen[0] is not CaptureOperator.seen[1]
    assert CaptureOperator.seen == [{"mutated": True}, {"mutated": True}]
    assert CaptureOperator.shared_default == []


async def test_open_attribute_edges_reach_raw_apply_unchanged() -> None:
    server = _capture_server()
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool(
            "capture",
            {
                "input_data": [[]],
                "attributes": {"unknown": 7, "enabled": "true"},
                "ignored_top_level": "dropped",
            },
        )
    decoded = json.loads(_text(result))
    assert decoded[0][0]["attributes"] == {
        "unknown": 7,
        "enabled": "true",
        "mutated": True,
    }
    assert "ignored_top_level" not in decoded[0][0]


async def test_json_looking_strings_preparse_but_boolean_string_stays_string() -> None:
    server = _capture_server()
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool(
            "capture",
            {
                "input_data": "[[]]",
                "attributes": '{"enabled":"true"}',
                "properties": "null",
            },
        )
    decoded = json.loads(_text(result))[0][0]
    assert decoded == {
        "input_data": [[]],
        "attributes": {"enabled": "true", "mutated": True},
        "properties": None,
    }


async def test_wrong_containers_and_missing_input_are_tool_errors() -> None:
    server = _capture_server()
    bad_calls: list[dict[str, Any]] = [
        {},
        {"input_data": [{"not": "a group"}]},
        {"input_data": [[]], "properties": []},
    ]
    async with create_connected_server_and_client_session(server) as client:
        results = [await client.call_tool("capture", call) for call in bad_calls]
    assert all(result.isError is True for result in results)
    assert all("Error executing tool capture:" in _text(result) for result in results)


def test_schema_defaults_are_deep_copied() -> None:
    before = copy.deepcopy(CaptureOperator.attributes["items"].default)
    server = _capture_server()
    tool = server._tool_manager.list_tools()[0]  # pyright: ignore[reportPrivateUsage]
    tool.parameters["properties"]["attributes"]["properties"]["items"]["default"].append("x")
    assert CaptureOperator.attributes["items"].default == before


async def test_missing_required_operator_attribute_reaches_select_raw_apply() -> None:
    server = create_server(operator_ids=("select@1.0.0",))
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("select", {"input_data": [[{"score": 8}]]})
    assert result.isError is False
    assert json.loads(_text(result)) == [[]]

"""The MCP wire describes only caller settings it accepts, and refuses the rest as documented."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from blue_data_ops.llm.client import RESERVED_OPERATOR_LLM_CONTROLS
from blue_data_ops.operators import versioned_registry
from mcp.shared.memory import create_connected_server_and_client_session

from blue_data_ops_mcp import schema as schema_module
from blue_data_ops_mcp.registration import make_run_handler
from blue_data_ops_mcp.server import create_server

RESERVED = ("operator template and transport controls are reserved",)
BAD_OVERRIDE = (
    "LLM setting is not supported",
    "Use a documented llm.* or provider generation setting.",
)


def test_the_properties_description_does_not_advertise_a_reserved_control() -> None:
    published = schema_module.PROPERTIES_DESCRIPTION
    for control in RESERVED_OPERATOR_LLM_CONTROLS:
        assert f"`{control}`" not in published, control
    assert "service_prefix" not in published
    assert "`execution.timeout_seconds`" in published
    assert "`llm.*`" in published and "`openai.*`" in published


async def test_no_tool_schema_on_the_wire_advertises_service_prefix() -> None:
    server = create_server(operator_ids=("nl2llm@3.0.0", "semantic_filter@3.0.0", "avg@3.0.0"))
    async with create_connected_server_and_client_session(cast(Any, server)._mcp_server) as client:
        tools = (await client.list_tools()).tools
    assert tools
    for tool in tools:
        published = tool.inputSchema["properties"]["properties"]
        assert "service_prefix" not in json.dumps(published), tool.name


async def _nl2llm(properties: dict[str, object]) -> dict[str, object]:
    server = create_server(operator_ids=("nl2llm@3.0.0",))
    async with create_connected_server_and_client_session(cast(Any, server)._mcp_server) as client:
        result = await client.call_tool(
            "ops_nl2llm",
            {"input_data": [[]], "attributes": {"query": "hello"}, "properties": properties},
        )
    assert result.isError is False
    [error] = cast(dict[str, Any], result.structuredContent)["exec_meta"]["errors"]
    return cast(dict[str, object], error)


@pytest.mark.parametrize("control", sorted(RESERVED_OPERATOR_LLM_CONTROLS))
async def test_every_named_control_including_null_stays_reserved_on_the_wire(
    control: str,
) -> None:
    error = await _nl2llm({control: None})
    assert error["code"] == "EXECUTION_FAILED"
    assert (error["message"],) == RESERVED


async def test_an_unknown_provider_prefixed_field_stays_reserved_on_the_wire() -> None:
    assert ((await _nl2llm({"openai.not_a_field": 1}))["message"],) == RESERVED


async def test_an_unknown_llm_setting_is_bad_override_on_the_wire() -> None:
    error = await _nl2llm({"llm.max_token": 5})
    assert (error["message"], error["suggestion"]) == BAD_OVERRIDE
    assert error["retryable"] is False
    assert "max_token" not in json.dumps(error)


async def test_the_sql_preflight_reports_bad_override_before_any_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import blue_data_ops.operators.nl2sql_operator as module

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("no client or registry may be resolved")

    monkeypatch.setattr(module, "resolve_llm_client", forbidden)
    monkeypatch.setattr(module, "resolve_registry", forbidden, raising=False)
    for operator_id in ("nl2sql@3.0.0", "nl2sql@2.0.0"):
        result = await make_run_handler(versioned_registry().resolve(operator_id))(
            [[]],
            {"source": "s", "database": "d", "collection": "c", "question": "q"},
            {"llm.max_token": 5},
        )
        [error] = result.exec_meta.errors
        assert (error.message, error.suggestion) == BAD_OVERRIDE, operator_id

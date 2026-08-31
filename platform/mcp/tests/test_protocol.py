from __future__ import annotations

import asyncio
import builtins
import importlib
import importlib.metadata
import threading
from typing import Any, ClassVar, cast

import httpx
import pytest
from blue_data_ops.operators import AttributeSpec, Operator, OperatorRegistry
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session

from blue_data_ops_mcp.server import create_server

_EXCEPTION_GROUP_TYPE = cast(
    type[BaseException],
    getattr(builtins, "ExceptionGroup", None)
    or getattr(importlib.import_module("exceptiongroup"), "ExceptionGroup"),
)


class GateOperator(Operator):
    name: ClassVar[str] = "gate"
    description: ClassVar[str] = "Wait only when requested."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.done = threading.Event()
        self.completion_order: list[str] = []

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        del input_data, properties
        label = str(attributes["label"])
        if label == "slow":
            self.started.set()
            if not self.release.wait(timeout=5):
                raise TimeoutError("slow gate was not released")
        self.completion_order.append(label)
        self.done.set()
        return [[{"label": label}]]


def _gate_server(operator: GateOperator) -> Any:
    registry = OperatorRegistry()
    registry.register(operator, "2.0.0")
    return create_server(registry=registry, operator_ids=("gate@2.0.0",))


def _output(result: Any) -> Any:
    assert result.isError is False
    return result.structuredContent["output_data"]


async def test_stateful_session_lists_and_calls() -> None:
    server = create_server(operator_ids=("select@2.0.0",))
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools.tools] == ["select"]
        result = await client.call_tool(
            "select",
            {
                "input_data": [[{"a": 5}]],
                "attributes": {"operand_key": "a", "operand": ">", "operand_val": 1},
            },
        )
    assert _output(result) == [[{"a": 5}]]


async def test_server_info_version_is_the_sdk_version() -> None:
    server = create_server(operator_ids=("select@2.0.0",))
    async with create_connected_server_and_client_session(server) as client:
        init = await client.initialize()
    assert init.serverInfo.version == importlib.metadata.version("mcp")
    assert init.serverInfo.version == "1.27.2"


async def test_concurrent_thread_bridged_calls_do_not_block_loop() -> None:
    operator = GateOperator()
    async with create_connected_server_and_client_session(_gate_server(operator)) as client:
        slow = asyncio.create_task(
            client.call_tool("gate", {"input_data": [[]], "attributes": {"label": "slow"}})
        )
        assert await asyncio.wait_for(asyncio.to_thread(operator.started.wait), timeout=2)
        fast = await asyncio.wait_for(
            client.call_tool("gate", {"input_data": [[]], "attributes": {"label": "fast"}}),
            timeout=2,
        )
        operator.release.set()
        slow_result = await asyncio.wait_for(slow, timeout=2)
    assert operator.completion_order == ["fast", "slow"]
    assert _output(fast) == [[{"label": "fast"}]]
    assert _output(slow_result) == [[{"label": "slow"}]]


async def test_unknown_tool_is_sdk_tool_error() -> None:
    async with create_connected_server_and_client_session(
        create_server(operator_ids=("select@2.0.0",))
    ) as client:
        result = await client.call_tool("not_registered", {"input_data": [[]]})
    assert result.isError is True
    block = result.content[0]
    assert isinstance(block, types.TextContent)
    assert "Unknown tool: not_registered" in block.text


async def test_malformed_asgi_requests_are_http_jsonrpc_errors() -> None:
    app = create_server(operator_ids=()).streamable_http_app()
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "origin": "http://127.0.0.1:8000",
    }
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8000"
        ) as client:
            bad_json = await client.post("/mcp", content="{", headers=headers)
            bad_message = await client.post("/mcp", json={}, headers=headers)
    assert bad_json.status_code == 400
    assert bad_json.json()["error"]["code"] == -32700
    assert bad_json.json()["error"]["message"].startswith("Parse error:")
    assert bad_message.status_code == 400
    assert bad_message.json()["error"]["code"] == -32602
    assert bad_message.json()["error"]["message"].startswith("Validation error:")


async def test_protocol_cancellation_is_code_zero_and_worker_continues() -> None:
    operator = GateOperator()
    async with create_connected_server_and_client_session(_gate_server(operator)) as client:
        request_id = client._request_id  # pyright: ignore[reportPrivateUsage]
        task = asyncio.create_task(
            client.call_tool("gate", {"input_data": [[]], "attributes": {"label": "slow"}})
        )
        assert await asyncio.wait_for(asyncio.to_thread(operator.started.wait), timeout=2)
        await client.send_notification(
            types.ClientNotification(
                types.CancelledNotification(
                    params=types.CancelledNotificationParams(requestId=request_id),
                )
            )
        )
        with pytest.raises(McpError) as exc_info:
            await asyncio.wait_for(task, timeout=2)
        assert exc_info.value.error.code == 0
        assert exc_info.value.error.message == "Request cancelled"
        assert operator.done.is_set() is False
        operator.release.set()
        assert await asyncio.wait_for(asyncio.to_thread(operator.done.wait), timeout=2)
    assert operator.completion_order == ["slow"]


async def test_server_down_is_transport_exception() -> None:
    async with httpx.AsyncClient(timeout=0.25) as http_client:
        with pytest.raises(_EXCEPTION_GROUP_TYPE) as exc_info:
            async with streamable_http_client(
                "http://127.0.0.1:1/mcp",
                http_client=http_client,
                terminate_on_close=False,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as client:
                    await client.initialize()
    errors = cast(Any, exc_info.value).exceptions
    assert any(isinstance(error, httpx.ConnectError) for error in errors)

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, ClassVar

import httpx
import pytest
from blue_data_ops.operators import AttributeSpec, Operator, OperatorCard
from exceptiongroup import ExceptionGroup
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.server.fastmcp import FastMCP
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session

from blue_data_ops_mcp.registration import OperatorBinding, register_snapshot
from blue_data_ops_mcp.server import create_server


def _server_for(operator: Operator) -> FastMCP[Any]:
    server: FastMCP[Any] = FastMCP("protocol")
    register_snapshot(
        server,
        (
            OperatorBinding(
                OperatorCard(
                    f"{operator.name}@1.0.0",
                    operator.name,
                    "1.0.0",
                    operator.description,
                ),
                operator,
            ),
        ),
    )
    return server


def _text(result: Any) -> str:
    assert len(result.content) == 1
    return str(result.content[0].text)


class ValidatorSpyOperator(Operator):
    name: ClassVar[str] = "validator_spy"
    description: ClassVar[str] = "Record raw-function routing."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def __init__(self) -> None:
        self.validator_calls = 0

    def validate(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> bool:
        del input_data, attributes, properties
        self.validator_calls += 1
        raise AssertionError("validator called")

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        del input_data, attributes, properties
        return [[{"path": "raw"}]]


class ErrorOperator(Operator):
    name: ClassVar[str] = "explode"
    description: ClassVar[str] = "Raise a function error."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        del input_data, attributes, properties
        raise LookupError("function exploded")


class NullOperator(Operator):
    name: ClassVar[str] = "null_result"
    description: ClassVar[str] = "Return a null raw result."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def apply(  # type: ignore[override]
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> None:
        del input_data, attributes, properties


async def test_validator_is_never_called_w5() -> None:
    operator = ValidatorSpyOperator()
    operator.validator_calls = 0
    direct = operator.apply([[]], {})
    async with create_connected_server_and_client_session(_server_for(operator)) as client:
        result = await client.call_tool("validator_spy", {"input_data": [[]]})
    assert direct == [[{"path": "raw"}]]
    assert result.isError is False
    assert json.loads(_text(result)) == direct
    assert operator.validator_calls == 0


async def test_raw_exception_becomes_tool_error_w6() -> None:
    operator = ErrorOperator()
    with pytest.raises(LookupError, match="function exploded"):
        operator.apply([[]], {})
    async with create_connected_server_and_client_session(_server_for(operator)) as client:
        result = await client.call_tool("explode", {"input_data": [[]]})
    assert result.isError is True
    assert "Error executing tool explode: function exploded" in _text(result)


async def test_none_survives_as_one_json_text_block() -> None:
    async with create_connected_server_and_client_session(_server_for(NullOperator())) as client:
        result = await client.call_tool("null_result", {"input_data": [[]]})
    assert result.isError is False
    assert result.structuredContent is None
    assert _text(result) == "null"


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


async def test_concurrent_thread_bridged_calls_do_not_block_loop_w11() -> None:
    operator = GateOperator()
    async with create_connected_server_and_client_session(_server_for(operator)) as client:
        slow = asyncio.create_task(
            client.call_tool(
                "gate",
                {"input_data": [[]], "attributes": {"label": "slow"}},
            )
        )
        assert await asyncio.wait_for(asyncio.to_thread(operator.started.wait), timeout=1)
        fast = await asyncio.wait_for(
            client.call_tool(
                "gate",
                {"input_data": [[]], "attributes": {"label": "fast"}},
            ),
            timeout=1,
        )
        operator.release.set()
        slow_result = await asyncio.wait_for(slow, timeout=1)
    assert operator.completion_order == ["fast", "slow"]
    assert json.loads(_text(fast)) == [[{"label": "fast"}]]
    assert json.loads(_text(slow_result)) == [[{"label": "slow"}]]


async def test_unknown_tool_is_sdk_tool_error_w13() -> None:
    async with create_connected_server_and_client_session(
        create_server(operator_ids=("select@1.0.0",))
    ) as client:
        result = await client.call_tool("not_registered", {"input_data": [[]]})
    assert result.isError is True
    assert "Unknown tool: not_registered" in _text(result)


async def test_malformed_asgi_requests_are_http_jsonrpc_errors_w14() -> None:
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


async def test_protocol_cancellation_is_code_zero_and_worker_continues_w15() -> None:
    operator = GateOperator()
    server = _server_for(operator)
    async with create_connected_server_and_client_session(server) as client:
        request_id = client._request_id  # pyright: ignore[reportPrivateUsage]
        task = asyncio.create_task(
            client.call_tool(
                "gate",
                {"input_data": [[]], "attributes": {"label": "slow"}},
            )
        )
        assert await asyncio.wait_for(asyncio.to_thread(operator.started.wait), timeout=1)
        await client.send_notification(
            types.ClientNotification(
                types.CancelledNotification(
                    params=types.CancelledNotificationParams(requestId=request_id),
                )
            )
        )
        with pytest.raises(McpError) as exc_info:
            await asyncio.wait_for(task, timeout=1)
        assert exc_info.value.error.code == 0
        assert exc_info.value.error.message == "Request cancelled"
        assert operator.done.is_set() is False
        operator.release.set()
        assert await asyncio.wait_for(asyncio.to_thread(operator.done.wait), timeout=1)
    assert operator.completion_order == ["slow"]


async def test_server_down_is_transport_exception_w16() -> None:
    async with httpx.AsyncClient(timeout=0.25) as http_client:
        with pytest.raises(ExceptionGroup) as exc_info:
            async with streamable_http_client(
                "http://127.0.0.1:1/mcp",
                http_client=http_client,
                terminate_on_close=False,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as client:
                    await client.initialize()
    assert any(isinstance(error, httpx.ConnectError) for error in exc_info.value.exceptions)

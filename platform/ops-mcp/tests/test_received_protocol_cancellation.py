from __future__ import annotations

import asyncio
import threading
from typing import Any, ClassVar

import pytest
from blue_data.registry.data_registry import DataRegistry  # pyright: ignore[reportMissingTypeStubs]
from blue_data_ops.operators import AttributeSpec, Operator, OperatorRegistry
from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCRequest

from blue_data_ops_mcp.data_registry import DeploymentRegistry
from blue_data_ops_mcp.server import create_server

pytestmark = pytest.mark.asyncio


class GateOperator(Operator):
    name: ClassVar[str] = "received_cancel_gate"
    description: ClassVar[str] = "Synthetic registry admission gate."
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "label": AttributeSpec("str", "Synthetic call label", True),
    }

    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list[str] = []

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        del input_data, properties
        label = str(attributes["label"])
        self.calls.append(label)
        if label == "active":
            self.started.set()
            if not self.release.wait(timeout=5):
                raise RuntimeError("synthetic active call was not released")
        return [[{"label": label}]]


class RequestRecorder:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.requests: dict[str, int | str] = {}
        self.sent: dict[str, asyncio.Event] = {}

    async def send(self, message: SessionMessage) -> None:
        root = message.message.root
        label: str | None = None
        if isinstance(root, JSONRPCRequest):
            payload: dict[str, dict[str, dict[str, dict[str, Any]]]] = root.model_dump(
                by_alias=True, mode="json", exclude_none=True
            )
            arguments = (payload.get("params") or {}).get("arguments") or {}
            label_value = (arguments.get("attributes") or {}).get("label")
            if label_value is not None:
                label = str(label_value)
                self.requests[label] = root.id
        await self.inner.send(message)
        if label is not None:
            self.sent.setdefault(label, asyncio.Event()).set()

    async def request_id(self, label: str) -> int | str:
        await asyncio.wait_for(self.sent.setdefault(label, asyncio.Event()).wait(), timeout=2)
        return self.requests[label]


async def _call(client: Any, label: str) -> Any:
    return await client.call_tool(
        "ops_received_cancel_gate",
        {"input_data": [[]], "attributes": {"label": label}},
    )


async def _cancel(client: Any, request_id: int | str) -> None:
    await client.send_notification(
        types.ClientNotification(
            types.CancelledNotification(
                params=types.CancelledNotificationParams(
                    requestId=request_id,
                    reason="synthetic received cancellation",
                )
            )
        )
    )


async def test_received_cancellation_removes_admitted_waiter_and_lane_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = GateOperator()
    registry = OperatorRegistry()
    registry.register(operator, "2.0.0", tags=("requires-data-registry",))
    server = create_server(
        registry=registry,
        data_registry=DataRegistry(),
        operator_ids=("received_cancel_gate@2.0.0",),
    )

    waiting_in_run = asyncio.Event()
    original_run = DeploymentRegistry.run

    async def observed_run(
        self: DeploymentRegistry,
        selected: Any,
        input_data: Any,
        attributes: dict[str, Any],
        properties: dict[str, Any] | None,
        *,
        bound_execution: bool = False,
    ) -> Any:
        if attributes.get("label") == "cancelled-waiter":
            waiting_in_run.set()
        return await original_run(
            self,
            selected,
            input_data,
            attributes,
            properties,
            bound_execution=bound_execution,
        )

    monkeypatch.setattr(DeploymentRegistry, "run", observed_run)

    async with create_connected_server_and_client_session(server) as client:
        recorder = RequestRecorder(client._write_stream)  # pyright: ignore[reportPrivateUsage]
        client._write_stream = recorder  # type: ignore[assignment]  # pyright: ignore[reportPrivateUsage]

        active = asyncio.create_task(_call(client, "active"))
        assert await asyncio.wait_for(asyncio.to_thread(operator.started.wait), timeout=2)

        cancelled = asyncio.create_task(_call(client, "cancelled-waiter"))
        request_id = await recorder.request_id("cancelled-waiter")
        await asyncio.wait_for(waiting_in_run.wait(), timeout=2)
        await _cancel(client, request_id)
        outcome = await asyncio.gather(cancelled, return_exceptions=True)
        assert isinstance(outcome[0], BaseException)
        assert operator.calls == ["active"]

        operator.release.set()
        active_result = await asyncio.wait_for(active, timeout=3)
        assert active_result.isError is False
        fresh_result = await asyncio.wait_for(_call(client, "fresh"), timeout=3)
        assert fresh_result.isError is False

    assert operator.calls == ["active", "fresh"]

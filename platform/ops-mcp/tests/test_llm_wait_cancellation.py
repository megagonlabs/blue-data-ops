from __future__ import annotations

import asyncio
import json
import re
import threading
from typing import Any

import litellm
import pytest
from blue_data.registry.data_registry import DataRegistry  # pyright: ignore[reportMissingTypeStubs]
from blue_data_ops import _execution_scope as scope
from blue_data_ops.operators import SemanticJoinOperator
from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCRequest

from blue_data_ops_mcp.data_registry import DeploymentRegistry
from blue_data_ops_mcp.registration import make_run_handler
from blue_data_ops_mcp.server import create_server

pytestmark = pytest.mark.asyncio
DATA = [[{"name": value} for value in "abc"], [{"name": value} for value in "ABC"]]
ATTRIBUTES = {
    "left_fields": ["name"],
    "right_fields": ["name"],
    "join_predicate": "same name",
    "batch_size": 3,
    "estimate_cost": False,
}
PROPERTIES = {"llm.model": "gpt-4o-mini", "llm.rate_limit": 0.1}


class ObservedWait:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.started = threading.Event()
        self.finished = threading.Event()
        self.scopes: list[scope.ExecutionScope] = []
        self.calls = 0
        original = scope.wait_sync

        def wait(seconds: float) -> None:
            current = scope._CURRENT.get()  # pyright: ignore[reportPrivateUsage]
            if current is not None:
                self.scopes.append(current)
            self.started.set()
            try:
                original(seconds)
            finally:
                self.finished.set()

        def completion(**kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            prompt = " ".join(message["content"] for message in kwargs["messages"])
            count = len(re.findall(r"Pair \d+:", prompt))
            answer = json.dumps({f"pair_{index}": True for index in range(1, count + 1)})
            return {"choices": [{"message": {"content": answer}}]}

        monkeypatch.setattr(scope, "wait_sync", wait)
        monkeypatch.setattr(litellm, "completion", completion)

        def cost(**kwargs: Any) -> float:
            return 0.0

        monkeypatch.setattr(litellm, "completion_cost", cost)

    def release(self) -> None:
        for current in self.scopes:
            current.stop.set()


async def observed(event: threading.Event, timeout: float = 0.75) -> None:
    async def poll() -> None:
        while not event.is_set():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), timeout)


@pytest.mark.parametrize("registry_lane", [False, True])
async def test_handler_cancellation_retires_rate_wait(
    registry_lane: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wait = ObservedWait(monkeypatch)
    deployment = DeploymentRegistry(DataRegistry()) if registry_lane else None
    handler = make_run_handler(
        SemanticJoinOperator(), deployment=deployment, requires_registry=registry_lane
    )
    task = asyncio.create_task(handler(DATA, ATTRIBUTES, PROPERTIES))
    try:
        await observed(wait.started)
        assert wait.calls == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await observed(wait.finished)
        await asyncio.sleep(0.075)
        assert wait.calls == 1
    finally:
        wait.release()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    if deployment is not None:

        async def drained() -> None:
            while deployment._workers or deployment._draining:  # pyright: ignore[reportPrivateUsage]
                await asyncio.sleep(0.005)

        await asyncio.wait_for(drained(), 0.75)
        assert not deployment._admission.locked()  # pyright: ignore[reportPrivateUsage]


async def test_registry_deadline_retires_rate_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    wait = ObservedWait(monkeypatch)
    deployment = DeploymentRegistry(DataRegistry())
    handler = make_run_handler(
        SemanticJoinOperator(), deployment=deployment, requires_registry=True
    )
    original_wait = asyncio.wait

    async def expire_at_rate_wait(futures: Any, *, timeout: float | None = None) -> Any:
        if timeout is not None:
            assert timeout == 60.0
            await observed(wait.started, timeout=5.0)
            assert wait.calls == 1
            # Expire the adapter wait only after the worker reaches rate pacing.
            timeout = 0
        return await original_wait(futures, timeout=timeout)

    monkeypatch.setattr(asyncio, "wait", expire_at_rate_wait)
    try:
        result = await asyncio.wait_for(
            handler(DATA, ATTRIBUTES, {**PROPERTIES, "execution.timeout_seconds": 60.0}),
            10.0,
        )
        assert result.exec_meta.errors[0].code == "OPERATOR_TIMEOUT"
        assert wait.scopes
        for current in wait.scopes:
            assert current.parent is not None
            assert current.parent.stop.is_set()
        await observed(wait.finished, timeout=5.0)

        async def drained() -> None:
            while deployment._workers or deployment._draining:  # pyright: ignore[reportPrivateUsage]
                await asyncio.sleep(0.005)

        await asyncio.wait_for(drained(), 5.0)
        assert not deployment._admission.locked()  # pyright: ignore[reportPrivateUsage]
        assert wait.calls == 1
    finally:
        wait.release()


class RequestRecorder:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.request_id: int | str | None = None
        self.sent = asyncio.Event()

    async def send(self, message: SessionMessage) -> None:
        root = message.message.root
        if isinstance(root, JSONRPCRequest) and root.method == "tools/call":
            self.request_id = root.id
        await self.inner.send(message)
        if self.request_id is not None:
            self.sent.set()


async def test_received_cancellation_retires_rate_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    wait = ObservedWait(monkeypatch)
    server = create_server()
    try:
        async with create_connected_server_and_client_session(server) as client:
            recorder = RequestRecorder(client._write_stream)  # pyright: ignore[reportPrivateUsage]
            client._write_stream = recorder  # type: ignore[assignment]  # pyright: ignore[reportPrivateUsage]
            task = asyncio.create_task(
                client.call_tool(
                    "ops_semantic_join",
                    {
                        "input_data": DATA,
                        "attributes": ATTRIBUTES,
                        "properties": PROPERTIES,
                    },
                )
            )
            try:
                await asyncio.wait_for(recorder.sent.wait(), 0.75)
                await observed(wait.started)
                assert recorder.request_id is not None
                await client.send_notification(
                    types.ClientNotification(
                        types.CancelledNotification(
                            params=types.CancelledNotificationParams(
                                requestId=recorder.request_id, reason="cancel paced call"
                            ),
                        )
                    )
                )
                result = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 0.75)
                assert isinstance(result[0], BaseException)
                await observed(wait.finished)
                await asyncio.sleep(0.075)
                assert wait.calls == 1
            finally:
                wait.release()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    finally:
        wait.release()

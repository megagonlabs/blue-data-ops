"""An operator timeout returns to the caller and holds the registry lane until the worker drains.

The server owns the deadline for registry calls. When it expires, the caller gets core's
``OPERATOR_TIMEOUT`` record at once, but admission stays with the running worker, so no
queued or new registry call overlaps it. When the worker really finishes, admission is
released exactly once and the lane carries on with no restart.
"""

from __future__ import annotations

import asyncio
import gc
import sqlite3
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace
from typing import Any, Literal, NoReturn, cast

import pytest
from blue_data.registry.data_registry import DataRegistry  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.json.memory_json_source import MemoryJSONSource  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource  # pyright: ignore[reportMissingTypeStubs]
from blue_data_ops.data import RegistrySeam
from blue_data_ops.llm import LLMClient
from blue_data_ops.llm.sql_execution import ReadOnlySQLExecutor
from blue_data_ops.operators import FunctionResult, Operator, OperatorRegistry
from blue_data_ops.operators._nl2sql_outcome import NL2SQLOutcomeOperator
from blue_data_ops.operators.types import Attributes, DataBundle, Properties
from mcp.shared.memory import create_connected_server_and_client_session

from blue_data_ops_mcp.data_registry import DeploymentRegistry
from blue_data_ops_mcp.registration import make_run_handler, run_payload
from blue_data_ops_mcp.schema import RunResult
from blue_data_ops_mcp.server import SERVER_INSTRUCTIONS, create_server

ROOT = Path(__file__).resolve().parents[1]
DEADLINE = {"execution.timeout_seconds": 0.05}


async def until(predicate: Callable[[], bool]) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(poll(), 3)


class Gate(Operator):
    """Blocks in its body until released; counts bodies and their overlap."""

    name = "gate"

    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self.finish = Event()
        self.calls = 0
        self.active = 0
        self.most_active = 0
        self.seen: list[dict[str, Any] | None] = []
        self._count = Lock()

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
        with self._count:
            self.calls += 1
            self.active += 1
            self.most_active = max(self.most_active, self.active)
            self.seen.append(None if properties is None else dict(properties))
        try:
            self.started.set()
            assert self.finish.wait(5)
            return FunctionResult(input_data, {})
        finally:
            with self._count:
                self.active -= 1


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


class RaisingRun(Operator):
    """An operator whose own ``run()`` raises, after an optional wait."""

    name = "raising"

    def __init__(self, error: BaseException, wait: bool) -> None:
        super().__init__()
        self.error = error
        self.wait = wait
        self.started = Event()
        self.finish = Event()

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        return input_data

    def run(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> NoReturn:
        self.started.set()
        if self.wait:
            assert self.finish.wait(5)
        raise self.error


class CountingLock(asyncio.Lock):
    def __init__(self) -> None:
        super().__init__()
        self.acquired = 0
        self.released = 0
        self.on_release: Callable[[], object] | None = None

    async def acquire(self) -> Literal[True]:
        result = await super().acquire()
        self.acquired += 1
        return result

    def release(self) -> None:
        self.released += 1
        if self.on_release is not None:
            self.on_release()
        super().release()


def deployment_with_counting_lock() -> tuple[DeploymentRegistry, CountingLock]:
    deployment = DeploymentRegistry(DataRegistry())
    lock = CountingLock()
    cast(Any, deployment)._admission = lock
    return deployment, lock


def unretrieved(loop: asyncio.AbstractEventLoop) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    loop.set_exception_handler(lambda _loop, context: reports.append(context))
    return reports


def is_timeout(result: Any) -> bool:
    return [error.code for error in result.exec_meta.errors] == ["OPERATOR_TIMEOUT"]


@pytest.mark.parametrize("cancel_awaiter", [False, True])
async def test_timeout_returns_but_the_lane_waits_for_the_real_drain(cancel_awaiter: bool) -> None:
    op = Gate()
    deployment, lock = deployment_with_counting_lock()
    handler = make_run_handler(op, deployment=deployment, requires_registry=True)
    running = asyncio.create_task(handler([[{}]], properties=dict(DEADLINE)))
    await until(op.started.is_set)
    queued = [asyncio.create_task(handler([[{}]])) for _ in range(3)]
    try:
        if cancel_awaiter:
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
            await asyncio.sleep(0.1)
        else:
            assert is_timeout(await running)
        # The caller has its answer; the worker has not finished and still owns the lane.
        assert op.calls == 1
        assert not op.finish.is_set()
        assert lock.locked()
        assert not any(task.done() for task in queued)
        # Untagged tools and other servers are not behind this lane.
        assert (await make_run_handler(Immediate())([[{}]])).exec_meta.errors == []
        other = DeploymentRegistry(DataRegistry())
        assert (
            await make_run_handler(Immediate(), deployment=other, requires_registry=True)([[{}]])
        ).exec_meta.errors == []
    finally:
        op.finish.set()
    results = await asyncio.gather(*queued)
    assert all(result.exec_meta.errors == [] for result in results)
    assert (await handler([[{}]])).exec_meta.errors == []
    assert op.calls == 5
    assert op.most_active == 1
    await until(lambda: not lock.locked())
    assert lock.acquired == lock.released == 5


async def test_the_timeout_record_is_core_s_record() -> None:
    op = Gate()
    deployment = DeploymentRegistry(DataRegistry())
    handler = make_run_handler(op, deployment=deployment, requires_registry=True)
    try:
        served = await handler([[{}]], properties=dict(DEADLINE))
    finally:
        op.finish.set()
    core_op = Gate()
    try:
        core = core_op.run([[{}]], {}, dict(DEADLINE))
    finally:
        core_op.finish.set()
    assert (
        served.model_dump()
        == cast(type[RunResult], type(served)).model_validate(run_payload(core)).model_dump()
    )
    [error] = served.exec_meta.errors
    assert (error.category, error.code, error.stage) == ("TIMEOUT", "OPERATOR_TIMEOUT", "EXECUTE")
    assert error.message == "operator timed out"
    assert error.suggestion is None and error.retryable is False


async def test_a_draining_worker_is_strongly_held_until_it_finishes() -> None:
    op = Gate()
    deployment = DeploymentRegistry(DataRegistry())
    handler = make_run_handler(op, deployment=deployment, requires_registry=True)
    try:
        assert is_timeout(await handler([[{}]], properties=dict(DEADLINE)))
        gc.collect()
        assert len(cast(Any, deployment)._draining) == 1
        assert cast(Any, deployment)._admission.locked()
    finally:
        op.finish.set()
    await until(lambda: not cast(Any, deployment)._draining)
    assert not cast(Any, deployment)._admission.locked()


async def test_a_queued_call_cancelled_during_the_drain_never_runs() -> None:
    op = Gate()
    deployment, lock = deployment_with_counting_lock()
    handler = make_run_handler(op, deployment=deployment, requires_registry=True)
    assert is_timeout(await asyncio.wait_for(handler([[{}]], properties=dict(DEADLINE)), 3))
    queued = asyncio.create_task(handler([[{}]]))
    kept = asyncio.create_task(handler([[{}]]))
    await asyncio.sleep(0.02)
    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued
    op.finish.set()
    assert (await kept).exec_meta.errors == []
    assert op.calls == 2
    await until(lambda: not lock.locked())
    assert lock.acquired == lock.released == 2


async def test_a_worker_that_never_drains_keeps_the_lane_and_queued_calls_can_leave() -> None:
    op = Gate()
    deployment = DeploymentRegistry(DataRegistry())
    handler = make_run_handler(op, deployment=deployment, requires_registry=True)
    try:
        assert is_timeout(await handler([[{}]], properties=dict(DEADLINE)))
        queued = asyncio.create_task(handler([[{}]]))
        await asyncio.sleep(0.2)
        assert not queued.done()
        assert op.calls == 1
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert op.calls == 1
        assert cast(Any, deployment)._admission.locked()
    finally:
        op.finish.set()
    await until(lambda: not cast(Any, deployment)._admission.locked())
    assert (await handler([[{}]])).exec_meta.errors == []
    assert op.calls == 2


async def test_the_deadline_is_removed_from_the_body_and_the_caller_s_dict_is_kept() -> None:
    op = Gate()
    op.finish.set()
    deployment = DeploymentRegistry(DataRegistry())
    handler = make_run_handler(op, deployment=deployment, requires_registry=True)
    properties = {"execution.timeout_seconds": 5, "platform.name": "caller"}
    assert (await handler([[{}]], properties=properties)).exec_meta.errors == []
    assert properties == {"execution.timeout_seconds": 5, "platform.name": "caller"}
    assert op.seen[0] is not None
    assert "execution.timeout_seconds" not in op.seen[0]
    assert "platform.name" not in op.seen[0]


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True, "1", None])
async def test_invalid_timeouts_are_core_s_validation_error_with_no_body(value: Any) -> None:
    op = Gate()
    op.finish.set()
    deployment, lock = deployment_with_counting_lock()
    handler = make_run_handler(op, deployment=deployment, requires_registry=True)
    result = await handler([[{}]], properties={"execution.timeout_seconds": value})
    [error] = result.exec_meta.errors
    assert (error.code, error.stage) == ("INVALID_INPUT", "VALIDATE")
    assert error.message == "invalid execution timeout"
    assert op.calls == 0
    assert not lock.locked() and lock.acquired == lock.released == 1


async def test_a_worker_raised_timeout_error_is_not_a_caller_deadline() -> None:
    reports = unretrieved(asyncio.get_running_loop())
    op = RaisingRun(TimeoutError("raised by the operator itself"), wait=False)
    deployment, lock = deployment_with_counting_lock()
    handler = make_run_handler(op, deployment=deployment, requires_registry=True)
    result = await handler([[{}]], properties={"execution.timeout_seconds": 5})
    [error] = result.exec_meta.errors
    assert error.code == "EXECUTION_FAILED"
    assert error.message == "operator execution failed"
    assert error.suggestion is None and error.retryable is False
    assert not lock.locked() and lock.acquired == lock.released == 1
    assert cast(Any, deployment)._draining == set()
    assert (
        await make_run_handler(Immediate(), deployment=deployment, requires_registry=True)([[{}]])
    ).exec_meta.errors == []
    gc.collect()
    assert reports == []


async def test_a_late_worker_failure_is_consumed_and_releases_exactly_once() -> None:
    loop = asyncio.get_running_loop()
    reports = unretrieved(loop)
    op = RaisingRun(RuntimeError("late synthetic failure"), wait=True)
    deployment, lock = deployment_with_counting_lock()
    handler = make_run_handler(op, deployment=deployment, requires_registry=True)
    try:
        assert is_timeout(await handler([[{}]], properties=dict(DEADLINE)))
        [worker] = cast(Any, deployment)._draining
        order: list[tuple[bool, bool]] = []
        lock.on_release = lambda: order.append((worker.done(), worker._log_traceback))
        follower = asyncio.create_task(
            make_run_handler(Immediate(), deployment=deployment, requires_registry=True)([[{}]])
        )
        await asyncio.sleep(0.02)
        assert not follower.done()
    finally:
        op.finish.set()
    assert (await follower).exec_meta.errors == []
    await until(lambda: not lock.locked())
    assert lock.acquired == lock.released == 2
    # The drain released after the contained late result, then the follower.
    assert order[0] == (True, False)
    assert worker.exception() is None
    late = worker.result()
    assert late[2].errors[0].code == "EXECUTION_FAILED"
    assert late[2].errors[0].message == "operator execution failed"
    assert cast(Any, deployment)._draining == set()
    gc.collect()
    await asyncio.sleep(0)
    assert reports == []


async def test_completion_at_the_deadline_boundary_is_a_result_not_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the wait reports expiry but the worker has already finished, use its result."""
    import blue_data_ops_mcp.data_registry as module

    real_wait = asyncio.wait

    async def wait_that_expires_late(futures: Any, *args: Any, **kwargs: Any) -> Any:
        futures = set(futures)
        await real_wait(futures)
        return set(), futures

    monkeypatch.setattr(
        module,
        "asyncio",
        SimpleNamespace(**{**vars(asyncio), "wait": wait_that_expires_late}),
    )
    op = Gate()
    op.finish.set()
    deployment, lock = deployment_with_counting_lock()
    handler = make_run_handler(op, deployment=deployment, requires_registry=True)
    result = await handler([[{"kept": True}]], properties=dict(DEADLINE))
    assert result.exec_meta.errors == []
    assert result.output_data == [[{"kept": True}]]
    assert not lock.locked() and lock.acquired == lock.released == 1
    assert cast(Any, deployment)._draining == set()


async def test_the_initial_build_is_outside_the_deadline_and_the_body_inside_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import blue_data_ops_mcp.data_registry as module

    started, finish = Event(), Event()
    seam = RegistrySeam(DataRegistry())

    def build(**kwargs: Any) -> Any:
        started.set()
        assert finish.wait(5)
        return seam

    monkeypatch.setattr(module, "build_environment_registry", build)
    op = Gate()
    deployment = DeploymentRegistry()
    task = asyncio.create_task(
        make_run_handler(op, deployment=deployment, requires_registry=True)(
            [[{}]], properties=dict(DEADLINE)
        )
    )
    await until(started.is_set)
    await asyncio.sleep(0.1)
    assert not task.done()
    finish.set()
    try:
        assert is_timeout(await task)
        assert deployment.state == "READY" and cast(Any, deployment)._admission.locked()
    finally:
        op.finish.set()
    await until(lambda: not cast(Any, deployment)._admission.locked())


class SQLClient(LLMClient):
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def execute_api_call(
        self,
        input: Any,
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append(properties)
        return deepcopy({"query": "SELECT id, value FROM records"})


async def test_bound_sql_queued_behind_a_draining_worker_waits_for_the_drain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import blue_data_ops.operators.nl2sql_operator as sql_module

    with sqlite3.connect(tmp_path / "db.db") as connection:
        connection.execute("CREATE TABLE records (id INTEGER, value TEXT)")
        connection.execute("INSERT INTO records VALUES (1, 'synthetic')")
    registry = DataRegistry(store=MemoryJSONSource(), rebuild=False)
    registry.register_source(
        SQLiteDBSource("approved", properties={"connection": {"database_directory": str(tmp_path)}})
    )
    capability = ReadOnlySQLExecutor(registry, frozenset({("approved", "db", "public")}))
    client = SQLClient()
    cast(
        Callable[
            [object, str, Callable[[dict[str, Any] | None], SQLClient]],
            None,
        ],
        monkeypatch.setattr,
    )(
        sql_module,
        "resolve_llm_client",
        lambda properties: client,
    )
    sql = OperatorRegistry()
    cast(Any, sql)._register_builtin(
        NL2SQLOutcomeOperator(read_only_executor=capability),
        "3.0.0",
        tags=("requires-data-registry",),
    )
    sql_operator = sql.resolve("nl2sql@3.0.0")

    op = Gate()
    deployment = DeploymentRegistry(DataRegistry())
    gate = make_run_handler(op, deployment=deployment, requires_registry=True)
    bound = make_run_handler(sql_operator, deployment=deployment, requires_registry=True)
    attributes = {
        "source": "approved",
        "database": "db",
        "collection": "public",
        "protocol": "sqlite",
        "question": "list rows",
    }
    try:
        assert is_timeout(await gate([[{}]], properties=dict(DEADLINE)))
        queued = asyncio.create_task(bound([[]], attributes, {"execute_query": True}))
        await asyncio.sleep(0.1)
        assert not queued.done()
        assert client.calls == []
    finally:
        op.finish.set()
    result = await queued
    assert result.exec_meta.errors == []
    assert len(client.calls) == 1


async def test_real_protocol_timeout_then_the_next_call_runs_after_the_drain() -> None:
    op = Gate()
    registry = OperatorRegistry()
    registry.register(op, "2.0.0", tags=("requires-data-registry",))
    server = create_server(
        registry=registry, data_registry=DataRegistry(), operator_ids=("gate@2.0.0",)
    )
    async with create_connected_server_and_client_session(cast(Any, server)._mcp_server) as client:
        try:
            first = await client.call_tool(
                "ops_gate", {"input_data": [[{}]], "properties": dict(DEADLINE)}
            )
            assert first.isError is False
            assert [
                e["code"]
                for e in cast(dict[str, Any], first.structuredContent)["exec_meta"]["errors"]
            ] == ["OPERATOR_TIMEOUT"]
            second = asyncio.create_task(client.call_tool("ops_gate", {"input_data": [[{"n": 2}]]}))
            await asyncio.sleep(0.1)
            assert not second.done()
            assert op.calls == 1
        finally:
            op.finish.set()
        result = await second
        assert cast(dict[str, Any], result.structuredContent)["exec_meta"]["errors"] == []
        assert cast(dict[str, Any], result.structuredContent)["output_data"] == [[{"n": 2}]]
    assert op.most_active == 1


async def test_real_protocol_data_discover_tiny_deadline_does_not_suspend_the_lane() -> None:
    server = create_server(data_registry=DataRegistry(), operator_ids=("data_discover@2.0.0",))
    arguments: dict[str, Any] = {
        "input_data": [[]],
        "attributes": {"search_query": "none", "approximate": False},
    }
    async with create_connected_server_and_client_session(cast(Any, server)._mcp_server) as client:
        first = await client.call_tool(
            "ops_data_discover", {**arguments, "properties": {"execution.timeout_seconds": 1e-9}}
        )
        assert first.isError is False
        codes = [
            e["code"] for e in cast(dict[str, Any], first.structuredContent)["exec_meta"]["errors"]
        ]
        assert codes in ([], ["OPERATOR_TIMEOUT"])
        second = await asyncio.wait_for(client.call_tool("ops_data_discover", arguments), 5)
    assert second.isError is False
    assert cast(dict[str, Any], second.structuredContent)["exec_meta"]["errors"] == []


def test_the_published_contract_describes_the_drain_not_a_restart() -> None:
    paragraphs = {
        "SERVER_INSTRUCTIONS": SERVER_INSTRUCTIONS,
        "README.md": (ROOT / "README.md").read_text(encoding="utf-8"),
        "docs/mcp.md": (ROOT.parents[1] / "docs/mcp.md").read_text(encoding="utf-8"),
        "docs/guide.md": (ROOT.parents[1] / "docs/guide.md").read_text(encoding="utf-8"),
    }
    for name, text in paragraphs.items():
        flat = " ".join(text.split())
        assert "until restart" not in flat, name
        assert "suspends later registry calls" not in flat, name
        assert "suspends that server's registry lane" not in flat, name
        assert "until the worker finishes" in flat, name

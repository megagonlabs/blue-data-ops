from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any, ClassVar, cast

import pytest
from blue_data_ops.operators import (
    AttributeSpec,
    ExecMeta,
    Operator,
    OperatorRegistry,
    PlanDiscoverOperator,
    ProjectOperator,
    SelectOperator,
    versioned_registry,
)
from blue_data_ops.operators import query_breakdown_operator as qb_module
from blue_data_ops.plan import RefinableOperator
from blue_data_ops.plan import pipeline as pipeline_module
from blue_data_ops.plan.types import PlanRecord
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from blue_data_ops_mcp.registration import refine_payload, run_payload
from blue_data_ops_mcp.server import create_server

VALID_INPUT: list[list[dict[str, Any]]] = [[{"id": 1, "score": 8}, {"id": 2, "score": 2}]]
GT5: dict[str, Any] = {"operand_key": "score", "operand": ">", "operand_val": 5}

EMPTY_CASES: list[tuple[list[list[dict[str, Any]]], dict[str, Any]]] = [
    ([[{"score": 8}]], {"operand_key": "score", "operand": ">", "operand_val": 99}),
    ([[]], GT5),
    ([[], []], GT5),
]
BAD_ARGUMENTS: list[dict[str, Any]] = [
    {},  # input_data omitted
    {"input_data": [{"not": "a group"}]},  # not list[list[dict]]
    {"input_data": [[]], "properties": []},  # properties is not an object/null
]


# Helpers


async def _call(server: FastMCP[Any], name: str, arguments: dict[str, Any]) -> Any:
    async with create_connected_server_and_client_session(server) as client:
        return await client.call_tool(name, arguments)


def _single_server(operator: Operator) -> FastMCP[Any]:
    registry = OperatorRegistry()
    registry.register(operator, "2.0.0")
    return create_server(registry=registry, operator_ids=(f"{operator.name}@2.0.0",))


def _errors(result: Any) -> list[dict[str, Any]]:
    return result.structuredContent["exec_meta"]["errors"]


def _first_error(result: Any) -> dict[str, Any]:
    errors = _errors(result)
    assert len(errors) == 1, errors
    return errors[0]


def _id_sequence(prefix: str = "wire") -> Callable[[], str]:
    current = 0

    def next_id() -> str:
        nonlocal current
        current += 1
        return f"{prefix}-{current:04d}"

    return next_id


def _cte(table: str, dependency: list[str] | None = None) -> dict[str, Any]:
    return {
        "description": f"find {table}",
        "sql": f"select * from {table}",
        "table": table,
        "columns": [{"name": "value", "type": "str"}],
        "dependency": [] if dependency is None else dependency,
        "generality": 0,
    }


def _source(name: str, protocol: str = "sqlite") -> dict[str, Any]:
    return {
        "name": name,
        "type": "source",
        "scope": f"/source/{name}",
        "properties": {"connection": {"protocol": protocol}, "owner": name},
    }


class RecordingClient:
    def __init__(self, result: Any = None, error: BaseException | None = None) -> None:
        self.result: Any = [] if result is None else result
        self.error = error
        self.calls: list[Any] = []

    def execute_api_call(
        self,
        input: Any,  # noqa: A002
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append(input)
        if self.error is not None:
            raise self.error
        return self.result


def _resolver(client: RecordingClient) -> Callable[[Any], RecordingClient]:
    def resolve(properties: Any) -> RecordingClient:
        del properties
        return client

    return resolve


# Run families


async def test_run_success_direct_and_wire_agree() -> None:
    result = await _call(create_server(), "select", {"input_data": VALID_INPUT, "attributes": GT5})
    direct = versioned_registry().resolve("select@2.0.0").run(VALID_INPUT, dict(GT5))
    assert result.isError is False
    assert result.structuredContent == run_payload(direct)
    assert json.loads(result.content[0].text) == result.structuredContent
    assert result.structuredContent["output_data"] == [[{"id": 1, "score": 8}]]
    assert result.structuredContent["exec_meta"]["is_empty"] is False


@pytest.mark.parametrize("input_data,attributes", EMPTY_CASES)
async def test_run_successful_empty_is_canonical(
    input_data: list[list[dict[str, Any]]],
    attributes: dict[str, Any],
) -> None:
    result = await _call(
        create_server(), "select", {"input_data": input_data, "attributes": attributes}
    )
    assert result.isError is False
    assert result.structuredContent["output_data"] == [[]]
    assert result.structuredContent["output_attributes"] == {}
    assert result.structuredContent["exec_meta"]["is_empty"] is True
    assert _errors(result) == []


async def test_run_recoverable_invalid_attributes() -> None:
    # `select` without its required operands passes the open MCP container but fails canonical
    # validation — a recoverable record, not a silent empty result, and no body call.
    result = await _call(create_server(), "select", {"input_data": [[{"score": 8}]]})
    assert result.isError is False
    error = _first_error(result)
    assert (error["category"], error["code"], error["stage"]) == (
        "RECOVERABLE",
        "INVALID_INPUT",
        "VALIDATE",
    )
    assert error["operator_id"] == "select@2.0.0"
    assert error["retryable"] is False
    assert isinstance(error["suggestion"], str) and error["suggestion"]


async def test_run_failed_is_contained_and_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    leak_marker = "opaque-provider-detail-xyz"
    client = RecordingClient(error=RuntimeError(leak_marker))
    monkeypatch.setattr(qb_module, "resolve_llm_client", _resolver(client))
    result = await _call(
        create_server(), "query_breakdown", {"input_data": [[]], "attributes": {"query": "q"}}
    )
    assert result.isError is False
    error = _first_error(result)
    assert (error["category"], error["code"], error["stage"]) == (
        "FAILED",
        "EXECUTION_FAILED",
        "EXECUTE",
    )
    assert error["operator_id"] == "query_breakdown@2.0.0"
    assert leak_marker not in json.dumps(result.structuredContent)
    assert leak_marker not in result.content[0].text
    assert len(client.calls) == 1  # one body call, no retry


class BlockingOperator(Operator):
    name: ClassVar[str] = "blocking"
    description: ClassVar[str] = "Block until released."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def __init__(self) -> None:
        self.release = threading.Event()

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        del input_data, attributes, properties
        self.release.wait(timeout=5)
        return [[{"done": True}]]


async def test_run_timeout_is_contained_and_worker_discarded() -> None:
    operator = BlockingOperator()
    try:
        result = await _call(
            _single_server(operator),
            "blocking",
            {"input_data": [[]], "properties": {"execution.timeout_seconds": 0.2}},
        )
        assert result.isError is False
        error = _first_error(result)
        assert (error["category"], error["code"], error["stage"]) == (
            "TIMEOUT",
            "OPERATOR_TIMEOUT",
            "EXECUTE",
        )
        assert result.structuredContent["output_data"] == [[]]
    finally:
        operator.release.set()


# Refinement families


async def test_refine_multipart_direct_and_wire_agree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_data = [[_cte("orders")]]
    # The direct oracle must be the registry-selected 2.0.0 operator so its child pins match the
    # wire (a selected v2 refinement emits @2.0.0 children; an unbound one keeps declared @1.0.0).
    selected = versioned_registry().resolve("multipart_query@2.0.0")
    monkeypatch.setattr(pipeline_module, "_new_id", _id_sequence())
    direct = cast(RefinableOperator, selected).refine(input_data, {})
    monkeypatch.setattr(pipeline_module, "_new_id", _id_sequence())
    result = await _call(
        create_server(), "multipart_query__refine", {"input_data": input_data, "attributes": {}}
    )
    assert result.isError is False
    assert result.structuredContent == refine_payload(direct)
    assert len(result.structuredContent["plans"]) == 1
    assert json.loads(result.content[0].text) == result.structuredContent


async def test_refine_router_serializes_plan() -> None:
    attributes = {
        "search_query": "find rows",
        "columns": [{"name": "value"}],
        "execute_query": False,
        "protocol": "sqlite",
    }
    result = await _call(
        create_server(),
        "nl2query_router__refine",
        {"input_data": [[_source("s")]], "attributes": attributes},
    )
    assert result.isError is False
    plans = result.structuredContent["plans"]
    assert len(plans) == 1
    assert "nodes" in plans[0] and "entities" in plans[0]


async def test_refine_query_breakdown_serializes_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RecordingClient([[_cte("answer")]])
    monkeypatch.setattr(qb_module, "resolve_llm_client", _resolver(client))
    result = await _call(
        create_server(),
        "query_breakdown__refine",
        {"input_data": [[]], "attributes": {"query": "q"}},
    )
    assert result.isError is False
    assert len(result.structuredContent["plans"]) == 1


def _plan_discover_server() -> FastMCP[Any]:
    children = OperatorRegistry()
    for operator, tags in ((ProjectOperator(), ("starter",)), (SelectOperator(), ("starter",))):
        children.register(operator, "1.0.0", tags=tags)
        children.register(operator, "2.0.0", tags=tags)
    registry = OperatorRegistry()
    registry.register(PlanDiscoverOperator(children), "2.0.0")
    return create_server(registry=registry, operator_ids=("plan_discover@2.0.0",))


async def test_refine_plan_discover_serializes_plans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline_module, "_new_id", _id_sequence())
    result = await _call(
        _plan_discover_server(),
        "plan_discover__refine",
        {
            "input_data": [[]],
            "attributes": {"task": "starter", "data": "rows", "approximate": True},
        },
    )
    assert result.isError is False
    plans = result.structuredContent["plans"]
    assert len(plans) == 2
    assert all("nodes" in plan for plan in plans)


async def test_refine_zero_plan_is_successful_empty() -> None:
    result = await _call(
        create_server(), "multipart_query__refine", {"input_data": [], "attributes": {}}
    )
    assert result.isError is False
    assert result.structuredContent["plans"] == []
    assert result.structuredContent["exec_meta"]["is_empty"] is True
    assert _errors(result) == []


async def test_refine_invalid_input_is_recoverable() -> None:
    result = await _call(
        create_server(),
        "multipart_query__refine",
        {"input_data": [[]], "attributes": {"plans": "bad"}},
    )
    assert result.isError is False
    error = _first_error(result)
    assert (error["category"], error["code"], error["stage"]) == (
        "RECOVERABLE",
        "INVALID_INPUT",
        "VALIDATE",
    )


async def test_refine_raising_refiner_is_contained(monkeypatch: pytest.MonkeyPatch) -> None:
    client = RecordingClient(error=RuntimeError("opaque-refiner-payload"))
    monkeypatch.setattr(qb_module, "resolve_llm_client", _resolver(client))
    result = await _call(
        create_server(),
        "query_breakdown__refine",
        {"input_data": [[]], "attributes": {"query": "q"}},
    )
    assert result.isError is False
    error = _first_error(result)
    assert (error["category"], error["code"], error["stage"]) == (
        "FAILED",
        "REFINEMENT_FAILED",
        "REFINE",
    )
    assert "opaque-refiner-payload" not in result.content[0].text


class MalformedRefiner(RefinableOperator):
    name: ClassVar[str] = "malformed_refiner"
    description: ClassVar[str] = "Return a non-record refinement result."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        del input_data, attributes, properties
        return [[]]

    def refiner(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[PlanRecord]:
        del input_data, attributes, properties
        return cast(list[PlanRecord], [123])


async def test_refine_malformed_result_is_normalize_error() -> None:
    result = await _call(
        _single_server(MalformedRefiner()),
        "malformed_refiner__refine",
        {"input_data": [[]], "attributes": {}},
    )
    assert result.isError is False
    error = _first_error(result)
    assert (error["category"], error["code"], error["stage"]) == (
        "FAILED",
        "REFINEMENT_RESULT_INVALID",
        "NORMALIZE",
    )


class BlockingRefiner(RefinableOperator):
    name: ClassVar[str] = "blocking_refiner"
    description: ClassVar[str] = "Block inside the refiner until released."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def __init__(self) -> None:
        self.release = threading.Event()

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        del input_data, attributes, properties
        return [[]]

    def refiner(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[PlanRecord]:
        del input_data, attributes, properties
        self.release.wait(timeout=5)
        return []


async def test_refine_timeout_is_contained() -> None:
    operator = BlockingRefiner()
    try:
        result = await _call(
            _single_server(operator),
            "blocking_refiner__refine",
            {"input_data": [[]], "properties": {"execution.timeout_seconds": 0.2}},
        )
        assert result.isError is False
        error = _first_error(result)
        assert (error["category"], error["code"], error["stage"]) == (
            "TIMEOUT",
            "OPERATOR_TIMEOUT",
            "REFINE",
        )
    finally:
        operator.release.set()


# Dispatch boundary


class RunOnlySpy(Operator):
    name: ClassVar[str] = "run_only_spy"
    description: ClassVar[str] = "A primary that dispatches only through run()."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def __init__(self) -> None:
        self.run_calls = 0

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        raise AssertionError("apply must not be called by the adapter")

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("invoke must not be called by the adapter")

    def validate(self, *args: Any, **kwargs: Any) -> bool:
        raise AssertionError("validate must not be called by the adapter")

    def run(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> tuple[list[list[dict[str, Any]]], dict[str, Any], ExecMeta]:
        del input_data, attributes, properties
        self.run_calls += 1
        return [[{"ok": True}]], {}, ExecMeta(is_empty=False, errors=[], logs=[], traces={})


class RefineOnlySpy(RefinableOperator):
    name: ClassVar[str] = "refine_only_spy"
    description: ClassVar[str] = "A companion that dispatches only through refine()."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def __init__(self) -> None:
        self.refine_calls = 0

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        return [[]]

    def refiner(self, *args: Any, **kwargs: Any) -> list[PlanRecord]:
        raise AssertionError("raw refiner must not be called by the adapter")

    def refine(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> tuple[list[Any], ExecMeta]:
        del input_data, attributes, properties
        self.refine_calls += 1
        return [], ExecMeta(is_empty=True, errors=[], logs=[], traces={})


async def test_primary_dispatches_only_to_run_once() -> None:
    operator = RunOnlySpy()
    result = await _call(_single_server(operator), "run_only_spy", {"input_data": [[]]})
    assert result.isError is False
    assert operator.run_calls == 1
    assert result.structuredContent["output_data"] == [[{"ok": True}]]


async def test_companion_dispatches_only_to_refine_once() -> None:
    operator = RefineOnlySpy()
    result = await _call(_single_server(operator), "refine_only_spy__refine", {"input_data": [[]]})
    assert result.isError is False
    assert operator.refine_calls == 1
    assert result.structuredContent["plans"] == []


# Argument errors


class NoCallOperator(Operator):
    name: ClassVar[str] = "no_call"
    description: ClassVar[str] = "Fail loudly if any canonical call begins."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def apply(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("apply must not begin")

    def run(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("run must not begin")


@pytest.mark.parametrize("arguments", BAD_ARGUMENTS)
async def test_argument_shape_errors_are_tool_errors(arguments: dict[str, Any]) -> None:
    result = await _call(_single_server(NoCallOperator()), "no_call", arguments)
    assert result.isError is True


# Encoding errors


class EncodingOperator(Operator):
    name: ClassVar[str] = "encoding"
    description: ClassVar[str] = "Return a chosen leaf in the canonical output."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    leaf: ClassVar[Any] = None

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        del input_data, attributes, properties
        return [[{"v": type(self).leaf}]]


class _StrLeaf:
    def __str__(self) -> str:
        return "python-only-leaf"


@pytest.mark.parametrize("leaf", [float("nan"), float("inf"), float("-inf")])
async def test_non_finite_floats_are_tool_errors(leaf: float) -> None:
    EncodingOperator.leaf = leaf
    result = await _call(_single_server(EncodingOperator()), "encoding", {"input_data": [[]]})
    assert result.isError is True
    assert result.structuredContent is None  # a tool error, not a synthetic operator record


async def test_python_only_leaf_follows_default_str() -> None:
    EncodingOperator.leaf = _StrLeaf()
    result = await _call(_single_server(EncodingOperator()), "encoding", {"input_data": [[]]})
    assert result.isError is False
    assert result.structuredContent["output_data"] == [[{"v": "python-only-leaf"}]]
    assert _errors(result) == []

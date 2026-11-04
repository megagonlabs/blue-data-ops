from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, ClassVar, cast

import blue_data_ops.operators.data_discover_operator as discover_module
import litellm
import pytest
from blue_data_ops.operators import AttributeSpec, ExecMeta, Operator, OperatorRegistry
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from blue_data_ops_mcp.registration import run_payload
from blue_data_ops_mcp.server import create_server

VALID_INPUT: list[list[dict[str, Any]]] = [[{"id": 1, "score": 8}, {"id": 2, "score": 2}]]
GT5: dict[str, Any] = {"operand_key": "score", "operand": ">", "operand_val": 5}
EMPTY_CASES: list[tuple[list[list[dict[str, Any]]], dict[str, Any]]] = [
    ([[{"score": 8}]], {"operand_key": "score", "operand": ">", "operand_val": 99}),
    ([[]], GT5),
    ([[], []], GT5),
]
BAD_ARGUMENTS: list[dict[str, Any]] = [
    {},
    {"input_data": [{"not": "a group"}]},
    {"input_data": [[]], "properties": []},
]
README = Path(__file__).resolve().parents[1] / "README.md"
LLM_CALL_FENCE = re.compile(
    r"<!-- blue-data-ops-mcp-test: llm-(?P<name>[\w-]+)-call -->\n"
    r"```json\n(?P<payload>.*?)\n```",
    re.DOTALL,
)


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


async def test_success_direct_and_in_memory_protocol_agree() -> None:
    from blue_data_ops.operators import versioned_registry

    registry = versioned_registry()
    operator = registry.resolve("select@2.0.0")
    direct = run_payload(operator.run(VALID_INPUT, dict(GT5)))
    result = await _call(
        create_server(registry=registry, operator_ids=("select@2.0.0",)),
        "ops_select",
        {"input_data": VALID_INPUT, "attributes": GT5},
    )
    assert result.isError is False
    assert result.structuredContent == direct
    assert json.loads(result.content[0].text) == direct
    assert direct["output_data"] == [[{"id": 1, "score": 8}]]
    assert direct["exec_meta"]["is_empty"] is False


async def test_data_discover_tool_returns_only_catalog_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from blue_data_ops.operators import versioned_registry

    class LocalSearch:
        def search_records_hierarchical(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
            return [{"name": "jobs_db", "id": "/source/jobs_db", "scope": "/"}]

        def get_record(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {
                "description": "hidden-marker",
                "properties": {"kind": "sql", "connection": {"password": "hidden-marker"}},
                "metadata": {"note": "hidden-marker"},
            }

    def local_registry(_root: object) -> LocalSearch:
        return LocalSearch()

    monkeypatch.setattr(discover_module, "resolve_registry", local_registry)
    from blue_data.registry.data_registry import DataRegistry  # pyright: ignore[reportMissingTypeStubs]

    server = create_server(
        registry=versioned_registry(),
        data_registry=DataRegistry(),
        operator_ids=("data_discover@2.0.0",),
    )
    result = await _call(
        server,
        "ops_data_discover",
        {"input_data": [[]], "attributes": {"search_query": "jobs", "approximate": False}},
    )
    assert result.isError is False
    assert _errors(result) == []
    assert result.structuredContent["output_data"] == [
        [
            {
                "type": "source",
                "name": "jobs_db",
                "id": "/source/jobs_db",
                "scope": "/",
                "properties": {"kind": "sql"},
            }
        ]
    ]
    assert "hidden-marker" not in result.content[0].text


async def test_documented_llm_calls_execute_through_the_published_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OfflineResponse:
        def __init__(self, content: str) -> None:
            self.content = content

        def model_dump(self) -> dict[str, Any]:
            return {
                "choices": [{"message": {"role": "assistant", "content": self.content}}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                "model": "offline-model",
            }

    def offline_completion(**kwargs: Any) -> OfflineResponse:
        raw_messages: object = kwargs.get("messages")
        messages = (
            cast("list[dict[str, Any]]", raw_messages) if isinstance(raw_messages, list) else []
        )
        prompt = str(messages[0].get("content", "")) if messages else ""
        return OfflineResponse("true" if "only a boolean value" in prompt else "[]")

    def offline_cost(**kwargs: Any) -> float:
        del kwargs
        return 0.0

    monkeypatch.setattr(litellm, "completion", offline_completion)
    monkeypatch.setattr(litellm, "completion_cost", offline_cost)
    examples = {
        match.group("name"): cast(dict[str, Any], json.loads(match.group("payload")))
        for match in LLM_CALL_FENCE.finditer(README.read_text(encoding="utf-8"))
    }
    assert set(examples) == {"nl2llm", "semantic-filter"}
    server = create_server()
    for example_name, tool_name in (
        ("nl2llm", "ops_nl2llm"),
        ("semantic-filter", "ops_semantic_filter"),
    ):
        result = await _call(server, tool_name, examples[example_name])
        assert result.isError is False
        assert _errors(result) == []


@pytest.mark.parametrize(
    "input_data,attributes",
    EMPTY_CASES,
)
async def test_successful_empty_direct_and_protocol_agree(
    input_data: list[list[dict[str, Any]]],
    attributes: dict[str, Any],
) -> None:
    from blue_data_ops.operators import versioned_registry

    registry = versioned_registry()
    direct = run_payload(registry.resolve("select@2.0.0").run(input_data, dict(attributes)))
    result = await _call(
        create_server(registry=registry, operator_ids=("select@2.0.0",)),
        "ops_select",
        {"input_data": input_data, "attributes": attributes},
    )
    assert result.isError is False
    assert result.structuredContent == direct
    assert direct["output_data"] == [[]]
    assert direct["output_attributes"] == {}
    assert direct["exec_meta"]["is_empty"] is True
    assert direct["exec_meta"]["errors"] == []


async def test_validation_failure_direct_and_protocol_agree() -> None:
    from blue_data_ops.operators import versioned_registry

    registry = versioned_registry()
    operator = registry.resolve("select@2.0.0")
    direct = run_payload(operator.run([[{"score": 8}]], {}))
    result = await _call(
        create_server(registry=registry, operator_ids=("select@2.0.0",)),
        "ops_select",
        {"input_data": [[{"score": 8}]]},
    )
    assert result.isError is False
    assert result.structuredContent == direct
    error = _first_error(result)
    assert (error["category"], error["code"], error["stage"]) == (
        "RECOVERABLE",
        "INVALID_INPUT",
        "VALIDATE",
    )
    assert error["operator_id"] == "select@2.0.0"


async def test_published_required_does_not_become_a_second_enforcement_point() -> None:
    """A required attribute the caller omits is still an operator outcome, not a protocol error.

    The published `attributes` schema is advisory: the handler validates against an open
    object, so the tightening in 1.0.0 changes what the tool advertises and not what the
    server does with a call that ignores it.
    """
    from blue_data_ops.operators import versioned_registry

    server = create_server(registry=versioned_registry(), operator_ids=("argmax@2.0.0",))
    [tool] = await server.list_tools()
    assert tool.inputSchema["properties"]["attributes"]["required"] == ["argmax_key"]

    result = await _call(server, "ops_argmax", {"input_data": [[{"a": 1}]]})
    assert result.isError is False
    error = _first_error(result)
    assert (error["code"], error["stage"]) == ("INVALID_INPUT", "VALIDATE")
    assert error["suggestion"] == "supply a non-empty argmax_key"


class RaisingOperator(Operator):
    name: ClassVar[str] = "raising"
    description: ClassVar[str] = "Raise an opaque execution failure."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        del input_data, attributes, properties
        raise RuntimeError("opaque-provider-detail-xyz")


async def test_execution_failure_direct_and_protocol_agree_and_are_redacted() -> None:
    registry = OperatorRegistry()
    registry.register(RaisingOperator(), "2.0.0")
    operator = registry.resolve("raising@2.0.0")
    direct = run_payload(operator.run([[]], {}))
    result = await _call(
        create_server(registry=registry, operator_ids=("raising@2.0.0",)),
        "ops_raising",
        {"input_data": [[]]},
    )
    assert result.isError is False
    assert result.structuredContent == direct
    error = _first_error(result)
    assert (error["category"], error["code"], error["stage"]) == (
        "FAILED",
        "EXECUTION_FAILED",
        "EXECUTE",
    )
    assert error["operator_id"] == "raising@2.0.0"
    assert "opaque-provider-detail-xyz" not in json.dumps(result.structuredContent)
    assert "opaque-provider-detail-xyz" not in result.content[0].text


async def test_default_mixed_selection_dispatches_v3_implementation() -> None:
    result = await _call(
        create_server(),
        "ops_avg",
        {"input_data": [[{"value": 2}, {"value": 4}]], "attributes": {"avg_key": "value"}},
    )
    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent["exec_meta"]["errors"] == []
    [tool] = [tool for tool in await create_server().list_tools() if tool.name == "ops_avg"]
    assert (tool.meta or {})["operator_id"] == "avg@3.0.0"


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


async def test_timeout_is_contained_and_worker_discarded() -> None:
    operator = BlockingOperator()
    try:
        result = await _call(
            _single_server(operator),
            "ops_blocking",
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


class RunOnlySpy(Operator):
    name: ClassVar[str] = "run_only_spy"
    description: ClassVar[str] = "Dispatch only through run()."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def __init__(self) -> None:
        self.run_calls = 0

    def apply(self, *args: Any, **kwargs: Any) -> Any:
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


async def test_primary_dispatches_only_to_run_once() -> None:
    operator = RunOnlySpy()
    result = await _call(_single_server(operator), "ops_run_only_spy", {"input_data": [[]]})
    assert result.isError is False
    assert operator.run_calls == 1
    assert result.structuredContent["output_data"] == [[{"ok": True}]]


class PropertySpy(Operator):
    name: ClassVar[str] = "property_spy"
    description: ClassVar[str] = "Record the properties passed by the adapter."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def __init__(self) -> None:
        self.seen: dict[str, Any] | None = None
        super().__init__()

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        del attributes
        self.seen = dict(properties or {})
        return input_data


async def test_model_and_reasoning_effort_properties_reach_the_operator() -> None:
    operator = PropertySpy()
    result = await _call(
        _single_server(operator),
        "ops_property_spy",
        {
            "input_data": [[]],
            "properties": {"llm.model": "gpt-5-mini", "llm.reasoning_effort": "high"},
        },
    )

    assert result.isError is False
    assert operator.seen == {"llm.model": "gpt-5-mini", "llm.reasoning_effort": "high"}


class NoCallOperator(Operator):
    name: ClassVar[str] = "no_call"
    description: ClassVar[str] = "Fail if any canonical call begins."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def apply(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("apply must not begin")

    def run(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("run must not begin")


@pytest.mark.parametrize("arguments", BAD_ARGUMENTS)
async def test_argument_shape_errors_are_tool_errors(arguments: dict[str, Any]) -> None:
    result = await _call(_single_server(NoCallOperator()), "ops_no_call", arguments)
    assert result.isError is True


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
    result = await _call(_single_server(EncodingOperator()), "ops_encoding", {"input_data": [[]]})
    assert result.isError is True
    assert result.structuredContent is None


async def test_python_only_leaf_follows_default_str() -> None:
    EncodingOperator.leaf = _StrLeaf()
    result = await _call(_single_server(EncodingOperator()), "ops_encoding", {"input_data": [[]]})
    assert result.isError is False
    assert result.structuredContent["output_data"] == [[{"v": "python-only-leaf"}]]
    assert _errors(result) == []

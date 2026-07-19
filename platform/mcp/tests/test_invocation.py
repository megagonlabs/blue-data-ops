from __future__ import annotations

import json
from typing import Any

import pytest
from blue_data_ops.operators import (
    DataDiscoverOperator,
    MultipartQueryOperator,
    NL2QueryRouterOperator,
    NormalizeTextOperator,
    Operator,
    PlanDiscoverOperator,
    QueryBreakdownOperator,
    SelectOperator,
    SemanticFilterOperator,
    VectorEmbedOperator,
)
from blue_data_ops.operators import data_discover_operator as data_discover_module
from blue_data_ops.operators import query_breakdown_operator as query_breakdown_module
from blue_data_ops.operators import semantic_filter_operator as semantic_filter_module
from conftest import EncodeCall, SentenceTransformer
from mcp.shared.memory import create_connected_server_and_client_session

from blue_data_ops_mcp.server import create_server

SELECT_CASES: list[tuple[dict[str, Any], list[list[dict[str, Any]]]]] = [
    ({"operand_key": "score", "operand": ">", "operand_val": 5}, [[{"id": 1, "score": 8}]]),
    ({"operand_key": "score", "operand": "contains", "operand_val": 5}, [[]]),
    ({"operand_key": "score", "operand": ">", "operand_val": 99}, [[]]),
]


def _text(result: Any) -> str:
    assert result.isError is False
    assert result.structuredContent is None
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    return str(result.content[0].text)


async def _call(name: str, arguments: dict[str, Any]) -> Any:
    server = create_server(operator_ids=(f"{name}@1.0.0",))
    async with create_connected_server_and_client_session(server) as client:
        return await client.call_tool(name, arguments)


@pytest.mark.parametrize(
    "attributes,expected",
    SELECT_CASES,
)
async def test_select_direct_and_mcp_w1_w2_w3(
    attributes: dict[str, Any],
    expected: list[list[dict[str, Any]]],
) -> None:
    input_data = [[{"id": 1, "score": 8}, {"id": 2, "score": 2}]]
    direct = SelectOperator().apply(input_data, dict(attributes))
    result = await _call("select", {"input_data": input_data, "attributes": attributes})
    assert direct == expected
    assert json.loads(_text(result)) == direct


async def test_normalize_text_preserves_two_groups_and_nested_values_w4() -> None:
    input_data: list[list[dict[str, Any]]] = [
        [{"id": 1, "text": "  Héllo  ", "meta": {"tags": ["x", "y"]}}],
        [{"id": 2, "text": "World", "meta": {"tags": []}}],
    ]
    attributes = {"text_field": ["text"]}
    expected: list[list[dict[str, Any]]] = [
        [
            {
                "id": 1,
                "text": "  Héllo  ",
                "meta": {"tags": ["x", "y"]},
                "text_norm": "Héllo",
            }
        ],
        [{"id": 2, "text": "World", "meta": {"tags": []}, "text_norm": "World"}],
    ]
    direct = NormalizeTextOperator().apply(input_data, attributes)
    result = await _call(
        "normalize_text",
        {"input_data": input_data, "attributes": attributes},
    )
    assert direct == expected
    assert json.loads(_text(result)) == direct


class RegistrySeamDouble:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def search_records_hierarchical(
        self,
        input_query: Any,
        type: str | None = None,
        scope: str | None = None,
        page: int = 0,
        page_size: int = 5,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            (
                "search_records_hierarchical",
                {
                    "input_query": input_query,
                    "type": type,
                    "scope": scope,
                    "page": page,
                    "page_size": page_size,
                },
            )
        )
        return [
            {
                "name": "jobs_db",
                "type": "source",
                "scope": "/",
                "id": "//source/jobs_db",
                "score": 0.1,
            },
            {
                "name": "jobs_far",
                "type": "source",
                "scope": "/",
                "id": "//source/jobs_far",
                "score": 0.9,
            },
        ]

    def get_record(self, name: str, type: str, scope: str) -> dict[str, Any] | None:
        self.calls.append(("get_record", {"name": name, "type": type, "scope": scope}))
        if name == "jobs_db":
            return {
                "name": name,
                "description": "job postings",
                "properties": {"kind": "sql"},
            }
        return None


async def test_data_discover_injected_seam_w7(monkeypatch: pytest.MonkeyPatch) -> None:
    seam = RegistrySeamDouble()

    def resolve_registry(properties: dict[str, Any] | None) -> RegistrySeamDouble:
        del properties
        return seam

    monkeypatch.setattr(data_discover_module, "resolve_registry", resolve_registry)
    attributes = {"search_query": "jobs", "approximate": True, "threshold": 0.5}
    expected = [
        [
            {
                "type": "source",
                "name": "jobs_db",
                "id": "//source/jobs_db",
                "scope": "/",
                "score": 0.1,
                "description": "job postings",
                "properties": {"kind": "sql"},
            }
        ]
    ]
    direct = DataDiscoverOperator().apply([[]], attributes)
    direct_calls = list(seam.calls)
    seam.calls.clear()
    result = await _call(
        "data_discover",
        {"input_data": [[]], "attributes": attributes},
    )
    assert direct == expected
    assert json.loads(_text(result)) == direct
    assert seam.calls == direct_calls
    assert direct_calls == [
        (
            "search_records_hierarchical",
            {
                "input_query": "jobs",
                "type": "source",
                "scope": None,
                "page": 0,
                "page_size": 10,
            },
        ),
        ("get_record", {"name": "jobs_db", "type": "source", "scope": "/"}),
        ("get_record", {"name": "jobs_far", "type": "source", "scope": "/"}),
    ]


class QueueClient:
    def __init__(self, values: list[Any]) -> None:
        self.values = iter(values)
        self.calls: list[dict[str, Any]] = []

    def execute_api_call(
        self,
        input: Any,
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append(
            {"input": input, "properties": properties, "additional_data": additional_data}
        )
        return next(self.values)


async def test_semantic_filter_injected_queue_client_w8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_data = [[{"id": 1, "score": 8}, {"id": 2, "score": 2}]]
    attributes = {"filter_conditions": {"score": "high"}}

    direct_client = QueueClient(["true", "false"])

    def resolve_direct(properties: dict[str, Any]) -> QueueClient:
        del properties
        return direct_client

    monkeypatch.setattr(semantic_filter_module, "resolve_llm_client", resolve_direct)
    direct = SemanticFilterOperator().apply(input_data, attributes)

    wire_client = QueueClient(["true", "false"])

    def resolve_wire(properties: dict[str, Any]) -> QueueClient:
        del properties
        return wire_client

    monkeypatch.setattr(semantic_filter_module, "resolve_llm_client", resolve_wire)
    result = await _call(
        "semantic_filter",
        {"input_data": input_data, "attributes": attributes},
    )
    assert direct == [[input_data[0][0]]]
    assert json.loads(_text(result)) == direct
    assert len(direct_client.calls) == 2
    assert len(wire_client.calls) == 2


async def test_vector_embed_exact_stub_boundary_w9() -> None:
    SentenceTransformer.reset()
    input_data = [[{"id": "d1", "title": "alpha"}, {"id": "d2", "title": "beta"}]]
    attributes = {"text_field": ["title"]}
    properties = {"batch_size": 2}
    expected = [
        [
            {
                "id": "d1",
                "embedding": [
                    0.5568627450980392,
                    0.8274509803921568,
                    0.9647058823529412,
                    0.6784313725490196,
                ],
            },
            {
                "id": "d2",
                "embedding": [
                    0.9568627450980393,
                    0.3058823529411765,
                    0.39215686274509803,
                    0.9058823529411765,
                ],
            },
        ]
    ]
    direct = VectorEmbedOperator().apply(input_data, attributes, properties)
    direct_calls = list(SentenceTransformer.encode_calls)
    SentenceTransformer.reset()
    result = await _call(
        "vector_embed",
        {"input_data": input_data, "attributes": attributes, "properties": properties},
    )
    assert direct == expected
    assert json.loads(_text(result)) == direct
    assert direct_calls == [EncodeCall("all-MiniLM-L6-v2", ("alpha", "beta"), 2, False)]
    assert SentenceTransformer.encode_calls == direct_calls


class BreakdownClient:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error

    def execute_api_call(
        self,
        input: Any,
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        del input, properties, additional_data
        if self.error is not None:
            raise self.error
        return self.result


@pytest.mark.parametrize("attributes", [{}, {"query": ""}, {"query": "   "}])
async def test_query_breakdown_blank_guards_w10a(attributes: dict[str, Any]) -> None:
    direct = QueryBreakdownOperator().apply([[]], attributes)
    result = await _call(
        "query_breakdown",
        {"input_data": [[]], "attributes": attributes},
    )
    assert direct == []
    assert json.loads(_text(result)) == direct


async def test_query_breakdown_provider_success_and_error_w10a(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = [[{"table": "answer"}]]

    def resolve_success(properties: dict[str, Any]) -> BreakdownClient:
        del properties
        return BreakdownClient(expected)

    monkeypatch.setattr(
        query_breakdown_module,
        "resolve_llm_client",
        resolve_success,
    )
    direct = QueryBreakdownOperator().apply([[]], {"query": "q"})
    result = await _call(
        "query_breakdown",
        {"input_data": [[]], "attributes": {"query": "q"}},
    )
    assert direct is expected
    assert json.loads(_text(result)) == direct

    def resolve_error(properties: dict[str, Any]) -> BreakdownClient:
        del properties
        return BreakdownClient(error=LookupError("provider down"))

    monkeypatch.setattr(
        query_breakdown_module,
        "resolve_llm_client",
        resolve_error,
    )
    error = await _call(
        "query_breakdown",
        {"input_data": [[]], "attributes": {"query": "q"}},
    )
    assert error.isError is True
    assert "Error executing tool query_breakdown: provider down" in str(error.content[0].text)


PLAN_CASES: list[tuple[str, Operator, dict[str, Any], dict[str, Any] | None]] = [
    (
        "plan_discover",
        PlanDiscoverOperator(),
        {"task": "find", "data": [[]], "approximate": True},
        None,
    ),
    (
        "plan_discover",
        PlanDiscoverOperator(),
        {
            "task": "find",
            "data": [[]],
            "approximate": True,
            "search_query": "q",
        },
        None,
    ),
    ("plan_discover", PlanDiscoverOperator(), {}, None),
    ("multipart_query", MultipartQueryOperator(), {}, {}),
    ("nl2query_router", NL2QueryRouterOperator(), {}, {}),
]


@pytest.mark.parametrize(
    "name,operator,attributes,properties",
    PLAN_CASES,
)
async def test_raw_plan_tools_return_placeholder_w10b_w10c_w10d(
    name: str,
    operator: Operator,
    attributes: dict[str, Any],
    properties: dict[str, Any] | None,
) -> None:
    direct = operator.apply([[]], attributes, properties)
    arguments: dict[str, Any] = {"input_data": [[]], "attributes": attributes}
    if properties is not None:
        arguments["properties"] = properties
    result = await _call(name, arguments)
    assert direct == [[]]
    assert json.loads(_text(result)) == direct

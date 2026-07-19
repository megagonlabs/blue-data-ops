from __future__ import annotations

import hashlib
from string import Template
from typing import Any

import litellm
import pytest
from jinja2 import BaseLoader, Environment

from blue_data_ops.operators import QueryBreakdownOperator, default_registry
from blue_data_ops.operators import query_breakdown_operator as query_module
from blue_data_ops.operators.query_breakdown_operator import (
    _PROMPT,  # pyright: ignore[reportPrivateUsage]
)
from tests.unit.operators._plan_operator_helpers import (
    assert_registry_resolves,
    assert_roundtrip,
    cte,
    edges,
    operator_ids,
    operator_records,
)

INPUT: list[list[dict[str, Any]]] = [[]]


class _RecordingClient:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.result: Any = [] if result is None else result
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def execute_api_call(
        self,
        input: Any,  # noqa: A002
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append(
            {
                "input": input,
                "properties": properties,
                "additional_data": additional_data,
            }
        )
        if self.error is not None:
            raise self.error
        return self.result


def _inject(monkeypatch: pytest.MonkeyPatch, client: _RecordingClient) -> list[dict[str, Any]]:
    resolutions: list[dict[str, Any]] = []

    def resolve(properties: dict[str, Any]) -> Any:
        resolutions.append(properties)
        return client

    monkeypatch.setattr(query_module, "resolve_llm_client", resolve)
    return resolutions


def test_prompt_bytes_and_default_properties() -> None:
    assert len(_PROMPT) == 3912
    assert hashlib.sha256(_PROMPT.encode()).hexdigest() == (
        "75243f3df16b4d7373262ba6ba6002bc0ef1eef443d72401d392281dc3102db7"
    )
    assert QueryBreakdownOperator.DEFAULT_PROPERTIES == {
        "openai.api": "ChatCompletion",
        "openai.model": "gpt-4o",
        "openai.stream": False,
        "openai.max_tokens": 4096,
        "openai.temperature": 0,
        "input_json": '[{"role": "user"}]',
        "input_context": "$[0]",
        "input_context_field": "content",
        "input_field": "messages",
        "input_template": _PROMPT,
        "output_path": "$.choices[0].message.content",
        "service_prefix": "openai",
        "output_transformations": [
            {"transformation": "replace", "from": "```", "to": ""},
            {"transformation": "replace", "from": "json", "to": ""},
        ],
        "output_strip": True,
        "output_cast": "json",
    }
    assert len(QueryBreakdownOperator.DEFAULT_PROPERTIES) == 15


def test_interface_explainer_and_validator() -> None:
    op = QueryBreakdownOperator()
    assert op.name == "query_breakdown"
    assert op.description == (
        "Processes natural language query and break it down to subqueries using common table "
        "expressions"
    )
    assert op.PROPERTIES == {"refine": True}
    assert [spec.default for spec in op.attributes.values()] == [None, "", [], 1]
    assert op.explain([[{"x": 1}]], INPUT, {"query": "q"}) == {
        "output": [[{"x": 1}]],
        "attributes": {"query": "q"},
    }
    cases: list[tuple[dict[str, Any], bool]] = [
        ({"query": "q"}, True),
        ({}, False),
        ({"query": ""}, True),
        ({"query": b"q"}, True),
        ({"query": "q", "schema": []}, False),
        ({"query": "q", "num_alternatives": "2"}, True),
        ({"query": "q", "num_alternatives": None}, False),
        ({"query": "q", "serialize": False}, True),
    ]
    for attributes, expected in cases:
        assert op.validate(INPUT, attributes) is expected


@pytest.mark.parametrize("query", [None, "", "   "])
def test_blank_guard_avoids_provider_resolution(
    monkeypatch: pytest.MonkeyPatch,
    query: Any,
) -> None:
    client = _RecordingClient()
    resolutions = _inject(monkeypatch, client)
    attributes = {} if query is None else {"query": query}
    op = QueryBreakdownOperator()
    assert op.apply(INPUT, attributes) == []
    assert op.refiner(INPUT, attributes) == []
    assert resolutions == []
    assert client.calls == []


def test_function_provider_call_defaults_overrides_and_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = [[{"table": "answer"}]]
    client = _RecordingClient(result)
    resolutions = _inject(monkeypatch, client)
    attributes = {"query": "q"}
    properties = {"openai.model": "gpt-4o-mini", "caller": True}

    output = QueryBreakdownOperator().apply(INPUT, attributes, properties)

    assert output is result
    [resolved] = resolutions
    assert resolved["openai.model"] == "gpt-4o-mini"
    assert resolved["openai.temperature"] == 0
    [call] = client.calls
    assert call["input"] == {}
    assert call["properties"] is resolved
    assert call["additional_data"] == {
        "query": "q",
        "context": "",
        "num_alternatives": 1,
        "schema": "",
    }


def test_provider_exception_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    _inject(monkeypatch, _RecordingClient(error=RuntimeError("provider down")))
    with pytest.raises(RuntimeError, match="provider down"):
        QueryBreakdownOperator().apply(INPUT, {"query": "q"})
    with pytest.raises(RuntimeError, match="provider down"):
        QueryBreakdownOperator().refiner(INPUT, {"query": "q"})


def test_refiner_zero_one_many_and_properties(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingClient([])
    _inject(monkeypatch, client)
    op = QueryBreakdownOperator()
    assert op.refiner(INPUT, {"query": "q"}) == []

    properties = {"caller": {"kept": True}}
    client.result = [[cte("one")], [cte("two")]]
    plans = op.refiner(INPUT, {"query": "q"}, properties)
    assert len(plans) == 2
    assert [operator_records(plan)[2][1]["table"] for plan in plans] == ["one", "two"]
    for plan in plans:
        assert plan["properties"] == properties
        assert_registry_resolves(plan, default_registry())
        assert_roundtrip(plan)


def test_refiner_none_and_graph_errors_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingClient()
    _inject(monkeypatch, client)
    client.result = None
    with pytest.raises(TypeError):
        QueryBreakdownOperator().refiner(INPUT, {"query": "q"})

    client.result = [[cte("x", generality="high")]]
    with pytest.raises(TypeError):
        QueryBreakdownOperator().refiner(INPUT, {"query": "q"})


def test_refiner_missing_fields_drop_only_that_alternative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = cte("bad")
    del invalid["description"]
    client = _RecordingClient([[invalid], [cte("good")]])
    _inject(monkeypatch, client)
    plans = QueryBreakdownOperator().refiner(INPUT, {"query": "q"})
    assert len(plans) == 1
    assert operator_records(plans[0])[2][1]["table"] == "good"


def test_undeclared_serialize_selects_branch_topology(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingClient([[cte("a"), cte("b")]])
    _inject(monkeypatch, client)
    plan = QueryBreakdownOperator().refiner(INPUT, {"query": "q", "serialize": False})[0]
    records = operator_records(plan)
    root_id = records[0][2]["id"]
    starts = {records[1][2]["id"], records[5][2]["id"]}
    assert {(root_id, start) for start in starts} <= edges(plan)


def test_real_adapter_renders_exact_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    litellm.calls.clear()

    def fake(**kwargs: Any) -> Any:
        litellm.calls.append(kwargs)

        class _Response:
            def model_dump(self) -> dict[str, Any]:
                return {"choices": [{"message": {"content": "[]"}}]}

        return _Response()

    monkeypatch.setattr(litellm, "completion", fake)
    output = QueryBreakdownOperator().apply(
        INPUT,
        {
            "query": "top jobs",
            "context": "workforce",
            "schema": "jobs(title)",
            "num_alternatives": 2,
        },
    )
    assert output == []
    content = litellm.calls[-1]["messages"][0]["content"]
    expected = (
        Environment(loader=BaseLoader())
        .from_string(
            Template(_PROMPT).safe_substitute(
                query="top jobs",
                context="workforce",
                schema="jobs(title)",
                num_alternatives=2,
            )
        )
        .render()
    )
    assert content == expected
    call = litellm.calls[-1]
    assert call["model"] == "gpt-4o"
    assert call["max_tokens"] == 4096
    assert call["temperature"] == 0
    assert "service_url" not in call and "api" not in call


def test_every_graph_reference_is_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    result = [[cte("base"), cte("child", dependency=["base"])]]
    client = _RecordingClient(result)
    _inject(monkeypatch, client)
    [plan] = QueryBreakdownOperator().refiner(INPUT, {"query": "q"})
    assert operator_ids(plan) == [
        "create_database@1.0.0",
        "data_discover@1.0.0",
        "create_table@1.0.0",
        "nl2query_router@1.0.0",
        "insert_table@1.0.0",
        "create_table@1.0.0",
        "nl2sql@1.0.0",
        "insert_table@1.0.0",
    ]
    assert all("@1.0.0" in operator_id for operator_id in operator_ids(plan))
    assert "/server/" not in repr(plan)

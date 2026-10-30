"""Exercise temperature fallback at each registered operator call boundary."""

from __future__ import annotations

import json
from typing import Any

import litellm
import pytest

from blue_data_ops.data import RegistrySeam
from blue_data_ops.llm import LLMClient
from blue_data_ops.operators.registry import active_registry, default_registry, versioned_registry
from tests.doubles.data import RegistrySeamDouble
from tests.unit.llm.test_temperature_fallback import invoke, prepared, price, rejection


class Seam(RegistrySeamDouble, RegistrySeam):
    pass


FAMILIES = [
    "nl2llm",
    "nl2sql",
    "nl2bn",
    "semantic_extract",
    "semantic_filter",
    "semantic_join",
    "semantic_project",
    "semantic_transform",
]


@pytest.mark.parametrize("kind", ["local", "structured"])
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("version", ["default", "2.0.0", "active"])
def test_operator_call_boundaries(
    monkeypatch: pytest.MonkeyPatch, family: str, version: str, kind: str
) -> None:
    litellm.calls.clear()
    litellm.fail_next.clear()
    monkeypatch.delenv("BLUE_DATA_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("BLUE_DATA_LLM_ALLOWED_MODELS", raising=False)
    operator: Any = (
        default_registry().resolve(f"{family}@1.0.0")
        if version == "default"
        else active_registry().resolve(f"{family}@3.0.0")
        if version == "active"
        else versioned_registry().resolve(f"{family}@{version}")
    )
    seam = Seam()
    seam.schema_result = {"entities": [{"name": "jobs"}], "relations": []}
    seam.query_result = [{"probability": 0.42, "role": "manager"}]
    props: dict[str, Any] = {
        "llm.model": "gpt-6.1-sol",
        "llm.reasoning_effort": "low",
        "data_registry": seam,
    }
    data: list[list[dict[str, Any]]] = [[{"name": "Ada", "score": 1}]]
    attrs: dict[str, Any]
    replies: list[Any]
    if family == "nl2llm":
        attrs, replies = {"query": "Return a name"}, [[{"name": "Ada"}]]
    elif family == "nl2sql":
        attrs = {
            "question": "Return jobs",
            "source": "pg",
            "protocol": "postgres",
            "database": "postgres",
            "collection": "public",
        }
        replies = [{"query": "SELECT role FROM jobs", "question": "Return jobs"}]
    elif family == "nl2bn":
        attrs = {
            "question": "Probability?",
            "source": "bn",
            "collection": "graph",
            "schema": "Node status has states yes and no",
            "max_corrections": 1,
        }
        replies = [{}, {"target_node": "status", "target_state": "yes", "context": {}}]
    elif family == "semantic_extract":
        attrs = {
            "entities": [{"name": "person", "extract_on_fields": ["name"]}],
            "extract_with_single_prompt": False,
        }
        replies = [["Ada"]]
    elif family == "semantic_filter":
        attrs, replies = {"filter_conditions": {"score": "positive"}}, [True]
    elif family == "semantic_join":
        data = [[{"name": "Ada"}, {"name": "Bob"}], [{"person": "Ada"}]]
        attrs = {
            "join_predicate": "same person",
            "batch_size": 1,
            "use_cache": False,
            "estimate_cost": False,
        }
        replies = [{"pair_1": True}, {"pair_1": True}]
    elif family == "semantic_project":
        attrs, replies = {"projection_instructions": "keep name"}, [{"name": "person"}]
    else:
        attrs = {"output_desc": {"label": {"description": "score label"}}, "strategy": "per_record"}
        replies = [
            {
                "label": {
                    "source_fields": ["score"],
                    "transformation_type": "field_mapping_with_value_change",
                }
            },
            {"label": "positive"},
        ]
    calls: list[dict[str, Any]] = []
    successes: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        if "temperature" in kwargs:
            raise rejection(kind)
        successes.append(dict(kwargs))
        assert replies, "unexpected extra operator call"
        return {
            "choices": [{"message": {"content": json.dumps(replies.pop(0))}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        }

    monkeypatch.setattr(litellm, "completion", completion)
    monkeypatch.setattr(litellm, "completion_cost", price)
    output = operator.apply(data, attrs, props)
    assert output and any(output)
    assert not replies
    assert len(calls) == 2 * len(successes)
    for first, second in zip(calls[::2], calls[1::2], strict=True):
        assert first.pop("temperature") == 0
        assert first == second
    assert "llm.temperature" not in props
    assert operator.DEFAULT_PROPERTIES["openai.temperature"] == 0


@pytest.mark.parametrize("mode", ["sync", "async", "observed"])
def test_fallback_reserves_second_rate_slot(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    from tests.unit.llm.test_temperature_fallback import install

    calls = install(monkeypatch, [rejection("structured")])
    slots: list[int] = []

    def reserve(client: LLMClient, properties: dict[str, Any]) -> None:
        slots.append(len(calls))

    monkeypatch.setattr(LLMClient, "_apply_rate_limit", reserve)
    props = prepared()
    invoke(LLMClient("rate", props), props, mode)
    assert slots == [0, 1]

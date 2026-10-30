"""Behavior, prompt, provider, and interface tests for `nl2llm`."""

from __future__ import annotations

from typing import Any

import litellm  # the deterministic stub
import pytest

from blue_data_ops.llm import LLMClient, LLMError
from blue_data_ops.operators.nl2llm_operator import NL2LLMOperator
from blue_data_ops.operators.registry import versioned_registry

INPUT: list[list[dict[str, Any]]] = [[]]


@pytest.fixture(autouse=True)
def _reset_fake() -> None:  # pyright: ignore[reportUnusedFunction] — autouse
    litellm.calls.clear()
    litellm.fail_next.clear()


@pytest.fixture
def op() -> NL2LLMOperator:
    return NL2LLMOperator()


def _json_provider(content: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(**kwargs: Any) -> Any:
        litellm.calls.append(kwargs)

        class _R:
            def model_dump(self) -> dict[str, Any]:
                return {
                    "choices": [{"message": {"role": "assistant", "content": content}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }

        return _R()

    monkeypatch.setattr(litellm, "completion", fake)


# --- Blank query: empty result with zero provider calls ---
@pytest.mark.parametrize("query", ["", "   "])
def test_blank_query_returns_empty(op: NL2LLMOperator, query: str) -> None:
    assert op.apply(INPUT, {"query": query}) == []
    assert litellm.calls == []


# --- Rendered prompt bytes reach the provider unchanged ---
def test_prompt_construction_with_typed_and_untyped_attrs(
    op: NL2LLMOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider("[]", monkeypatch)
    op.apply(
        INPUT,
        {
            "query": "top languages",
            "context": "job market",
            "attrs": [{"name": "language", "type": "string"}, {"name": "rank"}],
        },
    )
    content = litellm.calls[-1]["messages"][0]["content"]
    assert "Query: top languages" in content
    assert "Required output attributes:" in content
    assert "- language: string" in content
    assert "- rank: (type will be inferred)" in content
    assert "Context:\njob market" in content


def test_no_attrs_gives_empty_attrs_section(
    op: NL2LLMOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider("[]", monkeypatch)
    op.apply(INPUT, {"query": "q"})
    content = litellm.calls[-1]["messages"][0]["content"]
    assert "Attributes:\n\n" in content  # ${attrs} substituted with ""


# --- Output parsing: fence removal, JSON conversion, and list wrapping ---
def test_fenced_json_output_pipeline(op: NL2LLMOperator, monkeypatch: pytest.MonkeyPatch) -> None:
    _json_provider('```json\n[{"language": "Python", "rank": 1}]\n```', monkeypatch)
    out = op.apply(INPUT, {"query": "q"})
    assert out == [[{"language": "Python", "rank": 1}]]  # [cast-output] wrap


def test_json_substring_is_preserved(op: NL2LLMOperator, monkeypatch: pytest.MonkeyPatch) -> None:
    _json_provider('[{"jsonish": 1}]', monkeypatch)
    out = op.apply(INPUT, {"query": "q"})
    assert out == [[{"jsonish": 1}]]


# --- Provider defaults and caller overrides ---
def test_defaults_reach_provider(op: NL2LLMOperator, monkeypatch: pytest.MonkeyPatch) -> None:
    _json_provider("[]", monkeypatch)
    op.apply(INPUT, {"query": "q"})
    call = litellm.calls[-1]
    assert call["model"] == "gpt-6-luna"
    assert call["max_completion_tokens"] == 4096
    assert "max_tokens" not in call
    assert "temperature" not in call
    assert "reasoning_effort" not in call
    assert "api" not in call and "service_url" not in call


def test_active_default_reaches_provider_without_sampling_or_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _json_provider("[]", monkeypatch)
    operator = versioned_registry().resolve("nl2llm@3.0.0")
    _, _, meta = operator.run(INPUT, {"query": "q"})
    assert not meta.errors
    call = litellm.calls[-1]
    assert call["model"] == "gpt-6-luna"
    assert call["max_completion_tokens"] == 4096
    assert "max_tokens" not in call
    assert "temperature" not in call
    assert "reasoning_effort" not in call

    _, _, meta = operator.run(INPUT, {"query": "q"}, {"llm.model": "gpt-4o"})
    assert not meta.errors
    override = litellm.calls[-1]
    assert override["model"] == "gpt-4o"
    assert override["max_tokens"] == 4096
    assert override["temperature"] == 0
    assert "max_completion_tokens" not in override
    assert "reasoning_effort" not in override


def test_caller_properties_override_defaults(
    op: NL2LLMOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider("[]", monkeypatch)
    op.apply(INPUT, {"query": "q"}, {"openai.model": "gpt-4o-mini"})
    assert litellm.calls[-1]["model"] == "gpt-4o-mini"


@pytest.mark.parametrize("model", ["gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-5-mini"])
def test_reasoning_model_omits_operator_temperature(
    op: NL2LLMOperator, monkeypatch: pytest.MonkeyPatch, model: str
) -> None:
    _json_provider("[]", monkeypatch)
    op.apply(INPUT, {"query": "q"}, {"llm.model": model, "llm.reasoning_effort": "low"})
    call = litellm.calls[-1]
    assert call["model"] == model
    assert "temperature" not in call
    assert call["max_completion_tokens"] == 4096


def test_explicit_sampling_conflict_is_not_discarded(
    op: NL2LLMOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider("[]", monkeypatch)
    with pytest.raises(LLMError) as raised:
        op.apply(
            INPUT,
            {"query": "q"},
            {
                "llm.model": "gpt-6-sol",
                "llm.reasoning_effort": "medium",
                "llm.temperature": 0,
            },
        )
    assert raised.value.code == "unsupported_parameter"
    assert litellm.calls == []


def test_conflicting_token_limits_have_a_useful_run_error(op: NL2LLMOperator) -> None:
    _, _, meta = op.run(
        INPUT,
        {"query": "q"},
        {"openai.max_tokens": 1024, "openai.max_completion_tokens": 2048},
    )
    [error] = meta.errors
    assert error.message == "conflicting LLM token limits"
    assert error.suggestion == "Set only one of max_tokens and max_completion_tokens."
    assert litellm.calls == []


def test_injected_client_is_used(op: NL2LLMOperator, monkeypatch: pytest.MonkeyPatch) -> None:
    _json_provider("[]", monkeypatch)
    client = LLMClient("mine", {**NL2LLMOperator.DEFAULT_PROPERTIES, "openai.temperature": None})
    out = op.apply(INPUT, {"query": "q"}, {"llm_client": client})
    assert out == [[]]
    assert len(client.ledger.records) == 1  # the injected client did the call


def test_injected_client_model_does_not_keep_incompatible_operator_default(
    op: NL2LLMOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider("[]", monkeypatch)
    client = LLMClient("mine", {"llm.model": "gpt-6-sol"})
    op.apply(INPUT, {"query": "q"}, {"llm_client": client})
    assert litellm.calls[-1]["model"] == "gpt-6-sol"
    assert "temperature" not in litellm.calls[-1]


def test_injected_client_with_operator_defaults_can_switch_model(
    op: NL2LLMOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider("[]", monkeypatch)
    client = LLMClient(
        "mine",
        {**NL2LLMOperator.DEFAULT_PROPERTIES, "openai.temperature": None, "llm.model": "gpt-6-sol"},
    )
    assert op.apply(INPUT, {"query": "q"}, {"llm_client": client}) == [[]]
    assert litellm.calls[-1]["model"] == "gpt-6-sol"
    assert "temperature" not in litellm.calls[-1]


def test_injected_client_can_replace_default_token_limit(
    op: NL2LLMOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider("[]", monkeypatch)
    client = LLMClient("mine", {**NL2LLMOperator.DEFAULT_PROPERTIES, "openai.temperature": None})
    assert op.apply(
        INPUT,
        {"query": "q"},
        {"llm_client": client, "openai.max_completion_tokens": 8192},
    ) == [[]]
    assert litellm.calls[-1]["max_completion_tokens"] == 8192
    assert "max_tokens" not in litellm.calls[-1]


@pytest.mark.parametrize("copy_defaults", [False, True])
@pytest.mark.parametrize("model", ["gpt-4o", "gpt-6-sol"])
def test_injected_client_native_cap_replaces_default_token_limit(
    op: NL2LLMOperator, monkeypatch: pytest.MonkeyPatch, copy_defaults: bool, model: str
) -> None:
    _json_provider("[]", monkeypatch)
    stored = dict(NL2LLMOperator.DEFAULT_PROPERTIES) if copy_defaults else {}
    if model == "gpt-6-sol":
        stored["openai.temperature"] = None
    stored["openai.model"] = model
    stored["openai.max_completion_tokens"] = 8192
    client = LLMClient("mine", stored)
    assert op.apply(INPUT, {"query": "q"}, {"llm_client": client}) == [[]]
    assert litellm.calls[-1]["max_completion_tokens"] == 8192
    assert "max_tokens" not in litellm.calls[-1]
    assert ("temperature" in litellm.calls[-1]) is (model == "gpt-4o")


# --- Provider errors propagate ---
def test_provider_error_propagates(op: NL2LLMOperator) -> None:
    litellm.fail_next.extend([RuntimeError("down")] * 3)
    with pytest.raises(LLMError):
        op.apply(INPUT, {"query": "q"})


# --- Validator ---
@pytest.mark.parametrize(
    "attrs,expected",
    [
        ({"query": "q"}, True),
        ({}, False),  # query required
        ({"query": ""}, True),  # blank validates; apply returns []
        ({"query": "q", "attrs": [{"name": "a"}]}, True),
        ({"query": "q", "attrs": [{"name": "a", "type": "str"}]}, True),
        ({"query": "q", "attrs": ["not-a-dict"]}, False),
        ({"query": "q", "attrs": [{"type": "str"}]}, False),  # no name
        ({"query": "q", "attrs": 5}, False),  # composite type gate (list[dict])
        ({"query": 123}, False),  # str gate (pydantic-lax rejects int for str)
    ],
    ids=[
        "valid",
        "no-query",
        "blank-query-validates",
        "attrs-ok",
        "attrs-typed",
        "attrs-non-dict",
        "attrs-no-name",
        "attrs-not-list",
        "query-not-str",
    ],
)
def test_validator(op: NL2LLMOperator, attrs: dict[str, Any], expected: bool) -> None:
    assert op.validate(INPUT, attrs) is expected


# --- Byte-level prompt contract ---
def test_prompt_template_bytes() -> None:
    # The template is protocol text, so its complete byte sequence is contractual.
    import hashlib

    from blue_data_ops.operators.nl2llm_operator import (
        _PROMPT,  # pyright: ignore[reportPrivateUsage]
    )

    assert (
        hashlib.sha256(_PROMPT.encode()).hexdigest()
        == "9c802d7c25893030f534b56c3dcb416760419f545a4b3e0cebb00c9c0c86c220"
    )


def test_rendered_prompt_full_equality(op: NL2LLMOperator, monkeypatch: pytest.MonkeyPatch) -> None:
    # Full-content equality (not substrings): the rendered prompt must equal the
    # template with exactly these three substitutions and nothing else changed.
    import json
    from pathlib import Path

    _json_provider("[]", monkeypatch)
    attrs = [{"name": "language", "type": "string"}, {"name": "rank"}]
    op.apply(INPUT, {"query": "top languages", "context": "job market", "attrs": attrs})
    content = litellm.calls[-1]["messages"][0]["content"]

    frozen = json.loads(
        (Path(__file__).parents[2] / "fixtures/llm_benign_prompts.json").read_text()
    )
    expected = frozen["nl2llm"]["prompt"]
    assert content == expected
    assert not expected.endswith("\n")


# --- Complete 15-field defaults contract ---
def test_default_properties_field_by_field() -> None:
    from blue_data_ops.operators.nl2llm_operator import (
        _PROMPT,  # pyright: ignore[reportPrivateUsage]
    )

    assert NL2LLMOperator.DEFAULT_PROPERTIES == {
        "openai.api": "ChatCompletion",
        "openai.model": "gpt-6-luna",
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
            {
                "transformation": "sub",
                "from": r"(?is)\A```(?:json)?[ \t]*\r?\n(.*)\r?\n```\Z",
                "to": r"\1",
            },
        ],
        "output_strip": True,
        "output_cast": "json",
    }
    assert len(NL2LLMOperator.DEFAULT_PROPERTIES) == 15


# --- Explainer (custom minimal) ---
def test_explainer(op: NL2LLMOperator) -> None:
    exp = op.explain([[{"a": 1}]], INPUT, {"query": "q"})
    assert exp == {"output": [[{"a": 1}]], "attributes": {"query": "q"}}


# --- Interface contract ---
def test_interface(op: NL2LLMOperator) -> None:
    assert op.name == "nl2llm"
    assert op.description == (
        "Processes natural language query using LLM models and returns structured data"
    )
    expected: dict[str, tuple[str, str, bool, Any]] = {
        "query": ("str", "Natural language query to process", True, None),
        "context": ("str", "Optional context to provide domain knowledge", False, ""),
        "attrs": (
            "list[dict]",
            "List of attribute specifications (dicts with name and optional type)",
            False,
            [],
        ),
    }
    assert set(op.attributes) == set(expected)
    for attr_name, (attr_type, attr_desc, required, default) in expected.items():
        spec = op.attributes[attr_name]
        assert spec.type == attr_type
        assert spec.description == attr_desc
        assert spec.required is required
        assert spec.default == default

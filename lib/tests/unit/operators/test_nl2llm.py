"""Behavior, prompt, provider, and interface tests for `nl2llm`."""

from __future__ import annotations

from typing import Any

import litellm  # the deterministic stub
import pytest

from blue_data_ops.llm import LLMClient, LLMError
from blue_data_ops.operators.nl2llm_operator import NL2LLMOperator

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


# --- Literal "json" substring removal ---
def test_json_substring_is_removed_before_parsing(
    op: NL2LLMOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The fence cleanup replaces the SUBSTRING "json" anywhere: a key "jsonish"
    # becomes "ish" before the JSON cast.
    _json_provider('[{"jsonish": 1}]', monkeypatch)
    out = op.apply(INPUT, {"query": "q"})
    assert out == [[{"ish": 1}]]


# --- Provider defaults and caller overrides ---
def test_defaults_reach_provider(op: NL2LLMOperator, monkeypatch: pytest.MonkeyPatch) -> None:
    _json_provider("[]", monkeypatch)
    op.apply(INPUT, {"query": "q"})
    call = litellm.calls[-1]
    assert call["model"] == "gpt-4o"
    assert call["max_tokens"] == 4096
    assert call["temperature"] == 0
    assert "api" not in call and "service_url" not in call


def test_caller_properties_override_defaults(
    op: NL2LLMOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider("[]", monkeypatch)
    op.apply(INPUT, {"query": "q"}, {"openai.model": "gpt-4o-mini"})
    assert litellm.calls[-1]["model"] == "gpt-4o-mini"


def test_injected_client_is_used(op: NL2LLMOperator, monkeypatch: pytest.MonkeyPatch) -> None:
    _json_provider("[]", monkeypatch)
    client = LLMClient("mine", NL2LLMOperator.DEFAULT_PROPERTIES)
    out = op.apply(INPUT, {"query": "q"}, {"llm_client": client})
    assert out == [[]]
    assert len(client.ledger.records) == 1  # the injected client did the call


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
    from string import Template

    from blue_data_ops.operators.nl2llm_operator import (
        _PROMPT,  # pyright: ignore[reportPrivateUsage]
    )

    _json_provider("[]", monkeypatch)
    attrs = [{"name": "language", "type": "string"}, {"name": "rank"}]
    op.apply(INPUT, {"query": "top languages", "context": "job market", "attrs": attrs})
    content = litellm.calls[-1]["messages"][0]["content"]

    templated = Template(_PROMPT).safe_substitute(
        query="top languages",
        context="job market",
        attrs=(
            "Required output attributes:\n- language: string\n- rank: (type will be inferred)\n"
        ),
    )
    # The Jinja pass follows Template substitution and trims the final newline.
    from jinja2 import BaseLoader, Environment

    expected = Environment(loader=BaseLoader()).from_string(templated).render()
    assert content == expected
    assert not content.endswith("\n")  # the Jinja trailing-newline trim, explicit


# --- Complete 15-field defaults contract ---
def test_default_properties_field_by_field() -> None:
    from blue_data_ops.operators.nl2llm_operator import (
        _PROMPT,  # pyright: ignore[reportPrivateUsage]
    )

    assert NL2LLMOperator.DEFAULT_PROPERTIES == {
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

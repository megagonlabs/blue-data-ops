from __future__ import annotations

import hashlib
from typing import Any

import litellm
import pytest

from blue_data_ops.llm import LLMClient, LLMError
from blue_data_ops.operators.semantic_filter_operator import SemanticFilterOperator
from tests.unit.operators._semantic_test_helpers import (
    json_provider as _json_provider,
)
from tests.unit.operators._semantic_test_helpers import (
    reset_litellm,
)

DATA: list[list[dict[str, Any]]] = [
    [
        {"id": 1, "name": "Ada", "score": 8},
        {"id": 2, "name": "Bob"},
    ]
]


@pytest.fixture(autouse=True)
def _reset_fake() -> None:  # pyright: ignore[reportUnusedFunction]
    reset_litellm()


@pytest.fixture
def op() -> SemanticFilterOperator:
    return SemanticFilterOperator()


@pytest.mark.parametrize(  # pyright: ignore[reportUnknownArgumentType]
    "input_data,attrs",
    [  # pyright: ignore[reportUnknownArgumentType]
        ([], {"filter_conditions": {"score": "high"}}),
        ([[]], {"filter_conditions": {"score": "high"}}),
        (DATA, {}),
        (DATA, {"filter_conditions": {}}),
    ],
)
def test_guards_return_empty_without_provider(
    op: SemanticFilterOperator,
    input_data: list[list[dict[str, Any]]],
    attrs: dict[str, Any],
) -> None:
    assert op.apply(input_data, attrs) == []
    assert litellm.calls == []


def test_string_truth_set_is_exact(
    op: SemanticFilterOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider([" TRUE ", "false"], monkeypatch)
    assert op.apply(DATA, {"filter_conditions": {"score": "high"}}) == [[DATA[0][0]]]
    for value in ["yes", " YeS ", "1", " 1\t", "include", " InClUdE\n"]:
        _json_provider([value, " false "], monkeypatch)
        assert op.apply(DATA, {"filter_conditions": {"score": "high"}}) == [[DATA[0][0]]]
    for value in ["maybe", "", "Yes.", "True."]:
        _json_provider(value, monkeypatch)
        with pytest.raises(ValueError, match="model reply"):
            op.apply(DATA, {"filter_conditions": {"score": "high"}})


def test_non_string_results_are_rejected(
    op: SemanticFilterOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    for value in [1, 0, [], [0], None]:

        def fake(*args: Any, **kwargs: Any) -> Any:
            return value

        monkeypatch.setattr(LLMClient, "execute_api_call", fake)
        with pytest.raises(ValueError, match="model reply"):
            op.apply(DATA, {"filter_conditions": {"score": "high"}})


def test_return_indices_and_exact_condition_text(
    op: SemanticFilterOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider(["true", "false"], monkeypatch)
    assert op.apply(
        DATA,
        {
            "filter_conditions": {
                "score": "at least 5",
                "missing": "present",
            },
            "return_idx": True,
            "context": "ctx",
            "demonstrations": "demo",
        },
    ) == [[{"indices": [0]}]]
    first_prompt = litellm.calls[0]["messages"][0]["content"]
    assert (
        "1. Field 'score' (value: 8) should satisfy: at least 5\n"
        "2. Field 'missing' (not present in record) should satisfy: present"
    ) in first_prompt
    assert "## Context\nctx" in first_prompt
    assert "## Demonstrations\ndemo" in first_prompt


def test_filtered_record_identity_is_preserved(
    op: SemanticFilterOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider(["true", "false"], monkeypatch)
    output = op.apply(DATA, {"filter_conditions": {"score": "high"}})
    assert output[0][0] is DATA[0][0]


def test_later_empty_group_is_preserved(
    op: SemanticFilterOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider("true", monkeypatch)
    assert op.apply([DATA[0][:1], []], {"filter_conditions": {"score": "high"}}) == [
        [DATA[0][0]],
        [],
    ]


def test_provider_error_propagates(op: SemanticFilterOperator) -> None:
    litellm.fail_next.extend([RuntimeError("down")] * 3)
    with pytest.raises(LLMError):
        op.apply(DATA, {"filter_conditions": {"score": "high"}})


@pytest.mark.parametrize(
    "attrs,expected",
    [
        ({"filter_conditions": {"score": "high"}}, True),
        ({}, False),
        ({"filter_conditions": {}}, False),
        ({"filter_conditions": [("score", "high")]}, False),
        ({"filter_conditions": {1: "high"}}, False),
        ({"filter_conditions": {"score": 1}}, False),
        ({"filter_conditions": {" ": "high"}}, False),
        ({"filter_conditions": {"score": " "}}, False),
        # Blue spells the declaration "boolean", which its parser treats as Any.
        ({"filter_conditions": {"score": "high"}, "return_idx": "yes"}, True),
        # Pydantic-lax str accepts bytes and the business validator ignores context.
        ({"filter_conditions": {"score": "high"}, "context": b"ctx"}, True),
    ],
)
def test_validator(op: SemanticFilterOperator, attrs: dict[str, Any], expected: bool) -> None:
    assert op.validate(DATA, attrs) is expected


def test_prompt_and_defaults_are_pinned() -> None:
    assert hashlib.sha256(SemanticFilterOperator.FILTER_PROMPT.encode()).hexdigest() == (
        "b73bacd2406123fee9aad698596d905d343217227465dfeb63cfabea17a2ae47"
    )
    assert SemanticFilterOperator.DEFAULT_PROPERTIES == {
        "openai.api": "ChatCompletion",
        "openai.model": "gpt-6-luna",
        "openai.stream": False,
        "openai.max_tokens": 1024,
        "openai.temperature": 0,
        "input_json": '[{"role": "user"}]',
        "input_context": "$[0]",
        "input_context_field": "content",
        "input_field": "messages",
        "input_template": SemanticFilterOperator.FILTER_PROMPT,
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
        # The adapter deliberately leaves unknown cast names unchanged.
        "output_cast": "bool",
    }


def test_interface_exact(op: SemanticFilterOperator) -> None:
    assert op.name == "semantic_filter"
    assert op.description == (
        "Filters records based on natural language conditions using LLM models"
    )
    expected: dict[str, tuple[str, str, bool, Any]] = {
        "filter_conditions": (
            "dict[str, str]",
            "Dictionary mapping field names to natural language filter conditions",
            True,
            None,
        ),
        "context": (
            "str",
            "Optional context to provide domain knowledge or additional instructions",
            False,
            "",
        ),
        "demonstrations": (
            "str",
            "Optional demonstrations to help in-context learning",
            False,
            "",
        ),
        "return_idx": (
            "boolean",
            "If true, return indices of records that satisfy all conditions, else return "
            "filtered records",
            False,
            False,
        ),
    }
    assert set(op.attributes) == set(expected)
    for name, values in expected.items():
        spec = op.attributes[name]
        assert (spec.type, spec.description, spec.required, spec.default) == values

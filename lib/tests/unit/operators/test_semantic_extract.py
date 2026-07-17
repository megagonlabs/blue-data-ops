from __future__ import annotations

import hashlib
from typing import Any

import litellm
import pytest

from blue_data_ops.llm import LLMError
from blue_data_ops.operators.semantic_extract_operator import SemanticExtractOperator
from tests.unit.operators._semantic_test_helpers import (
    json_provider as _json_provider,
)
from tests.unit.operators._semantic_test_helpers import (
    reset_litellm,
)

DATA: list[list[dict[str, Any]]] = [
    [
        {"id": 1, "name": "Ada", "bio": "Ada uses Python", "score": 8},
        {"id": 2, "name": "Bob", "bio": "", "active": True},
    ]
]


@pytest.fixture(autouse=True)
def _reset_fake() -> None:  # pyright: ignore[reportUnusedFunction]
    reset_litellm()


@pytest.fixture
def op() -> SemanticExtractOperator:
    return SemanticExtractOperator()


@pytest.mark.parametrize(  # pyright: ignore[reportUnknownArgumentType]
    "input_data,attrs",
    [  # pyright: ignore[reportUnknownArgumentType]
        ([], {"entities": [{"name": "skill"}]}),
        ([[]], {"entities": [{"name": "skill"}]}),
        (DATA, {}),
        (DATA, {"entities": []}),
    ],
)
def test_guards_return_empty_without_provider(
    op: SemanticExtractOperator,
    input_data: list[list[dict[str, Any]]],
    attrs: dict[str, Any],
) -> None:
    assert op.apply(input_data, attrs) == []
    assert litellm.calls == []


def test_single_prompt_outputs_and_nondict_fallback(
    op: SemanticExtractOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider(
        ['{"skill": ["Python"], "person": ["Ada"]}', '["not-a-dict"]'],
        monkeypatch,
    )
    output = op.apply(
        DATA,
        {
            "entities": [
                {
                    "name": "skill",
                    "type": "str",
                    "description": "A skill",
                    "extract_on_fields": ["bio", "missing"],
                },
                {"name": "person"},
            ],
            "context": "ctx",
            "demonstrations": "demo",
        },
    )
    assert output == [
        [
            {"skill": ["Python"], "person": ["Ada"]},
            {"skill": [], "person": []},
        ]
    ]
    assert len(litellm.calls) == 2
    first_prompt = litellm.calls[0]["messages"][0]["content"]
    assert "- skill (str): A skill (from fields: bio, missing)" in first_prompt
    assert "- person: Extract person from the text (from all fields)" in first_prompt
    assert "'bio': 'Ada uses Python'" in first_prompt
    assert "'missing'" not in first_prompt


def test_individual_mode_skips_empty_fields_and_normalizes_shapes(
    op: SemanticExtractOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider(['["Python"]', '"Ada"', "[]"], monkeypatch)
    output = op.apply(
        DATA,
        {
            "entities": [
                {
                    "name": "skill",
                    "type": "str",
                    "description": "A skill",
                    "extract_on_fields": ["bio"],
                },
                {"name": "person", "extract_on_fields": ["name"]},
                {"name": "missing", "extract_on_fields": ["absent"]},
            ],
            "extract_with_single_prompt": False,
        },
    )
    assert output == [
        [
            {"skill": ["Python"], "person": ["Ada"], "missing": []},
            {"skill": [], "person": [], "missing": []},
        ]
    ]
    # Ada: skill + person; Bob: person only. Missing fields never call the provider.
    assert len(litellm.calls) == 3
    assert "- **Name**: skill (str)" in litellm.calls[0]["messages"][0]["content"]
    assert "bio: Ada uses Python" in litellm.calls[0]["messages"][0]["content"]


def test_later_empty_group_is_preserved(
    op: SemanticExtractOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider('{"skill": ["Python"]}', monkeypatch)
    assert op.apply([DATA[0][:1], []], {"entities": [{"name": "skill"}]}) == [
        [{"skill": ["Python"]}],
        [],
    ]


def test_provider_error_propagates(op: SemanticExtractOperator) -> None:
    litellm.fail_next.extend([RuntimeError("down")] * 3)
    with pytest.raises(LLMError):
        op.apply(DATA, {"entities": [{"name": "skill"}]})


@pytest.mark.parametrize(  # pyright: ignore[reportUnknownArgumentType]
    "attrs,expected",
    [  # pyright: ignore[reportUnknownArgumentType]
        ({"entities": [{"name": "skill"}]}, True),
        ({}, False),
        ({"entities": []}, False),
        ({"entities": ({"name": "skill"},)}, False),
        ({"entities": ["skill"]}, False),
        ({"entities": [{"description": "x"}]}, False),
        ({"entities": [{"name": "x", "description": 1}]}, False),
        ({"entities": [{"name": "x", "type": 1}]}, False),
        ({"entities": [{"name": "x", "extract_on_fields": ("bio",)}]}, False),
        ({"entities": [{"name": "x", "extract_on_fields": []}]}, False),
        # Blue checks only that this is a non-empty list, not member types.
        ({"entities": [{"name": "x", "extract_on_fields": [1]}]}, True),
        # Pydantic-lax bool accepts this string before Blue's business validator.
        ({"entities": [{"name": "x"}], "extract_with_single_prompt": "false"}, True),
    ],
)
def test_validator(op: SemanticExtractOperator, attrs: dict[str, Any], expected: bool) -> None:
    assert op.validate(DATA, attrs) is expected


def test_invoke_rejects_invalid(op: SemanticExtractOperator) -> None:
    assert op.invoke(DATA, {}) is None


def test_prompt_templates_and_defaults_are_pinned() -> None:
    assert hashlib.sha256(SemanticExtractOperator.SINGLE_EXTRACT_PROMPT.encode()).hexdigest() == (
        "92c9635ebb09ddf6c732c963fdd140600e2bdfcde1f45036a47dd5cf1f9f0a89"
    )
    assert (
        hashlib.sha256(SemanticExtractOperator.INDIVIDUAL_EXTRACT_PROMPT.encode()).hexdigest()
        == "906f4dd82803ee815225896d50124b819d7f26b734c80fe87d9afa60a8220198"
    )
    assert SemanticExtractOperator.DEFAULT_PROPERTIES == {
        "openai.api": "ChatCompletion",
        "openai.model": "gpt-4o",
        "openai.stream": False,
        "openai.max_tokens": 4096,
        "openai.temperature": 0,
        "input_json": '[{"role": "user"}]',
        "input_context": "$[0]",
        "input_context_field": "content",
        "input_field": "messages",
        "input_template": SemanticExtractOperator.SINGLE_EXTRACT_PROMPT,
        "output_path": "$.choices[0].message.content",
        "service_prefix": "openai",
        "output_transformations": [
            {"transformation": "replace", "from": "```", "to": ""},
            {"transformation": "replace", "from": "json", "to": ""},
        ],
        "output_strip": True,
        "output_cast": "json",
    }


def test_interface_exact(op: SemanticExtractOperator) -> None:
    assert op.name == "semantic_extract"
    assert op.description == (
        "Extracts entities from natural language text fields using LLM models"
    )
    expected: dict[str, tuple[str, str, bool, Any]] = {
        "entities": (
            "list[dict]",
            "List of entities to extract. Each dict has 'name', 'description' (optional), "
            "'extract_on_fields' (optional list of field names - if not provided, extracts "
            "from all fields), and 'type' (optional)",
            True,
            None,
        ),
        "context": (
            "str",
            "Additional context information that provides domain knowledge or additional "
            "instructions for the extraction",
            False,
            "",
        ),
        "demonstrations": (
            "str",
            "Additional demonstrations to help in-context learning",
            False,
            "",
        ),
        "extract_with_single_prompt": (
            "bool",
            "If true, extract all entities in a single prompt, else extract each entity "
            "with individual prompt",
            False,
            True,
        ),
    }
    assert set(op.attributes) == set(expected)
    for name, values in expected.items():
        spec = op.attributes[name]
        assert (spec.type, spec.description, spec.required, spec.default) == values

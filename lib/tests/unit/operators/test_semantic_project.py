from __future__ import annotations

import hashlib
from typing import Any

import litellm
import pytest

from blue_data_ops.llm import LLMError
from blue_data_ops.operators.semantic_project_operator import SemanticProjectOperator
from tests.unit.operators._semantic_test_helpers import (
    json_provider as _json_provider,
)
from tests.unit.operators._semantic_test_helpers import (
    reset_litellm,
)

DATA: list[list[dict[str, Any]]] = [
    [
        {"id": 1, "name": "Ada", "score": 8, "tags": ["python"]},
        {"id": 2, "name": "Bob", "score": None, "active": True},
    ]
]


@pytest.fixture(autouse=True)
def _reset_fake() -> None:  # pyright: ignore[reportUnusedFunction]
    reset_litellm()


@pytest.fixture
def op() -> SemanticProjectOperator:
    return SemanticProjectOperator()


@pytest.mark.parametrize(  # pyright: ignore[reportUnknownArgumentType]
    "input_data,attrs",
    [  # pyright: ignore[reportUnknownArgumentType]
        ([], {"projection_instructions": "keep name"}),
        ([[]], {"projection_instructions": "keep name"}),
        (DATA, {}),
        (DATA, {"projection_instructions": ""}),
    ],
)
def test_guards_return_empty_without_provider(
    op: SemanticProjectOperator,
    input_data: list[list[dict[str, Any]]],
    attrs: dict[str, Any],
) -> None:
    assert op.apply(input_data, attrs) == []
    assert litellm.calls == []


def test_mapping_projects_renames_and_omits_missing(
    op: SemanticProjectOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider(
        '{"name": "person", "score": "rating"}',
        monkeypatch,
    )
    assert op.apply(DATA, {"projection_instructions": "keep and rename"}) == [
        [
            {"person": "Ada", "rating": 8},
            {"person": "Bob", "rating": None},
        ]
    ]
    prompt = litellm.calls[0]["messages"][0]["content"]
    assert (
        "- id (integer)\n- name (string)\n- score (integer|null)\n"
        "- tags (array)\n- active (boolean)"
    ) in prompt
    assert "## Projection Instructions\nkeep and rename" in prompt


def test_non_dict_mapping_is_rejected(
    op: SemanticProjectOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider('["name"]', monkeypatch)
    with pytest.raises(ValueError, match="model reply"):
        op.apply(DATA, {"projection_instructions": "keep name"})


def test_mapping_with_only_missing_keys_is_rejected(
    op: SemanticProjectOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider('{"missing": "ghost"}', monkeypatch)
    with pytest.raises(ValueError, match="model reply"):
        op.apply(DATA, {"projection_instructions": "keep missing"})


def test_duplicate_target_is_rejected(
    op: SemanticProjectOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider('{"a": "x", "b": "x"}', monkeypatch)
    with pytest.raises(ValueError, match="model reply"):
        op.apply([[{"a": 1, "b": 2}]], {"projection_instructions": "merge"})


def test_nested_value_identity_is_preserved(
    op: SemanticProjectOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider('{"tags": "skills"}', monkeypatch)
    output = op.apply(DATA, {"projection_instructions": "keep tags"})
    assert output[0][0]["skills"] is DATA[0][0]["tags"]


def test_later_empty_group_is_preserved(
    op: SemanticProjectOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider('{"name": "name"}', monkeypatch)
    assert op.apply([DATA[0][:1], []], {"projection_instructions": "keep name"}) == [
        [{"name": "Ada"}],
        [],
    ]


def test_provider_error_propagates(op: SemanticProjectOperator) -> None:
    litellm.fail_next.extend([RuntimeError("down")] * 3)
    with pytest.raises(LLMError):
        op.apply(DATA, {"projection_instructions": "keep name"})


@pytest.mark.parametrize(
    "attrs,expected",
    [
        ({"projection_instructions": "keep name"}, True),
        ({}, False),
        ({"projection_instructions": ""}, False),
        ({"projection_instructions": "  "}, False),
        ({"projection_instructions": b"keep"}, False),
        ({"projection_instructions": 1}, False),
    ],
)
def test_validator(op: SemanticProjectOperator, attrs: dict[str, Any], expected: bool) -> None:
    assert op.validate(DATA, attrs) is expected


def test_prompt_and_defaults_are_pinned() -> None:
    assert hashlib.sha256(SemanticProjectOperator.MAPPING_PROMPT.encode()).hexdigest() == (
        "0edeb890f9d68aba8e1dc893dab86fb2016c465717b3571cbdbe837d760a200e"
    )
    assert SemanticProjectOperator.DEFAULT_PROPERTIES == {
        "openai.api": "ChatCompletion",
        "openai.model": "gpt-6-luna",
        "openai.stream": False,
        "openai.max_tokens": 1024,
        "openai.temperature": 0,
        "input_json": '[{"role": "user"}]',
        "input_context": "$[0]",
        "input_context_field": "content",
        "input_field": "messages",
        "input_template": SemanticProjectOperator.MAPPING_PROMPT,
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


def test_interface_exact(op: SemanticProjectOperator) -> None:
    assert op.name == "semantic_project"
    assert op.description == (
        "Projects records to select and rename columns using LLM-based mapping resolution"
    )
    assert set(op.attributes) == {"projection_instructions"}
    spec = op.attributes["projection_instructions"]
    assert (
        spec.type,
        spec.description,
        spec.required,
        spec.default,
    ) == (
        "str",
        "Natural language description of which columns to keep and how to rename them",
        True,
        None,
    )

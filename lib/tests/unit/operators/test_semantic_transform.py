from __future__ import annotations

import hashlib
from typing import Any

import litellm
import pytest

from blue_data_ops.llm import LLMError
from blue_data_ops.operators.semantic_transform_operator import SemanticTransformOperator
from tests.unit.operators._semantic_test_helpers import (
    json_provider as _json_provider,
)
from tests.unit.operators._semantic_test_helpers import (
    reset_litellm,
)

DATA: list[list[dict[str, Any]]] = [
    [
        {"name": "Ada", "city": "NY", "score": 1},
        {"name": "Bob", "city": "NY", "score": 2},
        {"name": "Cid", "city": "SF", "score": 2},
    ]
]


@pytest.fixture(autouse=True)
def _reset_fake() -> None:  # pyright: ignore[reportUnusedFunction]
    reset_litellm()


@pytest.fixture
def op() -> SemanticTransformOperator:
    return SemanticTransformOperator()


@pytest.mark.parametrize(  # pyright: ignore[reportUnknownArgumentType]
    "input_data,attrs",
    [  # pyright: ignore[reportUnknownArgumentType]
        ([], {"output_desc": {"label": {"description": "Label"}}}),
        ([[]], {"output_desc": {"label": {"description": "Label"}}}),
        (DATA, {}),
        (DATA, {"output_desc": {}}),
    ],
)
def test_guards_return_empty_without_provider(
    op: SemanticTransformOperator,
    input_data: list[list[dict[str, Any]]],
    attrs: dict[str, Any],
) -> None:
    assert op.apply(input_data, attrs) == []
    assert litellm.calls == []


def test_simple_rename_strategy_uses_only_plan_call(
    op: SemanticTransformOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider(
        '{"person": {"source_fields": ["name"], "transformation_type": '
        '"field_mapping_without_value_change"}, "label": {"source_fields": '
        '["score"], "transformation_type": "field_mapping_without_value_change"}}',
        monkeypatch,
    )
    assert op.apply(
        DATA,
        {
            "output_desc": {
                "person": {"description": "Copied name"},
                "label": {"description": "Copied score"},
            }
        },
    ) == [
        [
            {"person": "Ada", "label": 1},
            {"person": "Bob", "label": 2},
            {"person": "Cid", "label": 2},
        ]
    ]
    assert len(litellm.calls) == 1
    assert "You are a data transformation planner" in litellm.calls[0]["messages"][0]["content"]


def test_per_record_strategy_parses_each_model_object(
    op: SemanticTransformOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider(
        [
            '{"person": {"source_fields": ["name"], "transformation_type": '
            '"field_mapping_without_value_change"}, "label": {"source_fields": '
            '["score"], "transformation_type": "field_mapping_with_value_change"}}',
            '{"label": "low"}',
            '{"label": "medium"}',
            '{"label": "medium"}',
        ],
        monkeypatch,
    )
    assert op.apply(
        DATA,
        {
            "output_desc": {
                "person": {"description": "Copied name"},
                "label": {"description": "Score label"},
            },
            "strategy": "per_record",
        },
    ) == [
        [
            {"person": "Ada", "label": "low"},
            {"person": "Bob", "label": "medium"},
            {"person": "Cid", "label": "medium"},
        ]
    ]
    assert len(litellm.calls) == 4
    execution_prompt = litellm.calls[1]["messages"][0]["content"]
    assert "- label: Score label (from score, field_mapping_with_value_change)" in (
        execution_prompt
    )
    assert "## Input Data Record\n{'name': 'Ada', 'city': 'NY', 'score': 1}" in (execution_prompt)


def test_auto_dispatch_selects_distinct_values_on_lower_cost(
    op: SemanticTransformOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider(
        [
            '{"label": {"source_fields": ["city"], "transformation_type": '
            '"field_mapping_with_value_change"}}',
            '{"label": "west"}',
            '{"label": "east"}',
        ],
        monkeypatch,
    )
    output = op.apply(
        DATA,
        {"output_desc": {"label": {"description": "City label"}}},
    )
    # One plan + two distinct city values, not one execution per record.
    assert len(litellm.calls) == 3
    labels = [record["label"] for record in output[0]]
    assert labels[0] == labels[1]
    assert set(labels) == {"east", "west"}


def test_distinct_values_keeps_results_separate_per_target_field(
    op: SemanticTransformOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The reference implementation keys only by ("NY",), so the second field
    # overwrites the first and both output "NE". The port uses (target, values).
    _json_provider(
        [
            '{"city_label": {"source_fields": ["city"], "transformation_type": '
            '"field_mapping_with_value_change"}, "region": {"source_fields": '
            '["city"], "transformation_type": "field_mapping_with_value_change"}}',
            '{"city_label": "east"}',
            '{"region": "NE"}',
        ],
        monkeypatch,
    )
    assert op.apply(
        [[{"city": "NY"}, {"city": "NY"}]],
        {
            "output_desc": {
                "city_label": {"description": "City label"},
                "region": {"description": "Region"},
            },
            "strategy": "distinct_required_values",
        },
    ) == [
        [
            {"city_label": "east", "region": "NE"},
            {"city_label": "east", "region": "NE"},
        ]
    ]


def test_merged_fields_applies_results_with_group_dependencies(
    op: SemanticTransformOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The reference implementation, after building the group for [city, score],
    # reuses the final target's [city] list for lookup and silently drops the result.
    _json_provider(
        [
            '{"city_label": {"source_fields": ["city"], "transformation_type": '
            '"field_mapping_with_value_change"}, "combo": {"source_fields": '
            '["city", "score"], "transformation_type": '
            '"field_mapping_with_value_change"}}',
            '{"combo": "NY-1", "city_label": "east"}',
        ],
        monkeypatch,
    )
    assert op.apply(
        [[{"city": "NY", "score": 1}]],
        {
            "output_desc": {
                "city_label": {"description": "City label"},
                "combo": {"description": "City-score pair"},
            },
            "strategy": "distinct_required_values_with_merged_fields",
        },
    ) == [[{"combo": "NY-1", "city_label": "east"}]]
    assert len(litellm.calls) == 2


def test_invalid_forced_strategy_falls_back_to_per_record(
    op: SemanticTransformOperator,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _json_provider(
        [
            '{"label": {"source_fields": ["score"], "transformation_type": '
            '"field_mapping_with_value_change"}}',
            '{"label": "low"}',
        ],
        monkeypatch,
    )
    assert op.apply(
        [[{"score": 1}]],
        {
            "output_desc": {"label": {"description": "Label"}},
            "strategy": "bogus",
        },
    ) == [[{"label": "low"}]]
    assert "Invalid strategy 'bogus', falling back to 'per_record'" in capsys.readouterr().out


def test_plan_prompt_includes_input_metadata_and_mutates_nested_output_desc(
    op: SemanticTransformOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider(
        '{"label": {"source_fields": ["score"], "transformation_type": '
        '"field_mapping_without_value_change"}}',
        monkeypatch,
    )
    output_desc = {"label": {"description": "Score", "required": True}}
    assert op.apply(
        [[{"score": 8}]],
        {
            "input_meta": {
                "score": {
                    "description": "Raw score",
                    "type": "int",
                    "hints": "0-10",
                }
            },
            "output_desc": output_desc,
        },
    ) == [[{"label": 8}]]
    prompt = litellm.calls[0]["messages"][0]["content"]
    assert "- score: Raw score (type: int)" in prompt
    assert "- score: Raw score (type: int) (hints: 0-10)" in prompt
    assert "- label: Score (required: True)" in prompt
    # Blue uses output_desc.copy(), then updates nested dictionaries in place.
    assert output_desc["label"]["source_fields"] == ["score"]


def test_auto_unclassified_plan_field_uses_empty_simple_rename(
    op: SemanticTransformOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider(
        '{"optional": {"source_fields": [], "transformation_type": "other"}}',
        monkeypatch,
    )
    assert op.apply(
        [[{"x": 1}]],
        {"output_desc": {"optional": {"description": "Optional"}}},
    ) == [[{}]]


def test_forced_per_record_sets_unclassified_plan_field_to_none(
    op: SemanticTransformOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider(
        '{"optional": {"source_fields": [], "transformation_type": "other"}}',
        monkeypatch,
    )
    assert op.apply(
        [[{"x": 1}]],
        {
            "output_desc": {"optional": {"description": "Optional"}},
            "strategy": "per_record",
        },
    ) == [[{"optional": None}]]


def test_later_empty_group_is_preserved(
    op: SemanticTransformOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider(
        '{"name": {"source_fields": ["name"], "transformation_type": '
        '"field_mapping_without_value_change"}}',
        monkeypatch,
    )
    assert op.apply(
        [[{"name": "Ada"}], []],
        {"output_desc": {"name": {"description": "Name"}}},
    ) == [[{"name": "Ada"}], []]


def test_provider_error_propagates(op: SemanticTransformOperator) -> None:
    litellm.fail_next.extend([RuntimeError("down")] * 3)
    with pytest.raises(LLMError):
        op.apply(DATA, {"output_desc": {"label": {"description": "Label"}}})


@pytest.mark.parametrize(
    "attrs,expected",
    [
        ({"output_desc": {"x": {"description": "X"}}}, True),
        ({}, False),
        ({"output_desc": {}}, False),
        ({"output_desc": []}, False),
        ({"output_desc": {1: {"description": "X"}}}, False),
        ({"output_desc": {"x": "X"}}, False),
        ({"output_desc": {"x": {}}}, False),
        ({"output_desc": {"x": {"description": 1}}}, False),
        ({"output_desc": {"x": {"description": "X"}}, "strategy": b"auto"}, True),
        ({"output_desc": {"x": {"description": "X"}}, "input_meta": []}, False),
    ],
)
def test_validator(op: SemanticTransformOperator, attrs: dict[str, Any], expected: bool) -> None:
    assert op.validate(DATA, attrs) is expected


def test_prompt_templates_and_defaults_are_pinned() -> None:
    assert (
        hashlib.sha256(SemanticTransformOperator.PLAN_RESOLUTION_PROMPT.encode()).hexdigest()
        == "742634bf42a3a57b8ed0742e99f6406f71058693a839dc3ac0771bbca101cdf7"
    )
    assert hashlib.sha256(SemanticTransformOperator.TRANSFORM_PROMPT.encode()).hexdigest() == (
        "87656cfde6854ed87b8473ea8c0d2b947ec7e803d6c639cffb80b102cd3c4a15"
    )
    assert SemanticTransformOperator.DEFAULT_PROPERTIES == {
        "openai.api": "ChatCompletion",
        "openai.model": "gpt-4o",
        "openai.stream": False,
        "openai.max_tokens": 1024,
        "openai.temperature": 0.0,
        "input_json": '[{"role": "user"}]',
        "input_context": "$[0]",
        "input_context_field": "content",
        "input_field": "messages",
        "input_template": SemanticTransformOperator.TRANSFORM_PROMPT,
        "output_path": "$.choices[0].message.content",
        "service_prefix": "openai",
        "output_transformations": [
            {"transformation": "replace", "from": "```", "to": ""},
            {"transformation": "replace", "from": "json", "to": ""},
        ],
        "output_strip": True,
        "output_cast": "json",
    }


def test_interface_exact(op: SemanticTransformOperator) -> None:
    assert op.name == "semantic_transform"
    assert op.description == (
        "Transforms data into target fields and values using LLM-based transformations"
    )
    expected: dict[str, tuple[str, str, bool, Any]] = {
        "input_meta": ("dict", "Optional metadata about input fields", False, {}),
        "output_desc": (
            "dict",
            "Required description of target fields to create",
            True,
            None,
        ),
        "strategy": (
            "str",
            "Execution strategy: 'auto' (automatic cost-based selection), 'per_record' "
            "(one LLM call per record), 'distinct_required_values' (deduplicate by "
            "distinct values), 'distinct_required_values_with_merged_fields' (merged "
            "distinct optimization).",
            False,
            "auto",
        ),
    }
    assert set(op.attributes) == set(expected)
    for name, values in expected.items():
        spec = op.attributes[name]
        assert (spec.type, spec.description, spec.required, spec.default) == values

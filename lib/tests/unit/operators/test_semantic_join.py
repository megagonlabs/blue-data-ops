from __future__ import annotations

import hashlib
from typing import Any

import litellm
import pytest
from sentence_transformers import SentenceTransformer

from blue_data_ops.llm import LLMClient, LLMError
from blue_data_ops.operators import semantic_join_operator as join_module
from blue_data_ops.operators.semantic_join_operator import SemanticJoinOperator
from tests.unit.operators._semantic_test_helpers import (
    json_provider as _json_provider,
)
from tests.unit.operators._semantic_test_helpers import (
    reset_litellm,
)

LEFT = [{"id": 1, "name": "Ada"}, {"id": 2, "name": "Bob"}]
RIGHT = [{"id": "a", "name": "ADA"}, {"id": "b", "name": "Cid"}]
ATTRS: dict[str, Any] = {
    "left_fields": ["name"],
    "right_fields": ["name"],
    "join_predicate": "names refer to the same person",
    "estimate_cost": False,
}


class RecordingClient(LLMClient):
    def __init__(self, responses: list[Any]):
        super().__init__("recording", {})
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def execute_api_call(
        self,
        input: Any,
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
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def _reset_fake(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    reset_litellm()
    SentenceTransformer.reset()
    monkeypatch.setattr(join_module, "_sentence_transformer", None)


@pytest.fixture
def op() -> SemanticJoinOperator:
    return SemanticJoinOperator()


@pytest.mark.parametrize(
    "input_data",
    [[], [LEFT]],
)
def test_input_arity_guards_return_empty_without_provider(
    op: SemanticJoinOperator, input_data: list[list[dict[str, Any]]]
) -> None:
    assert op.apply(input_data, ATTRS) == []
    assert litellm.calls == []


def test_join_suffix_length_guard_runs_without_provider(op: SemanticJoinOperator) -> None:
    assert op.apply([LEFT, RIGHT], {**ATTRS, "join_suffix": ["_only"]}) == []
    assert litellm.calls == []


def test_inner_join_batches_in_pair_order(
    op: SemanticJoinOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider(
        [
            '{"pair_1": "match", "pair_2": false, "pair_3": 1}',
            '{"pair_1": 0}',
        ],
        monkeypatch,
    )
    assert op.apply(
        [LEFT, RIGHT],
        {**ATTRS, "join_type": "inner", "keep_keys": "both", "batch_size": 3},
    ) == [
        [
            {"id_left": 1, "name_left": "Ada", "id_right": "a", "name_right": "ADA"},
            {"id_left": 2, "name_left": "Bob", "id_right": "a", "name_right": "ADA"},
        ]
    ]
    assert len(litellm.calls) == 2
    prompt = litellm.calls[0]["messages"][0]["content"]
    assert prompt.index("Left Record (index 0)") < prompt.index("Left Record (index 1)")
    assert "Pair 3:" in prompt and "pair_1 through pair_3" in prompt


def test_left_join_list_result_and_keep_left_keys(
    op: SemanticJoinOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider("[true, false, false, false]", monkeypatch)
    assert op.apply([LEFT, RIGHT], {**ATTRS, "join_type": "left", "batch_size": 4}) == [
        [
            {"id_left": 1, "name": "Ada", "id_right": "a"},
            {"id_left": 2, "name": "Bob"},
        ]
    ]


def test_right_join_parses_fenced_batch_object(
    op: SemanticJoinOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider(
        '```json\n{"pair_1": false, "pair_2": false, "pair_3": true, "pair_4": false}\n```',
        monkeypatch,
    )
    assert op.apply([LEFT, RIGHT], {**ATTRS, "join_type": "right", "keep_keys": "both"}) == [
        [
            {"id_left": 2, "name_left": "Bob", "id_right": "a", "name_right": "ADA"},
            {"id_right": "b", "name_right": "Cid"},
        ]
    ]


def test_outer_join_missing_pair_keys_default_false(
    op: SemanticJoinOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider('{"pair_2": true}', monkeypatch)
    assert op.apply([LEFT, RIGHT], {**ATTRS, "join_type": "outer", "keep_keys": "both"}) == [
        [
            {"id_left": 1, "name_left": "Ada", "id_right": "b", "name_right": "Cid"},
            {"id_left": 2, "name_left": "Bob"},
            {"id_right": "a", "name_right": "ADA"},
        ]
    ]


def test_default_predicate_and_all_fields_reach_batch_prompt(
    op: SemanticJoinOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider('{"pair_1": false}', monkeypatch)
    assert op.apply(
        [[{"a": 1}], [{"b": 2}]],
        {
            "left_fields": [],
            "right_fields": [],
            "estimate_cost": False,
        },
    ) == [[]]
    prompt = litellm.calls[0]["messages"][0]["content"]
    assert (
        "Determine if the two records are semantically equivalent based on the provided fields."
        in prompt
    )
    assert 'Left Record (index 0): {"a": 1}' in prompt
    assert 'Right Record (index 0): {"b": 2}' in prompt


def test_batch_properties_copy_drops_cast_without_mutating_caller(
    op: SemanticJoinOperator,
) -> None:
    client = RecordingClient([{"pair_1": True}])
    caller_properties: dict[str, Any] = {
        "llm_client": client,
        "output_cast": "bool",
        "sentinel": "keep",
    }
    before = caller_properties.copy()
    assert op.apply(
        [[{"a": 1}], [{"b": 2}]],
        {"left_fields": [], "right_fields": [], "estimate_cost": False},
        caller_properties,
    ) == [[{"a": 1}]]
    assert caller_properties == before
    call_properties = client.calls[0]["properties"]
    assert call_properties is not None
    assert "output_cast" not in call_properties
    assert call_properties["input_template"] == SemanticJoinOperator.BATCH_JOIN_PROMPT
    assert call_properties["sentinel"] == "keep"
    assert SemanticJoinOperator.DEFAULT_PROPERTIES["output_cast"] == "bool"


def test_cache_reuses_identical_pair_across_batches(op: SemanticJoinOperator) -> None:
    client = RecordingClient([{"pair_1": True}])
    output = op.apply(
        [[{"name": "same"}, {"name": "same"}], [{"name": "same"}]],
        {
            "left_fields": ["name"],
            "right_fields": ["name"],
            "batch_size": 1,
            "estimate_cost": False,
        },
        {"llm_client": client},
    )
    assert output == [[{"name": "same"}, {"name": "same"}]]
    assert len(client.calls) == 1


def test_cost_limit_aborts_before_client_construction(op: SemanticJoinOperator) -> None:
    with pytest.raises(ValueError) as exc_info:
        op.apply(
            [LEFT, RIGHT],
            {
                **ATTRS,
                "estimate_cost": True,
                "batch_size": 1,
                "max_llm_calls": 3,
            },
        )
    assert str(exc_info.value) == (
        "Semantic join aborted: 4 LLM calls exceeds limit of 3. Dataset: 2 × 2 = 4 "
        "pairs. Estimated cost: ~$0.08"
    )
    assert litellm.calls == []


def test_embedding_filter_uses_deterministic_stub_and_math_path(
    op: SemanticJoinOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json_provider('{"pair_1": true}', monkeypatch)
    assert op.apply(
        [[{"name": "Ada"}], [{"name": "ADA"}]],
        {
            **ATTRS,
            "use_embedding_filter": True,
            "embedding_threshold": -2.0,
        },
    ) == [[{"name": "Ada"}]]
    assert SentenceTransformer.model_names == ["paraphrase-MiniLM-L6-v2"]
    assert [call.sentences for call in SentenceTransformer.encode_calls] == [
        ("name: Ada",),
        ("name: ADA",),
    ]
    assert all(call.batch_size == 32 for call in SentenceTransformer.encode_calls)
    assert all(call.show_progress_bar is False for call in SentenceTransformer.encode_calls)


def test_embedding_filter_can_reject_all_without_llm(op: SemanticJoinOperator) -> None:
    assert op.apply(
        [[{"name": "Ada"}], [{"name": "Cid"}]],
        {
            **ATTRS,
            "use_embedding_filter": True,
            "embedding_threshold": 2.0,
        },
    ) == [[]]
    assert litellm.calls == []


def test_numeric_helpers_are_blue_pinned() -> None:
    np = pytest.importorskip("numpy")
    left = np.array([[1.0, 0.0], [0.0, 0.0]])
    right = np.array([[1.0, 0.0], [-1.0, 0.0]])
    similarity = join_module._compute_cosine_similarity_matrix(  # pyright: ignore[reportPrivateUsage]
        left, right
    )
    assert similarity.tolist() == [[1.0, -1.0], [0.0, 0.0]]
    assert join_module._filter_pairs_by_similarity(  # pyright: ignore[reportPrivateUsage]
        similarity, 0.5
    ) == [(0, 0), (1, 0), (1, 1)]
    indices, corrections = join_module._importance_sampling(  # pyright: ignore[reportPrivateUsage]
        [0.0, 0.1, 0.2, 0.3, 0.4], 1.0
    )
    assert indices == [2, 4, 3, 1, 0]
    assert corrections.tolist() == pytest.approx(
        [0.9300310055612874, 0.7613233908623362, 0.830210614091401, 1.1028384337476413, 2.0]
    )


def test_provider_error_propagates(op: SemanticJoinOperator) -> None:
    litellm.fail_next.extend([RuntimeError("down")] * 3)
    with pytest.raises(LLMError):
        op.apply([LEFT, RIGHT], ATTRS)


@pytest.mark.parametrize(
    "attrs,expected",
    [
        (ATTRS, True),
        ({"left_fields": [], "right_fields": []}, True),
        ({"left_fields": [], "right_fields": [], "join_predicate": 1}, False),
        ({"left_fields": [], "right_fields": [], "join_type": "cross"}, False),
        ({"left_fields": None, "right_fields": []}, False),
        ({"left_fields": ("name",), "right_fields": []}, False),
        ({"left_fields": [1], "right_fields": []}, False),
        ({"left_fields": [], "right_fields": [], "left_suffix": 1}, False),
        ({"left_fields": [], "right_fields": [], "left_suffix": 0}, False),
        ({"left_fields": [], "right_fields": [], "keep_keys": "right"}, False),
        ({"left_fields": [], "right_fields": [], "batch_size": "2"}, True),
        ({"left_fields": [], "right_fields": [], "embedding_threshold": "0.5"}, True),
        ({"left_fields": [], "right_fields": [], "max_llm_calls": None}, False),
    ],
)
def test_validator(op: SemanticJoinOperator, attrs: dict[str, Any], expected: bool) -> None:
    assert op.validate([LEFT, RIGHT], attrs) is expected


def test_prompt_templates_and_defaults_are_pinned() -> None:
    assert hashlib.sha256(SemanticJoinOperator.JOIN_PROMPT.encode()).hexdigest() == (
        "befe836eea07275f242a00ebbdb1cdca79d21a7a676379aa82a9a320939aa032"
    )
    assert hashlib.sha256(SemanticJoinOperator.BATCH_JOIN_PROMPT.encode()).hexdigest() == (
        "06610947b374a0426bbfb5e1e011aa128a446f64ce0bbc8b1c5a4c15033d0252"
    )
    assert SemanticJoinOperator.DEFAULT_PROPERTIES == {
        "openai.api": "ChatCompletion",
        "openai.model": "gpt-4o",
        "openai.stream": False,
        "openai.max_tokens": 1024,
        "openai.temperature": 0,
        "input_json": '[{"role": "user"}]',
        "input_context": "$[0]",
        "input_context_field": "content",
        "input_field": "messages",
        "input_template": SemanticJoinOperator.JOIN_PROMPT,
        "output_path": "$.choices[0].message.content",
        "service_prefix": "openai",
        "output_transformations": [
            {"transformation": "replace", "from": "```", "to": ""},
            {"transformation": "replace", "from": "json", "to": ""},
        ],
        "output_strip": True,
        "output_cast": "bool",
    }


def test_interface_exact(op: SemanticJoinOperator) -> None:
    assert op.name == "semantic_join"
    assert op.description == (
        "Joins two datasets based on natural language join predicate using LLM models"
    )
    expected: dict[str, tuple[str, str, bool, Any]] = {
        "left_fields": ("list[str]", "Fields from left dataset to consider", True, None),
        "right_fields": ("list[str]", "Fields from right dataset to consider", True, None),
        "join_predicate": (
            "str",
            "Natural language description of when records should be joined",
            False,
            "",
        ),
        "join_type": (
            "str",
            "Type of join: 'inner', 'left', 'right', 'outer'",
            False,
            "inner",
        ),
        "left_suffix": (
            "str",
            "Suffix for field name conflicts from left dataset",
            False,
            "_left",
        ),
        "right_suffix": (
            "str",
            "Suffix for field name conflicts from right dataset",
            False,
            "_right",
        ),
        "keep_keys": (
            "str",
            "'left' to keep left keys only, 'both' to keep both",
            False,
            "left",
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
        "batch_size": (
            "int",
            "Number of record pairs to evaluate per LLM call (batch processing)",
            False,
            10,
        ),
        "use_cache": (
            "bool",
            "Enable result caching to avoid re-evaluating similar pairs",
            False,
            True,
        ),
        "use_embedding_filter": (
            "bool",
            "Use embedding pre-filtering to reduce candidate pairs (requires "
            "sentence-transformers package)",
            False,
            False,
        ),
        "embedding_threshold": (
            "float",
            "Similarity threshold for embedding pre-filtering (0.0-1.0, maps to cosine "
            "similarity [-1,1])",
            False,
            0.7,
        ),
        "max_llm_calls": (
            "int",
            "Maximum allowed LLM calls (None = no limit). Prevents accidental expensive "
            "operations.",
            False,
            1000,
        ),
        "estimate_cost": (
            "bool",
            "Show cost estimate and warnings before execution",
            False,
            True,
        ),
        "optimize_thresholds": (
            "bool",
            "Enable dynamic threshold learning (Cascade Optimization)",
            False,
            False,
        ),
        "recall_target": (
            "float",
            "Target recall for optimization (0.0-1.0)",
            False,
            0.8,
        ),
        "precision_target": (
            "float",
            "Target precision for auto-acceptance (0.0-1.0)",
            False,
            0.8,
        ),
        "sampling_percentage": (
            "float",
            "Fraction of data to sample for learning (0.0-1.0)",
            False,
            0.1,
        ),
        "failure_probability": (
            "float",
            "Statistical failure probability (delta) for threshold learning",
            False,
            0.2,
        ),
    }
    assert set(op.attributes) == set(expected)
    for name, values in expected.items():
        spec = op.attributes[name]
        assert (spec.type, spec.description, spec.required, spec.default) == values

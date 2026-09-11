from __future__ import annotations

from typing import Any

import pytest

from blue_data_ops.operators import _vector_embed_outcome as embed_module
from blue_data_ops.operators import _vector_similarity_outcome as similarity_module
from blue_data_ops.operators.registry import versioned_registry


class RecordingEmbedder:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], int, bool]] = []

    def encode(
        self,
        sentences: list[str],
        batch_size: int = 32,
        normalize_embeddings: bool = False,
    ) -> list[list[float]]:
        self.calls.append((list(sentences), batch_size, normalize_embeddings))
        return [[float(len(sentence)), 2.0] for sentence in sentences]


def test_vector_embed_processes_a_later_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embedder = RecordingEmbedder()
    constructor_calls: list[str] = []

    def constructor(model_ref: str) -> RecordingEmbedder:
        constructor_calls.append(model_ref)
        return embedder

    monkeypatch.setattr(embed_module, "_embedder_constructor", lambda: constructor)
    operator = versioned_registry().resolve("vector_embed@3.0.0")
    output_data, output_attributes, meta = operator.run(
        [
            [],
            [{"id": "later", "caption": "cobalt"}],
            [{"id": "final", "caption": "gold"}],
            [],
        ],
        {"text_field": ["caption"], "append": True},
    )

    assert output_data == [
        [],
        [{"id": "later", "caption": "cobalt", "embedding": [6.0, 2.0]}],
        [{"id": "final", "caption": "gold", "embedding": [4.0, 2.0]}],
        [],
    ]
    assert output_attributes == {}
    assert meta.errors == []
    assert meta.is_empty is False
    assert constructor_calls == ["all-MiniLM-L6-v2"]
    assert embedder.calls == [(["cobalt"], 32, False), (["gold"], 32, False)]


def test_vector_search_declared_attribute_top_k_changes_the_result() -> None:
    candidates = [
        {"id": "a", "embedding": [2.0, 0.0], "embed.model": "all-MiniLM-L6-v2"},
        {"id": "b", "embedding": [1.0, 0.0], "embed.model": "all-MiniLM-L6-v2"},
        {"id": "c", "embedding": [0.0, 1.0], "embed.model": "all-MiniLM-L6-v2"},
    ]
    attributes = {
        "query": {"embedding": [1.0, 0.0], "model": "all-MiniLM-L6-v2"},
        "metric": "dot",
        "top_k": 1,
    }

    output_data, output_attributes, meta = (
        versioned_registry().resolve("vector_search@3.0.0").run([candidates], attributes)
    )
    old_output_data, _, old_meta = (
        versioned_registry().resolve("vector_search@2.0.0").run([candidates], attributes)
    )

    assert [record["id"] for record in output_data[0]] == ["a"]
    assert [record["search.score"] for record in output_data[0]] == [2.0]
    assert [record["search.rank"] for record in output_data[0]] == [1]
    assert output_attributes == {}
    assert meta.errors == []
    assert meta.is_empty is False
    assert [record["id"] for record in old_output_data[0]] == ["a", "b", "c"]
    assert old_meta.errors == []


def test_vector_search_properties_override_declared_attribute_controls() -> None:
    operator = versioned_registry().resolve("vector_search@3.0.0")
    candidates = [
        {"id": "a", "embedding": [2.0, 0.0], "embed.model": "all-MiniLM-L6-v2"},
        {"id": "b", "embedding": [1.0, 0.0], "embed.model": "all-MiniLM-L6-v2"},
        {"id": "c", "embedding": [0.0, 1.0], "embed.model": "all-MiniLM-L6-v2"},
    ]
    output_data, output_attributes, meta = operator.run(
        [candidates],
        {
            "query": {"embedding": [1.0, 0.0], "model": "all-MiniLM-L6-v2"},
            "metric": "dot",
            "top_k": 1,
        },
        {"top_k": 3},
    )

    assert [record["id"] for record in output_data[0]] == ["a", "b", "c"]
    assert [record["search.score"] for record in output_data[0]] == [2.0, 1.0, 0.0]
    assert [record["search.rank"] for record in output_data[0]] == [1, 2, 3]
    assert output_attributes == {}
    assert meta.errors == []
    assert meta.is_empty is False


def test_vector_similarity_zero_cartesian_pairs_skip_optional_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imports: list[str] = []

    def unexpected_import(name: str) -> Any:
        imports.append(name)
        raise AssertionError(f"unexpected optional dependency import: {name}")

    monkeypatch.setattr(similarity_module, "import_module", unexpected_import)
    operator = versioned_registry().resolve("vector_similarity@3.0.0")
    output_data, output_attributes, meta = operator.run(
        [[], [{"id": "right", "embedding": [1.0]}]],
        {"comparison_mode": "cartesian"},
    )

    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.errors == []
    assert meta.is_empty is True
    assert imports == []

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import NoReturn

import pytest

import blue_data_ops.operators.classify_operator as classify_module
import blue_data_ops.operators.cluster_operator as cluster_module
import blue_data_ops.operators.vector_embed_operator as embed_module
import blue_data_ops.operators.vector_search_operator as search_module
import blue_data_ops.operators.vector_similarity_operator as similarity_module
from blue_data_ops.operators import (
    ClassifyOperator,
    ClusterOperator,
    VectorEmbedOperator,
    VectorSearchOperator,
    VectorSimilarityOperator,
)

LIB_DIR = Path(__file__).resolve().parents[3]


def test_optional_dependency_extras_match_binding_spec() -> None:
    manifest = (LIB_DIR / "pyproject.toml").read_text(encoding="utf-8")
    assert 'ml = ["numpy", "scikit-learn"]' in manifest
    assert 'vector = ["numpy", "sentence-transformers"]' in manifest
    dev_block = manifest.split("dev = [", 1)[1].split("]", 1)[0]
    assert '"numpy"' in dev_block
    assert '"scikit-learn"' in dev_block
    assert '"sentence-transformers"' not in dev_block


def test_sentence_transformers_resolves_to_deterministic_test_stub() -> None:
    module = sys.modules.get("sentence_transformers")
    assert isinstance(module, ModuleType)
    module_file = getattr(module, "__file__", None)
    assert module_file is not None
    assert (
        Path(module_file).resolve()
        == (LIB_DIR / "tests" / "stubs" / "sentence_transformers" / "__init__.py").resolve()
    )


def _missing_dependency(_name: str) -> NoReturn:
    raise ImportError("simulated optional backend absence")


def test_guard_paths_do_not_resolve_optional_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(classify_module, "import_module", _missing_dependency)
    monkeypatch.setattr(cluster_module, "import_module", _missing_dependency)
    monkeypatch.setattr(embed_module, "import_module", _missing_dependency)
    monkeypatch.setattr(search_module, "import_module", _missing_dependency)
    monkeypatch.setattr(similarity_module, "import_module", _missing_dependency)

    classify_input: list[list[dict[str, object]]] = []
    assert (
        ClassifyOperator().apply(classify_input, {"vector_key": "vector", "label_key": "label"})
        is classify_input
    )
    assert ClusterOperator().apply([], {"vector_key": "vector", "n_cluster": 2}) == [[]]
    assert VectorEmbedOperator().apply([], {}) == [[]]
    assert VectorSearchOperator().apply([], {"query": "alpha"}) == []
    with pytest.raises(ValueError, match="exactly two input lists"):
        VectorSimilarityOperator().apply([[]], {})


def test_reached_heavy_paths_propagate_natural_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(classify_module, "import_module", _missing_dependency)
    with pytest.raises(ImportError, match="simulated optional backend absence"):
        ClassifyOperator().apply(
            [[{"vector": [0.0], "label": "a"}]],
            {"vector_key": "vector", "label_key": "label"},
        )

    monkeypatch.setattr(cluster_module, "import_module", _missing_dependency)
    with pytest.raises(ImportError, match="simulated optional backend absence"):
        ClusterOperator().apply(
            [[{"vector": [0.0]}]],
            {"vector_key": "vector", "n_cluster": 1},
        )

    monkeypatch.setattr(embed_module, "import_module", _missing_dependency)
    with pytest.raises(ImportError, match="simulated optional backend absence"):
        VectorEmbedOperator().apply([[{"text": "alpha"}]], {"text_field": ["text"]})

    monkeypatch.setattr(search_module, "import_module", _missing_dependency)
    with pytest.raises(ImportError, match="simulated optional backend absence"):
        VectorSearchOperator().apply(
            [[{"embedding": [1.0], "embed.model": "m"}]],
            {"query": {"embedding": [1.0], "model": "m"}},
        )

    monkeypatch.setattr(similarity_module, "import_module", _missing_dependency)
    with pytest.raises(ImportError, match="simulated optional backend absence"):
        VectorSimilarityOperator().apply(
            [[{"embedding": [1.0]}], [{"embedding": [1.0]}]],
            {},
        )

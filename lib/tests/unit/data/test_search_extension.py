"""The seam's search extension against REAL blue-data.

Pins the two delegate result shapes (wrapped keyword fallback, flat hybrid), the
score inversion and derived-id rules, the dropped approximate/hybrid parameters,
and the two upstream behaviors consumers must know: the hybrid hierarchical
engine crash (its type parameter shadows the builtin) and the empty flat result
under default thresholds when vector scores are zero.
"""

# blue-data ships no py.typed:
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import inspect
from typing import Any, cast

import pytest

blue_data = pytest.importorskip("blue_data")

from blue_data.registry.data_registry import DataRegistry  # noqa: E402
from blue_data.source.vector.memory_vector_source import MemoryVectorSource  # noqa: E402

from blue_data_ops.data import RegistrySeam  # noqa: E402
from blue_data_ops.data.registry_seam import (  # noqa: E402
    _normalize_search_result,  # pyright: ignore[reportPrivateUsage]
)


def _stub_embedding(texts: list[str]) -> list[list[float]]:
    return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


def _keyword_registry() -> RegistrySeam:
    # No vector source: hierarchical search takes the keyword fallback path.
    registry: Any = DataRegistry(name="kw_probe", rebuild=True)
    registry.register_record("jobs_db", "source", "/", description="job postings database")
    registry.register_record("jobs_kb", "source", "/", description="jobs knowledge")
    registry.register_record("other", "source", "/", description="unrelated")
    return RegistrySeam(registry)


# --- the wrapped keyword variant, normalized end-to-end -------------------------- #
def test_keyword_fallback_normalized_shape_and_order() -> None:
    seam = _keyword_registry()
    results = seam.search_records_hierarchical("jobs", type="source", page=0, page_size=10)
    # jobs_kb hits name AND description (15 => 0.0); jobs_db name only (10 => 1/3);
    # the non-match is absent entirely. Ascending (lower = better) order preserved
    # from the delegate's descending ints.
    assert [(r["name"], r["score"]) for r in results] == [
        ("jobs_kb", pytest.approx(0.0)),
        ("jobs_db", pytest.approx(1.0 / 3.0)),
    ]
    for r in results:
        assert set(r) == {"name", "type", "scope", "id", "score", "description"}
        assert r["id"] == f"//source/{r['name']}"  # "{scope}/{type}/{name}" with scope "/"


def test_keyword_scoring_tiers_invert_monotonically() -> None:
    # name+description (15) beats name-only (10) beats description-only (5) after
    # inversion: 0.0 < 1/3 < 2/3.
    registry: Any = DataRegistry(name="kw_tiers", rebuild=True)
    registry.register_record("alpha jobs", "source", "/", description="has jobs too")  # 15
    registry.register_record("jobs_beta", "source", "/", description="nothing")  # 10
    registry.register_record("gamma", "source", "/", description="jobs inside")  # 5
    seam = RegistrySeam(registry)
    results = seam.search_records_hierarchical("jobs", type="source", page=0, page_size=10)
    scores = [r["score"] for r in results]
    assert scores == pytest.approx([0.0, 1.0 / 3.0, 2.0 / 3.0])
    assert [r["name"] for r in results] == ["alpha jobs", "jobs_beta", "gamma"]


# --- the flat variant normalization (unit: the delegate shape observed live) ----- #
def test_flat_variant_normalization_unit() -> None:
    raw = {
        "name": "jobs_db",
        "type": "source",
        "scope": "/",
        "description": "job postings",
        "_score": 0.75,
        "_most_relevant_values": ["x"],
    }
    normalized = _normalize_search_result(raw)
    assert normalized == {
        "name": "jobs_db",
        "type": "source",
        "scope": "/",
        "id": "//source/jobs_db",
        "score": pytest.approx(0.25),  # 1 - _score
        "description": "job postings",
    }


def test_flat_variant_missing_score_counts_worst() -> None:
    normalized = _normalize_search_result({"name": "x", "type": "source", "scope": "/"})
    assert normalized["score"] == 1.0


# --- dropped parameters + signature pins ----------------------------------------- #
def test_search_records_drops_approximate_hybrid() -> None:
    class _Recorder:
        def __init__(self) -> None:
            self.kwargs: dict[str, Any] = {}

        def search_records(self, query: Any, **kwargs: Any) -> list[dict[str, Any]]:
            self.kwargs = {"input_query": query, **kwargs}
            return []

    recorder = _Recorder()
    seam = RegistrySeam(cast(Any, recorder))
    seam.search_records(
        "q", type="source", scope="/", approximate=True, hybrid=True, page=1, page_size=3
    )
    assert recorder.kwargs == {
        "input_query": "q",
        "type": "source",
        "scope": "/",
        "page": 1,
        "page_size": 3,
    }


def test_blue_data_search_signature_pins() -> None:
    # The wrapped registry has NO approximate/hybrid parameters; if upstream adds
    # them, the facade's drop-translation must be revisited.
    for method_name in ("search_records", "search_records_hierarchical"):
        method: Any = getattr(DataRegistry, method_name)
        parameters = list(inspect.signature(method).parameters)
        assert "approximate" not in parameters
        assert "hybrid" not in parameters
        assert parameters[1:6] == ["input_query", "type", "scope", "page", "page_size"]


# --- the two upstream behaviors, pinned live ------------------------------------- #
def test_vector_hierarchical_engine_crash_pinned() -> None:
    # The wrapped registry's hybrid hierarchical engine shadows the type() builtin
    # with its own parameter and crashes on the first record for ANY call (verified
    # on this checkout). The facade does not paper over an engine defect one layer
    # down; consumers reach it only through the discover operator's swallow.
    registry: Any = DataRegistry(
        name="crash_probe",
        rebuild=True,
        vector_source=MemoryVectorSource("v"),
        embedding_fn=_stub_embedding,
        vector_dim=4,
    )
    registry.register_record("jobs_db", "source", "/", description="job postings")
    seam = RegistrySeam(registry)
    with pytest.raises(TypeError, match="object is not callable"):
        seam.search_records_hierarchical("jobs", type="source", page=0, page_size=10)


def test_flat_search_empty_under_default_thresholds() -> None:
    # Default engine thresholds (vector_threshold 0.5) filter every record whose
    # vector score is 0 — a no-vector registry's flat search is empty even on an
    # exact name match. Pinned so the discover operator's regular-search behavior
    # on such registries is a documented upstream outcome, not a port defect.
    seam = _keyword_registry()
    assert seam.search_records("jobs", type="source", page=0, page_size=10) == []

"""The seam's search extension against REAL blue-data.

Pins the two delegate result shapes (wrapped keyword fallback, flat hybrid), the
score inversion and derived-id rules, the dropped approximate/hybrid parameters,
and the two upstream search behaviors consumers must know: the hierarchical
engine now completes rather than crashing on a shadowed type parameter, and flat
search now returns scored keyword matches on a registry with no vector source.
"""

# blue-data ships no py.typed:
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import hashlib
import inspect
import math
from pathlib import Path
from typing import Any, cast

import blue_data.core.utils.similarity_utils as similarity_algorithm
import blue_data.registry.search.hybrid_search as hybrid_algorithm
import blue_data.registry.search.registry_search as search_algorithm
import pytest
from blue_data.registry.data_registry import DataRegistry  # noqa: E402
from blue_data.source.vector.memory_vector_source import MemoryVectorSource  # noqa: E402

from blue_data_ops.data import RegistrySeam  # noqa: E402
from blue_data_ops.data.registry_seam import (  # noqa: E402
    _normalize_search_result,  # pyright: ignore[reportPrivateUsage]
)

_SEARCH_IDENTITIES = {
    (
        "27d87d9815acee9b431f1504082fdd378478355dda6fdc52f56179891a122629",
        "ad2ec87faad0e2c41bcd408e6e9e2aba2610b94b16f4a801e4f6dd1aa1316e52",
        "690bacdc3c5a21374cf722b28b0fffec2e3b28ad634dc8ff1f8510956cc45ec1",
    ): "dev",
    (
        "017876a7d28f755874b9e9316490fcd8c31feb866f173f87856490bec14e2800",
        "68b6e1703e4379babb45ef3ad76df94d02cb1eb946b045da6655fb3bc5edc381",
        "d22e9f809646bd242f6fbbb138ab868d4e6a5d67df25a4652c43114e419bf694",
    ): "1.0",
}

_PLURAL_SEARCH_IDENTITIES = {
    (
        "017876a7d28f755874b9e9316490fcd8c31feb866f173f87856490bec14e2800",
        "68b6e1703e4379babb45ef3ad76df94d02cb1eb946b045da6655fb3bc5edc381",
        "d2225ed76078392aed15d241842e4409ba85e28cccecd28e40cc999a5eb69df1",
    ): "1.0-plural",
}


def _search_contract() -> str:
    identity = tuple(
        hashlib.sha256(Path(cast(str, module.__file__)).read_bytes()).hexdigest()
        for module in (search_algorithm, hybrid_algorithm, similarity_algorithm)
    )
    contracts = {**_SEARCH_IDENTITIES, **_PLURAL_SEARCH_IDENTITIES}
    assert identity in contracts, "unrecognized blue-data search algorithm identity"
    return contracts[cast(tuple[str, str, str], identity)]


def test_search_identity_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search_algorithm, "__file__", __file__)
    with pytest.raises(AssertionError, match="unrecognized"):
        _search_contract()
    monkeypatch.setattr(search_algorithm, "__file__", None)
    with pytest.raises(TypeError):
        _search_contract()


def test_wrapped_keyword_scores_invert_separately() -> None:
    normalized = [
        _normalize_search_result(
            {"record": {"name": str(score), "type": "source", "scope": "/"}, "score": score}
        )
        for score in (15, 10, 5)
    ]
    assert [row["score"] for row in normalized] == pytest.approx([0, 1 / 3, 2 / 3])
    assert [row["id"] for row in normalized] == ["//source/15", "//source/10", "//source/5"]


def _stub_embedding(texts: list[str]) -> list[list[float]]:
    return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


def _keyword_registry() -> RegistrySeam:
    # Dev uses keyword fallback here; 1.0 uses flat hybrid BM25.
    registry: Any = DataRegistry(name="kw_probe", rebuild=True)
    registry.register_record("jobs_db", "source", "/", description="job postings database")
    registry.register_record("jobs_kb", "source", "/", description="jobs knowledge")
    registry.register_record("other", "source", "/", description="unrelated")
    return RegistrySeam(registry)


# --- the wrapped keyword variant, normalized end-to-end -------------------------- #
def test_keyword_fallback_normalized_shape_and_order() -> None:
    seam = _keyword_registry()
    results = seam.search_records_hierarchical("jobs", type="source", page=0, page_size=10)
    expected = {
        "dev": [("jobs_kb", 0.0), ("jobs_db", 1.0 / 3.0)],
        "1.0": [("jobs_kb", 3.0 / 23.0), ("jobs_db", 9.0 / 23.0)],
        "1.0-plural": [("jobs_db", 3.0 / 23.0), ("jobs_kb", 3.0 / 23.0)],
    }[_search_contract()]
    assert [r["name"] for r in results] == [name for name, _ in expected]
    assert [r["score"] for r in results] == pytest.approx([score for _, score in expected])
    assert all(math.isfinite(r["score"]) for r in results)
    assert [r["score"] for r in results] == sorted(r["score"] for r in results)
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
    if _search_contract() == "dev":
        assert scores == pytest.approx([0.0, 1.0 / 3.0, 2.0 / 3.0])
        assert [r["name"] for r in results] == ["alpha jobs", "jobs_beta", "gamma"]
    else:
        assert scores == pytest.approx([3.0 / 23.0])
        assert [r["name"] for r in results] == ["alpha jobs"]
    assert all(math.isfinite(score) for score in scores)
    assert scores == sorted(scores)


@pytest.mark.parametrize("query", ["job", "jobs"])
def test_singular_plural_search_scores(query: str) -> None:
    registry: Any = DataRegistry(name="kw_plural", rebuild=True)
    for name in ("job", "jobs", "other"):
        registry.register_record(name, "source", "/", description="unrelated")
    seam = RegistrySeam(registry)
    results = seam.search_records_hierarchical(query, type="source", page=0, page_size=10)
    expected = {
        "dev": {
            "job": [("job", 1.0 / 3.0), ("jobs", 1.0 / 3.0)],
            "jobs": [("jobs", 1.0 / 3.0)],
        },
        "1.0": {
            "job": [("job", 3.0 / 23.0)],
            "jobs": [("jobs", 3.0 / 23.0)],
        },
        "1.0-plural": {
            "job": [("job", 3.0 / 23.0), ("jobs", 3.0 / 23.0)],
            "jobs": [("job", 3.0 / 23.0), ("jobs", 3.0 / 23.0)],
        },
    }[_search_contract()][query]
    assert [r["name"] for r in results] == [name for name, _ in expected]
    scores = [r["score"] for r in results]
    assert scores == pytest.approx([score for _, score in expected])
    assert all(math.isfinite(score) for score in scores)
    assert scores == sorted(scores)
    for r in results:
        assert set(r) == {"name", "type", "scope", "id", "score", "description"}
        assert r["type"] == "source"
        assert r["scope"] == "/"
        assert r["id"] == f"//source/{r['name']}"


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
def test_vector_hierarchical_engine_returns_a_bounded_result() -> None:
    # This test previously pinned a crash: the hybrid hierarchical engine shadowed the
    # type() builtin with its own parameter and failed on the first record for any call.
    # Upstream fixed that by renaming the parameter to record_type across
    # prepare_parameters, _filter_records, search, and search_hierarchical, so the call
    # now completes and the seam returns an ordinary result list.
    #
    # It is empty here for a threshold reason rather than an error reason: the stub
    # embedding gives every record the same vector, so no record clears the engine's
    # default vector threshold. What the seam guarantees is the shape.
    registry: Any = DataRegistry(
        name="crash_probe",
        rebuild=True,
        vector_source=MemoryVectorSource("v"),
        embedding_fn=_stub_embedding,
        vector_dim=4,
    )
    registry.register_record("jobs_db", "source", "/", description="job postings")
    seam = RegistrySeam(registry)

    results = seam.search_records_hierarchical("jobs", type="source", page=0, page_size=10)

    assert type(results) is list
    assert all(type(record) is dict for record in results)
    assert len(results) <= 10


def test_flat_search_returns_scored_keyword_matches() -> None:
    # This test previously pinned an empty result: default thresholds filtered every
    # record whose vector score was 0, so a no-vector registry matched nothing even on
    # an exact name match. Under the current pin a keyword match survives scoring, so
    # the discover operator's regular-search path on such registries now yields records.
    seam = _keyword_registry()

    results = seam.search_records("jobs", type="source", page=0, page_size=10)

    assert results, "a no-vector registry now returns keyword matches"
    assert all(record["type"] == "source" for record in results)
    assert all(record["scope"] == "/" for record in results)
    # The seam's derived id and inverted score rules still hold on every entry.
    for record in results:
        assert record["id"] == f"//source/{record['name']}"
        assert type(record["score"]) is float
        assert 0.0 < record["score"] <= 1.0
    assert all("jobs" in record["name"] for record in results)

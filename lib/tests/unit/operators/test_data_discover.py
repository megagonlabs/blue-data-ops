"""Acceptance tests for the migrated data_discover operator.

Operator logic is asserted against the recording seam double (consumer-shaped
search pages); scope construction, threshold semantics, progressive pagination,
the swallow-to-[[]] design, the validator, and the explainer quirks are pinned
from blue-dev's source. The seam's search normalization itself is
pinned against real blue-data in the data-layer suite.
"""

from __future__ import annotations

from typing import Any

import pytest

blue_data = pytest.importorskip("blue_data")

from blue_data_ops.data import RegistrySeam  # noqa: E402
from blue_data_ops.operators.data_discover_operator import (  # noqa: E402
    DataDiscoverOperator,
    _construct_scope,  # pyright: ignore[reportPrivateUsage]
    _transform_result,  # pyright: ignore[reportPrivateUsage]
)
from tests.doubles.data import RegistrySeamDouble  # noqa: E402

INPUT: list[list[dict[str, Any]]] = [[]]

ATTRS: dict[str, Any] = {"search_query": "jobs"}


def _hit(name: str, score: float, scope: str = "/") -> dict[str, Any]:
    return {
        "name": name,
        "type": "source",
        "scope": scope,
        "id": f"{scope}/source/{name}",
        "score": score,
    }


class _RecordingSeam(RegistrySeamDouble, RegistrySeam):
    """The recording double, typed as a RegistrySeam so injection resolves it."""


class _RaisingSeam(_RecordingSeam):
    def search_records_hierarchical(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise TypeError("'str' object is not callable")  # the upstream engine crash shape


@pytest.fixture
def op() -> DataDiscoverOperator:
    return DataDiscoverOperator()


@pytest.fixture
def seam() -> _RecordingSeam:
    recording = _RecordingSeam()
    recording.search_pages = {0: [_hit("jobs_db", 0.1), _hit("jobs_kb", 0.3)]}
    recording.records[("jobs_db", "source", "/")] = {
        "name": "jobs_db",
        "description": "job postings",
        "properties": {"kind": "sql"},
        "metadata": {"owner": "ops"},
    }
    return recording


def _props(seam: RegistrySeam) -> dict[str, Any]:
    return {"data_registry": seam}


# --- D-F1: no registry => [[]] ---
@pytest.mark.parametrize("properties", [None, {}, {"unrelated": 1}])
def test_no_registry_returns_empty(
    op: DataDiscoverOperator, properties: dict[str, Any] | None
) -> None:
    assert op.apply(INPUT, dict(ATTRS), properties) == [[]]


# --- D-F2: simple pagination call shapes ---
def test_hierarchical_call_shape_default(op: DataDiscoverOperator, seam: _RecordingSeam) -> None:
    op.apply(INPUT, dict(ATTRS), _props(seam))
    [call] = seam.calls_to("search_records_hierarchical")
    # scope=None (the default) passes through as None — upstream's early return
    assert call == {
        "input_query": "jobs",
        "type": "source",
        "scope": None,
        "page": 0,
        "page_size": 10,
    }


def test_regular_call_shape_forwards_approximate_hybrid(
    op: DataDiscoverOperator, seam: _RecordingSeam
) -> None:
    op.apply(INPUT, {**ATTRS, "use_hierarchical_search": False, "hybrid": True}, _props(seam))
    [call] = seam.calls_to("search_records")
    assert call["approximate"] is True and call["hybrid"] is True
    assert call["page"] == 0 and call["page_size"] == 10


# --- D-F3: threshold + filter_names + transform ---
def test_threshold_keeps_low_scores_only(op: DataDiscoverOperator, seam: _RecordingSeam) -> None:
    seam.search_pages = {0: [_hit("close", 0.2), _hit("far", 0.9)]}
    out = op.apply(INPUT, {**ATTRS, "threshold": 0.5}, _props(seam))
    assert [r["name"] for r in out[0]] == ["close"]  # score <= threshold kept (lower = better)


def test_no_filtering_when_not_approximate_or_hybrid(
    op: DataDiscoverOperator, seam: _RecordingSeam
) -> None:
    seam.search_pages = {0: [_hit("far", 0.9)]}
    out = op.apply(INPUT, {**ATTRS, "approximate": False}, _props(seam))
    assert [r["name"] for r in out[0]] == ["far"]  # unfiltered without approximate/hybrid


def test_filter_names_skips_matches(op: DataDiscoverOperator, seam: _RecordingSeam) -> None:
    out = op.apply(INPUT, {**ATTRS, "filter_names": ["jobs_db"]}, _props(seam))
    assert [r["name"] for r in out[0]] == ["jobs_kb"]


def test_transform_enriches_from_get_record(op: DataDiscoverOperator, seam: _RecordingSeam) -> None:
    out = op.apply(INPUT, dict(ATTRS), _props(seam))
    enriched = out[0][0]
    assert enriched == {
        "type": "source",
        "name": "jobs_db",
        "id": "//source/jobs_db",
        "scope": "/",
        "score": 0.1,
        "description": "job postings",
        "properties": {"kind": "sql"},
    }
    bare = out[0][1]  # no stored record => empty description/properties, no metadata
    assert bare["description"] == "" and bare["properties"] == {}
    assert "metadata" not in bare


def test_include_metadata(op: DataDiscoverOperator, seam: _RecordingSeam) -> None:
    out = op.apply(INPUT, {**ATTRS, "include_metadata": True}, _props(seam))
    assert out[0][0]["metadata"] == {"owner": "ops"}
    assert "metadata" not in out[0][1]  # absent record: no metadata key even when requested


# --- D-F4: limit ---
@pytest.mark.parametrize(
    "limit,expected", [(-1, 2), (0, 0), (1, 1), (5, 2)], ids=["all", "zero", "one", "over"]
)
def test_limit(op: DataDiscoverOperator, seam: _RecordingSeam, limit: int, expected: int) -> None:
    out = op.apply(INPUT, {**ATTRS, "limit": limit}, _props(seam))
    assert len(out[0]) == expected


# --- D-F5: progressive pagination ---
def test_progressive_pagination_walks_pages_until_threshold(
    op: DataDiscoverOperator, seam: _RecordingSeam
) -> None:
    seam.search_pages = {
        0: [_hit("a", 0.1), _hit("b", 0.2)],
        1: [_hit("c", 0.3), _hit("d", 0.8)],  # d exceeds: inner+outer break here
        2: [_hit("e", 0.05)],
    }
    out = op.apply(INPUT, {**ATTRS, "progressive_pagination": True, "threshold": 0.5}, _props(seam))
    assert [r["name"] for r in out[0]] == ["a", "b", "c"]
    pages = [c["page"] for c in seam.calls_to("search_records_hierarchical")]
    assert pages == [0, 1]  # page 2 never fetched


def test_progressive_pagination_stops_on_empty_page(
    op: DataDiscoverOperator, seam: _RecordingSeam
) -> None:
    seam.search_pages = {0: [_hit("a", 0.1)]}
    out = op.apply(INPUT, {**ATTRS, "progressive_pagination": True}, _props(seam))
    assert [r["name"] for r in out[0]] == ["a"]
    pages = [c["page"] for c in seam.calls_to("search_records_hierarchical")]
    assert pages == [0, 1]  # the empty page 1 ends the loop


def test_progressive_requires_approximate_or_hybrid(
    op: DataDiscoverOperator, seam: _RecordingSeam
) -> None:
    # not approximate and not hybrid => simple pagination even with the flag on
    seam.search_pages = {0: [_hit("a", 0.9)], 1: [_hit("b", 0.9)]}
    out = op.apply(
        INPUT,
        {**ATTRS, "approximate": False, "progressive_pagination": True},
        _props(seam),
    )
    assert [r["name"] for r in out[0]] == ["a"]  # single call, unfiltered


# --- D-F6: the swallow design ---
def test_search_failure_swallowed_to_empty(op: DataDiscoverOperator) -> None:
    # The upstream engine's crash shape (and any other search failure) is logged
    # and swallowed to [[]] by design.
    raising = _RaisingSeam()
    assert op.apply(INPUT, dict(ATTRS), _props(raising)) == [[]]


# --- D-F7: scope construction (module helper, upstream-verbatim observables) ---
@pytest.mark.parametrize(
    "kwargs,expected",
    [
        (dict(scope=None, source="s", database="d", collection="c", concept_type="database"), None),
        (dict(scope="/x/y/", concept_type="source", auto_construct=False), "/x/y"),
        (dict(scope="", concept_type="source", auto_construct=False), "/"),
        (dict(scope="/", concept_type="source"), "/"),
        (dict(scope="/", source="s", concept_type="database"), "/source/s"),
        (
            dict(scope="/", source="s", database="d", concept_type="collection"),
            "/source/s/database/d",
        ),
        (
            dict(scope="/", source="s", database="d", collection="c", concept_type="entity"),
            "/source/s/database/d/collection/c",
        ),
        (dict(scope="/", source="s", concept_type="entity"), "/source/s"),
        (dict(scope="/source/x/database/y", concept_type="collection"), "/source/x/database/y"),
        (
            dict(scope="/source/x/database/y", source="s", concept_type="collection"),
            "/source/s/database/y",
        ),
        (
            dict(scope="/source/x/database/y/collection/z/entity/e", concept_type="attribute"),
            "/source/x/database/y/collection/z/entity/e",
        ),
        (dict(scope="/source/x", concept_type="mystery"), "/source/x"),  # unknown type: base scope
    ],
    ids=[
        "none-scope-short-circuits",
        "no-auto-construct-rstrip",
        "no-auto-construct-empty",
        "source-root",
        "database-from-source",
        "collection-from-source-db",
        "entity-full",
        "entity-partial",
        "explicit-scope-parsed",
        "attr-overrides-scope-part",
        "attribute-entity-scope",
        "unknown-type-fallback",
    ],
)
def test_construct_scope_matrix(kwargs: dict[str, Any], expected: str | None) -> None:
    defaults: dict[str, Any] = dict(source=None, database=None, collection=None)
    assert _construct_scope(**{**defaults, **kwargs}) == expected


# --- D-F8: transform helper edge (score passthrough only when present) ---
def test_transform_without_score(seam: _RecordingSeam) -> None:
    result = {"name": "x", "id": "/x", "scope": "/"}
    transformed = _transform_result(result, "source", seam, include_metadata=False)
    assert "score" not in transformed


# --- Validator ---
# `approximate` is declared required (with a default) — the presence-based base gate
# rejects attribute sets without it, matching blue-dev's declared schema.
BASE: dict[str, Any] = {"search_query": "q", "approximate": True}


@pytest.mark.parametrize(
    "attrs,expected",
    [
        (dict(BASE), True),
        ({"search_query": "q"}, False),  # approximate required-but-absent
        ({"approximate": True}, False),  # search_query required
        ({**BASE, "search_query": "  "}, False),
        ({**BASE, "page": -1}, False),
        ({**BASE, "page_size": 0}, False),
        ({**BASE, "threshold": 1.5}, False),
        ({**BASE, "threshold": -0.1}, False),
        ({**BASE, "database": "d"}, False),  # database requires source
        ({**BASE, "collection": "c", "source": "s"}, False),  # needs database too
        ({**BASE, "source": "s", "database": "d", "collection": "c"}, True),
        ({**BASE, "concept_type": "mystery"}, False),
        ({**BASE, "concept_type": "attribute"}, True),
        ({**BASE, "page": "junk"}, False),  # type gate inside the try wrap
    ],
    ids=[
        "minimal",
        "no-approximate",
        "missing-query",
        "blank-query",
        "neg-page",
        "zero-page-size",
        "threshold-high",
        "threshold-low",
        "db-no-source",
        "collection-no-db",
        "full-scope-chain",
        "bad-concept",
        "attribute-concept",
        "junk-page-type",
    ],
)
def test_validator(op: DataDiscoverOperator, attrs: dict[str, Any], expected: bool) -> None:
    assert op.validate(INPUT, attrs) is expected


# --- Explainer (custom; incl. the 'None'-scope quirk) ---
def test_explainer_default_scope_renders_none(op: DataDiscoverOperator) -> None:
    out: list[list[dict[str, Any]]] = [[{"name": "a"}]]
    exp = op.explain(out, INPUT, {"search_query": "jobs"})
    assert exp["output"] == out and exp["input_data"] == INPUT
    # Upstream compares the scope against "/" only, so the default None scope is
    # reported literally — pinned.
    assert exp["explanation"] == (
        "Data discover operator searched for source entities using hierarchical "
        "search with query 'jobs' within scope 'None' and returned 1 results."
    )


def test_explainer_root_scope_omits_scope_info(op: DataDiscoverOperator) -> None:
    exp = op.explain(
        [[]], INPUT, {"search_query": "q", "scope": "/", "use_hierarchical_search": False}
    )
    assert exp["explanation"] == (
        "Data discover operator searched for source entities using regular "
        "search with query 'q' and returned 0 results."
    )


# --- Interface parity ---
def test_interface(op: DataDiscoverOperator) -> None:
    assert op.name == "data_discover"
    assert op.description == "Discovers data sources using the data registry"
    assert op.DEFAULT_PROPERTIES == {}
    expected_required = {"search_query": True, "approximate": True}
    assert len(op.attributes) == 17
    for attr_name, spec in op.attributes.items():
        assert spec.required is expected_required.get(attr_name, False)
    assert op.attributes["approximate"].default is True
    assert op.attributes["concept_type"].default == "source"
    assert op.attributes["limit"].default == -1
    assert op.attributes["threshold"].default == 0.5
    assert op.attributes["scope"].default is None
    assert op.attributes["filter_names"].type == "list"

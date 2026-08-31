"""Versioned registry discovery and metadata validation.

The checked-in catalog covers card metadata, validation, resolution, ranking,
tag filtering, custom registrations, and the 36-card v2 selection.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from blue_data_ops.operators import (
    DiscoveryError,
    DiscoverySpec,
    OperatorCard,
    OperatorRegistry,
    default_registry,
    versioned_registry,
)
from blue_data_ops.operators._discovery import (
    NAMESPACE_ORDER,
    REQUIRED_NAMESPACES,
    namespace_of,
    validate_builtin_discovery,
)
from blue_data_ops.operators.registry import (
    _builtin_discovery_specs,  # pyright: ignore[reportPrivateUsage]
)

_LIB = Path(__file__).resolve().parents[3]
_FIXTURE_PATH = _LIB / "tests/fixtures/v2_discovery_catalog.json"

_FIXTURE: dict[str, Any] = json.loads(_FIXTURE_PATH.read_text())
_CARDS: dict[str, dict[str, Any]] = {card["operator_id"]: card for card in _FIXTURE["cards"]}
_NAMES: list[str] = sorted({card["name"] for card in _FIXTURE["cards"]})


# --------------------------------------------------------------------------------------------------
# Catalog provenance: canonical formatting, source manifest, and catalog size
# --------------------------------------------------------------------------------------------------
def test_fixture_is_canonical_json_with_expected_structure() -> None:
    checked_in = _FIXTURE_PATH.read_text()
    rendered = json.dumps(_FIXTURE, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    assert rendered == checked_in, "fixture is not canonically formatted"
    assert _FIXTURE["operator_count"] == 36
    assert _FIXTURE["card_count"] == 72
    assert set(_FIXTURE) >= {"operator_count", "card_count", "source_manifest", "cards"}
    assert set(_FIXTURE["source_manifest"]) >= {"files", "aggregate_sha256"}


def test_source_manifest_matches_current_sources() -> None:
    src = _LIB / "src/blue_data_ops/operators"
    recomputed = {
        name: hashlib.sha256((src / f"{name}_operator.py").read_bytes()).hexdigest()
        for name in _NAMES
    }
    assert recomputed == _FIXTURE["source_manifest"]["files"]
    lines = [f"{recomputed[n]}  src/blue_data_ops/operators/{n}_operator.py" for n in _NAMES]
    aggregate = hashlib.sha256("\n".join(lines).encode() + b"\n").hexdigest()
    assert aggregate == _FIXTURE["source_manifest"]["aggregate_sha256"]


def test_exactly_36_names_and_72_cards() -> None:
    registry_names = sorted({c.name for c in versioned_registry().list_cards()})
    assert registry_names == _NAMES
    assert len(_NAMES) == 36
    assert _FIXTURE["operator_count"] == 36
    assert _FIXTURE["card_count"] == 72


# --------------------------------------------------------------------------------------------------
# Card content and built-in metadata
# --------------------------------------------------------------------------------------------------
def test_live_cards_match_the_frozen_snapshot() -> None:
    for card in versioned_registry().list_cards():
        expected = _CARDS[card.operator_id]
        assert card.name == expected["name"]
        assert card.version == expected["version"]
        assert card.description == expected["description"]
        assert list(card.tags) == expected["tags"]
        assert card.when_to_invoke == expected["when_to_invoke"]


@pytest.mark.parametrize("operator_id", sorted(_CARDS))
def test_every_builtin_card_has_valid_metadata(operator_id: str) -> None:
    card = _CARDS[operator_id]
    assert card["when_to_invoke"].strip(), f"{operator_id}: empty when_to_invoke"
    tags = card["tags"]
    assert tags == sorted(set(tags), key=tags.index)  # unique
    by_ns: dict[str, list[str]] = {}
    for tag in tags:
        assert tag == tag.lower() and " " not in tag and "-" in tag
        by_ns.setdefault(namespace_of(tag), []).append(tag)
    for ns in REQUIRED_NAMESPACES:
        assert by_ns.get(ns), f"{operator_id}: missing {ns}-*"
    assert len(by_ns["domain"]) == 1
    # canonical namespace-then-lexicographic order
    order = {ns: i for i, ns in enumerate(NAMESPACE_ORDER)}
    assert tags == sorted(tags, key=lambda t: (order[namespace_of(t)], t))


def test_closed_vocabulary_rejects_out_of_vocab_tag() -> None:
    spec = DiscoverySpec(
        when_to_invoke="Use when.",
        tags=(
            "domain-relational",
            "flow-transform",
            "accepts-data",
            "produces-data",
            "capability-not-a-real-capability",
        ),
    )
    with pytest.raises(DiscoveryError):
        validate_builtin_discovery("probe", spec)


@pytest.mark.parametrize(
    "bad",
    [
        DiscoverySpec(when_to_invoke="", tags=("domain-relational",)),  # empty invocation
        DiscoverySpec(when_to_invoke="x", tags=("domain-relational", "domain-set")),  # two domains
        DiscoverySpec(
            when_to_invoke="x", tags=("flow-transform", "accepts-data")
        ),  # missing domain
        DiscoverySpec(when_to_invoke="x", tags=("Domain-Relational",)),  # non-canonical case
        DiscoverySpec(  # out of canonical order (flow before domain)
            when_to_invoke="x",
            tags=(
                "flow-transform",
                "domain-relational",
                "accepts-data",
                "produces-data",
                "capability-filter",
            ),
        ),
    ],
)
def test_builtin_validation_rejects_malformed_specs(bad: DiscoverySpec) -> None:
    with pytest.raises(DiscoveryError):
        validate_builtin_discovery("probe", bad)


def test_all_36_builtin_specs_validate() -> None:
    specs = _builtin_discovery_specs()
    assert len(specs) == 36  # the validation pre-pass ran on every built-in without raising


# --------------------------------------------------------------------------------------------------
# Resolution, list order, custom compatibility, legacy constructors
# --------------------------------------------------------------------------------------------------
def test_exact_resolution_and_pinned_identity() -> None:
    registry = versioned_registry()
    for name in _NAMES:
        assert registry.resolve(f"{name}@2.0.0").operator_id == f"{name}@2.0.0"
        assert registry.resolve(f"{name}@1.0.0").operator_id == f"{name}@1.0.0"


def test_list_cards_order_is_name_then_version_descending() -> None:
    ids = [c.operator_id for c in versioned_registry().list_cards()]
    assert ids == sorted(
        ids, key=lambda i: (i.split("@")[0], tuple(-int(p) for p in i.split("@")[1].split(".")))
    )


def test_custom_registration_stays_permissive() -> None:
    registry = OperatorRegistry()
    op = _probe_operator("custom")
    card = registry.register(op, "1.0.0", tags=["anything", "UPPER", "no-namespace"])
    assert card.tags == ("anything", "UPPER", "no-namespace")
    assert card.when_to_invoke == ""  # custom callers keep the empty invocation string


def test_legacy_card_constructors_remain_valid() -> None:
    four = OperatorCard("select@1.0.0", "select", "1.0.0", "desc")
    five = OperatorCard("select@1.0.0", "select", "1.0.0", "desc", ("domain-relational",))
    assert four.tags == () and four.when_to_invoke == ""
    assert five.tags == ("domain-relational",) and five.when_to_invoke == ""


# --------------------------------------------------------------------------------------------------
# Text scoring and exact tag filters
# --------------------------------------------------------------------------------------------------
def _probe_operator(name: str) -> Any:
    from blue_data_ops.operators import Operator
    from blue_data_ops.operators.types import Attributes, DataBundle, Properties

    class _Probe(Operator):
        def __init__(self, probe_name: str) -> None:
            type(self).name = probe_name  # type: ignore[misc]
            super().__init__()

        def apply(
            self,
            input_data: DataBundle,
            attributes: Attributes,
            properties: Properties | None = None,
        ) -> DataBundle:
            return input_data

    return _Probe(name)


def _catalog(**cards: tuple[str, tuple[str, ...], str]) -> OperatorRegistry:
    """Build a registry of custom cards (name -> (description, tags, when_to_invoke))."""
    registry = OperatorRegistry()
    for name, (description, tags, when) in cards.items():
        op = _probe_operator(name)
        op.description = description  # type: ignore[misc]
        registry.register(op, "1.0.0", tags=list(tags), when_to_invoke=when)
    return registry


def test_runtime_text_weights_are_the_expected_10_8_6_5() -> None:
    from blue_data_ops.operators.registry import (
        _DESCRIPTION_HIT,  # pyright: ignore[reportPrivateUsage]
        _NAME_HIT,  # pyright: ignore[reportPrivateUsage]
        _TAG_HIT,  # pyright: ignore[reportPrivateUsage]
        _WHEN_TO_INVOKE_HIT,  # pyright: ignore[reportPrivateUsage]
    )

    assert (_NAME_HIT, _TAG_HIT, _WHEN_TO_INVOKE_HIT, _DESCRIPTION_HIT) == (10, 8, 6, 5)
    # the fixture snapshot is bound to these runtime constants
    assert _FIXTURE["text_weights"] == {
        "name": _NAME_HIT,
        "tags": _TAG_HIT,
        "when_to_invoke": _WHEN_TO_INVOKE_HIT,
        "description": _DESCRIPTION_HIT,
    }


def test_text_weights_name_over_tag_over_when_over_description() -> None:
    # One common needle ("zeta") hits exactly one field per card. The full order proves the strict
    # name > tag > when_to_invoke > description ranking, so lowering the name weight below the tag
    # weight (e.g. 10 -> 1) reorders the result and fails this test.
    registry = _catalog(
        zeta_name=("plain", (), ""),  # name hit only: 10
        bcard=("plain", ("zeta-widget",), ""),  # tag hit only: 8
        ccard=("plain", (), "invoke on a zeta here"),  # when hit only: 6
        dcard=("a zeta appears", (), ""),  # description hit only: 5
    )
    assert [c.name for c in registry.find("zeta")] == ["zeta_name", "bcard", "ccard", "dcard"]


def test_each_field_scores_at_most_once() -> None:
    registry = _catalog(
        multi=("nothing", ("query-a", "query-b"), ""),  # two matching tags -> tag score once (8)
        single=("nothing", ("query-a",), "run a query-a query-a here"),  # tag 8 + when 6 = 14
    )
    scored = [c.name for c in registry.find("query")]
    assert scored == ["single", "multi"]  # 14 > 8, proving multi tags add the tag weight once


def test_exact_and_filter_is_normalized_full_token() -> None:
    registry = versioned_registry()
    # AND semantics + case/whitespace normalization
    got = {c.name for c in registry.find("", tags=["  Flow-Head  ", "produces-DATA"])}
    assert got == {"nl2bn", "nl2llm", "nl2sql"}
    # full-token: a substring of a real tag is not a match
    assert registry.find("", tags=["flow-hea"]) == []
    # idempotent repeats
    assert {c.operator_id for c in registry.find("", tags=["flow-plan", "flow-plan"])} == {
        c.operator_id for c in registry.find("", tags=["flow-plan"])
    }


def test_tag_only_and_blank_query_behavior() -> None:
    registry = versioned_registry()
    tag_only = registry.find("", tags=["domain-set"])
    assert sorted({c.name for c in tag_only}) == ["intersect", "union"]
    # tag-only order is name-ascending, version-descending
    ids = [c.operator_id for c in tag_only]
    assert ids == sorted(
        ids, key=lambda i: (i.split("@")[0], tuple(-int(p) for p in i.split("@")[1].split(".")))
    )
    assert registry.find("") == []
    assert registry.find("", tags=[]) == []


@pytest.mark.parametrize("token", ["BAD TAG", "  ", "nohyphen", ""])
def test_malformed_filter_token_is_rejected(token: str) -> None:
    with pytest.raises(DiscoveryError):
        versioned_registry().find("anything", tags=[token])


def test_ties_order_by_name_then_version_descending() -> None:
    registry = versioned_registry()
    # a query matching several equally: both versions of the same name adjacent, v2 before v1
    results = registry.find("", tags=["flow-plan"])
    grouped = [(c.name, c.version) for c in results]
    assert grouped == sorted(
        grouped, key=lambda nv: (nv[0], tuple(-int(p) for p in nv[1].split(".")))
    )


# --------------------------------------------------------------------------------------------------
# The frozen v2 selection
# --------------------------------------------------------------------------------------------------
def test_multi_valued_axes_are_published() -> None:
    cards = {c.operator_id: c for c in versioned_registry().list_cards()}
    for name in ("create_database", "create_table", "insert_table"):
        tags = set(cards[f"{name}@2.0.0"].tags)
        assert {"produces-data", "produces-side-effect"} <= tags
    assert {"produces-data", "produces-query"} <= set(cards["nl2sql@2.0.0"].tags)
    assert {"flow-combine", "flow-transform"} <= set(cards["insert@2.0.0"].tags)
    join = set(cards["semantic_join@2.0.0"].tags)
    assert "requires-llm" in join and "requires-vector" not in join
    assert "capability-embedding-filter" in join


def test_frozen_v2_selection_is_36_ids_inside_the_72_card_catalog() -> None:
    cards = versioned_registry().list_cards()
    v2_ids = sorted(c.operator_id for c in cards if c.version == "2.0.0")
    assert v2_ids == sorted(f"{name}@2.0.0" for name in _NAMES)
    assert len(v2_ids) == 36
    resolved = versioned_registry()
    for operator_id in v2_ids:
        assert resolved.resolve(operator_id).operator_id == operator_id


def test_default_registry_is_36_raw_v1_cards_preserving_the_frozen_mcp_surface() -> None:
    # default_registry() is the frozen v1 compatibility surface: raw cards (no tags/when_to_invoke),
    # so the v1 MCP deployment's raw 36-tool inventory and byte-identical v1 discovery are kept.
    # The enriched six-namespace metadata lives on versioned_registry()'s 72 cards.
    cards = default_registry().list_cards()
    assert len(cards) == 36
    assert all(c.version == "1.0.0" for c in cards)
    assert all(c.tags == () and c.when_to_invoke == "" for c in cards)
    # versioned_registry() carries the metadata on both versions
    versioned = {c.operator_id: c for c in versioned_registry().list_cards()}
    assert all(
        versioned[f"{c.name}@1.0.0"].tags and versioned[f"{c.name}@2.0.0"].tags for c in cards
    )


def test_custom_and_builtin_tags_do_not_share_validation() -> None:
    # A built-in out-of-vocab tag fails; the same tag on a custom registration is permitted.
    registry = OperatorRegistry()
    registry.register(_probe_operator("legacy"), "1.0.0", tags=["capability-not-real"])
    assert registry.get_card("legacy@1.0.0") is not None
    bad = replace(
        _builtin_discovery_specs()[next(iter(_builtin_discovery_specs()))],
        tags=("capability-not-real",),
    )
    with pytest.raises(DiscoveryError):
        validate_builtin_discovery("probe", bad)

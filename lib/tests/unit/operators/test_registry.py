"""The basic OperatorRegistry: register / discover / resolve pinned name@version.

A design-governed portable component (packaging, not upstream behavior parity):
resolution accepts only pinned semver ids and registrations are immutable;
discovery is rule-based over name/description/tags and returns pinned cards.
"""

from __future__ import annotations

import dataclasses

import pytest

from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.registry import (
    OperatorCard,
    OperatorRegistry,
    ResolveError,
    default_registry,
)
from blue_data_ops.operators.types import Attributes, DataBundle, Properties


def _op(name: str, description: str = "") -> Operator:
    class _Concrete(Operator):
        def apply(
            self,
            input_data: DataBundle,
            attributes: Attributes,
            properties: Properties | None = None,
        ) -> DataBundle:
            return input_data

    _Concrete.name = name
    _Concrete.description = description
    return _Concrete()


@pytest.fixture
def registry() -> OperatorRegistry:
    return OperatorRegistry()


# --- register ---
def test_register_returns_pinned_card(registry: OperatorRegistry) -> None:
    op = _op("select", "Selects records")
    card = registry.register(op, "1.0.0", tags=["relational"])
    assert card == OperatorCard(
        operator_id="select@1.0.0",
        name="select",
        version="1.0.0",
        description="Selects records",
        tags=("relational",),
    )


def test_register_is_immutable(registry: OperatorRegistry) -> None:
    registry.register(_op("select"), "1.0.0")
    with pytest.raises(ValueError, match="immutable"):
        registry.register(_op("select"), "1.0.0")


@pytest.mark.parametrize("version", ["1.0", "v1.0.0", "1.0.0-beta", "01.0.0", "1.0.0.0", ""])
def test_register_rejects_non_semver(registry: OperatorRegistry, version: str) -> None:
    with pytest.raises(ValueError, match="semver"):
        registry.register(_op("select"), version)


def test_register_rejects_unnamed_operator(registry: OperatorRegistry) -> None:
    with pytest.raises(ValueError, match="no name"):
        registry.register(_op(""), "1.0.0")


def test_multiple_versions_coexist(registry: OperatorRegistry) -> None:
    registry.register(_op("select"), "1.0.0")
    registry.register(_op("select"), "1.1.0")
    assert registry.get_card("select@1.0.0") is not None
    assert registry.get_card("select@1.1.0") is not None


# --- resolve (pinned only) ---
def test_resolve_exact(registry: OperatorRegistry) -> None:
    op = _op("select")
    registry.register(op, "1.0.0")
    assert registry.resolve("select@1.0.0") is op


@pytest.mark.parametrize(
    "ref",
    ["select", "select@", "select@1.0", "@1.0.0", "select@latest"],
    ids=["bare-name", "empty-version", "short-version", "no-name", "latest-tag"],
)
def test_resolve_rejects_unpinned_references(registry: OperatorRegistry, ref: str) -> None:
    registry.register(_op("select"), "1.0.0")
    with pytest.raises(ResolveError, match="pinned"):
        registry.resolve(ref)


def test_resolve_unknown_pinned_id(registry: OperatorRegistry) -> None:
    with pytest.raises(ResolveError, match="no operator registered"):
        registry.resolve("ghost@1.0.0")


# --- get_card ---
def test_get_card_none_when_absent(registry: OperatorRegistry) -> None:
    assert registry.get_card("ghost@1.0.0") is None


# --- discovery ---
def test_find_scores_name_over_tag_over_description(registry: OperatorRegistry) -> None:
    registry.register(_op("join", "combines"), "1.0.0", tags=["merge"])
    registry.register(_op("union", "a join-like merge"), "1.0.0")
    registry.register(_op("blend", "x"), "1.0.0", tags=["join"])
    cards = registry.find("join")
    assert [c.name for c in cards] == ["join", "blend", "union"]  # 10 > 8 > 5


def test_find_is_case_insensitive_and_substring(registry: OperatorRegistry) -> None:
    registry.register(_op("semantic_join", "LLM join"), "1.0.0")
    assert [c.name for c in registry.find("JOIN")] == ["semantic_join"]


def test_find_empty_or_blank_query(registry: OperatorRegistry) -> None:
    registry.register(_op("select"), "1.0.0")
    assert registry.find("") == []
    assert registry.find("   ") == []


def test_find_no_match(registry: OperatorRegistry) -> None:
    registry.register(_op("select"), "1.0.0")
    assert registry.find("ghost") == []


def test_find_tie_orders_by_name_then_version_desc(registry: OperatorRegistry) -> None:
    registry.register(_op("select_a"), "1.0.0")
    registry.register(_op("select_a"), "1.2.0")
    registry.register(_op("select_b"), "1.0.0")
    ids = [c.operator_id for c in registry.find("select")]
    assert ids == ["select_a@1.2.0", "select_a@1.0.0", "select_b@1.0.0"]


def test_found_cards_are_pinned(registry: OperatorRegistry) -> None:
    registry.register(_op("select"), "1.0.0")
    for card in registry.find("select"):
        name, _, version = card.operator_id.partition("@")
        assert name == card.name and version == card.version


# --- find_latest (semver-numeric, not lexicographic) ---
def test_find_latest_numeric_semver(registry: OperatorRegistry) -> None:
    registry.register(_op("select"), "0.9.0")
    registry.register(_op("select"), "0.10.0")
    latest = registry.find_latest("select")
    assert latest is not None and latest.version == "0.10.0"


def test_find_latest_none_for_unknown(registry: OperatorRegistry) -> None:
    assert registry.find_latest("ghost") is None


def test_find_latest_exact_name_only(registry: OperatorRegistry) -> None:
    registry.register(_op("semantic_join"), "1.0.0")
    assert registry.find_latest("join") is None


# --- list_cards ---
def test_list_cards_ordering(registry: OperatorRegistry) -> None:
    registry.register(_op("b_op"), "1.0.0")
    registry.register(_op("a_op"), "1.0.0")
    registry.register(_op("a_op"), "2.0.0")
    assert [c.operator_id for c in registry.list_cards()] == [
        "a_op@2.0.0",
        "a_op@1.0.0",
        "b_op@1.0.0",
    ]


# --- the pre-loaded default registry ---
def test_default_registry_covers_package_operators() -> None:
    registry = default_registry()
    cards = registry.list_cards()
    names = {c.name for c in cards}
    # spot checks across families; every card is at 1.0.0 unless overridden
    for expected in ("select", "join", "nl2sql", "nl2bn", "data_discover", "semantic_join"):
        assert expected in names
    assert all(c.version == "1.0.0" for c in cards)
    assert registry.resolve("select@1.0.0").name == "select"


def test_default_registry_version_override() -> None:
    registry = default_registry(nl2sql="1.1.0")
    assert registry.get_card("nl2sql@1.1.0") is not None
    assert registry.find_latest("nl2sql") is not None
    assert registry.resolve("nl2sql@1.1.0").name == "nl2sql"
    assert registry.get_card("nl2sql@1.0.0") is None


def test_operator_card_is_frozen() -> None:
    card = OperatorCard(operator_id="x@1.0.0", name="x", version="1.0.0", description="")
    with pytest.raises(dataclasses.FrozenInstanceError):
        card.name = "y"  # type: ignore[misc]

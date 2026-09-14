"""Retained versioned-registry compatibility."""

from __future__ import annotations

from typing import ClassVar

import pytest

import blue_data_ops
from blue_data_ops import ErrorCategory, ErrorCode, ErrorStage
from blue_data_ops.operators import (
    Attributes,
    DataBundle,
    Operator,
    OperatorCard,
    OperatorRegistry,
    Properties,
    ResolveError,
    default_registry,
    versioned_registry,
)
from tests.unit.operators._registry_catalog_expectations import (
    ADDED_OPERATOR_IDS,
    assert_full_inventory,
    assert_legacy_cards,
)

BUILTIN_NAMES: tuple[str, ...] = (
    "argmax",
    "argmin",
    "avg",
    "classify",
    "cluster",
    "create_database",
    "create_table",
    "data_discover",
    "delete",
    "insert",
    "insert_table",
    "intersect",
    "join",
    "max",
    "min",
    "nl2bn",
    "nl2llm",
    "nl2sql",
    "normalize_text",
    "project",
    "segment_text",
    "select",
    "semantic_extract",
    "semantic_filter",
    "semantic_join",
    "semantic_project",
    "semantic_transform",
    "sum",
    "union",
    "vector_embed",
    "vector_search",
    "vector_similarity",
)
V1_IDS = tuple(f"{name}@1.0.0" for name in BUILTIN_NAMES)
V2_IDS = tuple(f"{name}@2.0.0" for name in BUILTIN_NAMES)

INPUT: DataBundle = [[]]
NO_ATTRIBUTES: Attributes = {}
INVALID_TIMEOUT: Properties = {"execution.timeout_seconds": 0}


def _select_deployment(
    registry: OperatorRegistry,
    operator_ids: tuple[str, ...] | None = None,
) -> tuple[OperatorCard, ...]:
    """Resolve a unique, single-version deployment selection."""

    selected = V2_IDS if operator_ids is None else operator_ids
    if len(set(selected)) != len(selected):
        raise ValueError("deployment selection contains a repeated operator id")
    cards: list[OperatorCard] = []
    for operator_id in selected:
        registry.resolve(operator_id)
        card = registry.get_card(operator_id)
        assert card is not None
        cards.append(card)
    if len({card.name for card in cards}) != len(cards):
        raise ValueError("deployment selection contains multiple versions of one tool name")
    return tuple(sorted(cards, key=lambda card: card.name))


def test_default_registry_v1_inventory_and_resolution_identity() -> None:
    registry = default_registry()
    cards = registry.list_cards()

    assert len(cards) == 32
    assert tuple(card.operator_id for card in cards) == V1_IDS
    for name, operator_id in zip(BUILTIN_NAMES, V1_IDS, strict=True):
        resolved = registry.resolve(operator_id)
        assert (resolved.name, resolved.operator_id) == (name, operator_id)


def test_versioned_registry_retained_inventory_and_order() -> None:
    cards = versioned_registry().list_cards()
    legacy = assert_legacy_cards(cards)
    expected = [f"{name}@{version}" for name in BUILTIN_NAMES for version in ("2.0.0", "1.0.0")]

    assert [card.operator_id for card in legacy] == expected
    assert len(legacy) == 64
    assert_full_inventory(cards)


def test_bogus_export_cannot_change_either_inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BogusOperator(Operator):
        name: ClassVar[str] = "bogus"

        def apply(
            self,
            input_data: DataBundle,
            attributes: Attributes,
            properties: Properties | None = None,
        ) -> DataBundle:
            return [[]]

    import blue_data_ops.operators as operators_package

    monkeypatch.setattr(operators_package, "_BogusOperator", _BogusOperator, raising=False)
    monkeypatch.setattr(
        operators_package,
        "__all__",
        [*operators_package.__all__, "_BogusOperator"],
    )

    assert len(default_registry().list_cards()) == 32
    assert_full_inventory(versioned_registry().list_cards())


@pytest.mark.parametrize("name", BUILTIN_NAMES)
def test_v2_card_reports_selected_id_through_run(name: str) -> None:
    operator_id = f"{name}@2.0.0"
    resolved = versioned_registry().resolve(operator_id)

    output_data, output_attributes, meta = resolved.run(INPUT, NO_ATTRIBUTES, INVALID_TIMEOUT)

    assert resolved.operator_id == operator_id
    assert output_data == [[]]
    assert output_attributes == {}
    assert len(meta.errors) == 1
    error = meta.errors[0]
    assert error.operator_id == operator_id
    assert error.category is ErrorCategory.RECOVERABLE
    assert error.code is ErrorCode.INVALID_INPUT
    assert error.stage is ErrorStage.VALIDATE


@pytest.mark.parametrize("name", BUILTIN_NAMES)
def test_v1_card_keeps_compatibility_path(name: str) -> None:
    operator_id = f"{name}@1.0.0"
    versioned = versioned_registry().resolve(operator_id)
    compat = default_registry().resolve(operator_id)

    assert versioned.run(INPUT, NO_ATTRIBUTES, INVALID_TIMEOUT) == compat.run(
        INPUT, NO_ATTRIBUTES, INVALID_TIMEOUT
    )


def test_default_selection_yields_exactly_the_32_v2_ids() -> None:
    snapshot = _select_deployment(versioned_registry())
    assert tuple(card.operator_id for card in snapshot) == V2_IDS


def test_empty_subset_and_added_selections_remain_valid() -> None:
    registry = versioned_registry()
    assert _select_deployment(registry, ()) == ()
    subset = ("select@2.0.0", "join@1.0.0", "sum@2.0.0")
    assert tuple(card.operator_id for card in _select_deployment(registry, subset)) == (
        "join@1.0.0",
        "select@2.0.0",
        "sum@2.0.0",
    )
    assert tuple(card.operator_id for card in _select_deployment(registry, ADDED_OPERATOR_IDS)) == (
        ADDED_OPERATOR_IDS
    )


def test_invalid_selections_fail() -> None:
    registry = versioned_registry()
    with pytest.raises(ValueError, match="repeated operator id"):
        _select_deployment(registry, ("select@2.0.0", "select@2.0.0"))
    with pytest.raises(ValueError, match="multiple versions"):
        _select_deployment(registry, ("select@2.0.0", "select@1.0.0"))
    with pytest.raises(ResolveError):
        _select_deployment(registry, ("ghost@2.0.0",))


@pytest.mark.parametrize(
    "bad_id",
    ["select", "select@", "select@1.0", "select@01.0.0", "@2.0.0", "select@latest"],
)
def test_bare_malformed_and_leading_zero_ids_fail(bad_id: str) -> None:
    with pytest.raises(ResolveError):
        versioned_registry().resolve(bad_id)


def test_mcp_registry_surface_remains_raw_v1() -> None:
    cards = default_registry().list_cards()
    assert len(cards) == 32
    assert all(card.operator_id.endswith("@1.0.0") for card in cards)
    assert not hasattr(blue_data_ops, "versioned_registry")

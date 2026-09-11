from __future__ import annotations

import pytest

from blue_data_ops.operators.registry import default_registry, versioned_registry
from blue_data_ops.plan import planner as planner_module

OUTCOME_IDS = (
    "avg@3.0.0",
    "classify@3.0.0",
    "cluster@3.0.0",
    "insert@3.0.0",
    "insert_table@3.0.0",
    "intersect@3.0.0",
    "join@3.0.0",
    "max@3.0.0",
    "min@3.0.0",
    "nl2bn@3.0.0",
    "nl2llm@3.0.0",
    "nl2sql@3.0.0",
    "project@3.0.0",
    "semantic_extract@3.0.0",
    "semantic_filter@3.0.0",
    "semantic_join@3.0.0",
    "semantic_project@3.0.0",
    "semantic_transform@3.0.0",
    "vector_embed@3.0.0",
    "vector_search@3.0.0",
    "vector_similarity@3.0.0",
)

NEW_OUTCOME_IDS = (
    "classify@3.0.0",
    "cluster@3.0.0",
    "insert@3.0.0",
    "intersect@3.0.0",
    "max@3.0.0",
    "min@3.0.0",
    "nl2bn@3.0.0",
    "nl2llm@3.0.0",
    "nl2sql@3.0.0",
    "project@3.0.0",
    "semantic_extract@3.0.0",
    "semantic_filter@3.0.0",
    "semantic_join@3.0.0",
    "semantic_project@3.0.0",
    "semantic_transform@3.0.0",
    "vector_embed@3.0.0",
    "vector_search@3.0.0",
    "vector_similarity@3.0.0",
)

CONFIRMED_WITHOUT_OUTCOME = (
    "argmax",
    "argmin",
    "create_database",
    "create_table",
    "data_discover",
    "delete",
    "normalize_text",
    "segment_text",
    "select",
    "sum",
    "union",
)


def test_combined_registry_has_the_exact_outcome_inventory() -> None:
    registry = versioned_registry()
    cards = registry.list_cards()
    observed = tuple(card.operator_id for card in cards if card.version == "3.0.0")

    assert len(cards) == 93
    assert observed == OUTCOME_IDS
    assert all(
        type(registry.resolve(operator_id)).__module__
        == f"blue_data_ops.operators._{operator_id.split('@', 1)[0]}_outcome"
        for operator_id in OUTCOME_IDS
    )
    assert all(registry.get_card(f"{name}@3.0.0") is None for name in CONFIRMED_WITHOUT_OUTCOME)


def test_ordinary_defaults_and_planner_selection_stay_at_prior_versions() -> None:
    cards = default_registry().list_cards()

    assert len(cards) == 36
    assert all(card.version == "1.0.0" for card in cards)
    assert planner_module._PLANNER_OPERATOR_VERSION == "2.0.0"  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize("operator_id", NEW_OUTCOME_IDS)
def test_new_outcome_default_override_selects_only_the_requested_body(operator_id: str) -> None:
    name = operator_id.partition("@")[0]
    registry = default_registry(**{name: "3.0.0"})
    cards = registry.list_cards()

    assert len(cards) == 36
    assert (
        type(registry.resolve(operator_id)).__module__ == f"blue_data_ops.operators._{name}_outcome"
    )
    assert all(card.version == ("3.0.0" if card.name == name else "1.0.0") for card in cards)


@pytest.mark.parametrize("operator_id", NEW_OUTCOME_IDS)
def test_new_outcome_is_visible_through_public_discovery(operator_id: str) -> None:
    name = operator_id.partition("@")[0]
    registry = versioned_registry()
    card = registry.get_card(operator_id)

    assert card is not None
    assert registry.find_latest(name) == card
    assert card in registry.find(name)

"""The 3.0 built-in catalog contract."""

from __future__ import annotations

import importlib

import pytest

from blue_data_ops.operators import (
    ResolveError,
    active_registry,
    default_registry,
    versioned_registry,
)
from blue_data_ops.operators.operator_discover_operator import OperatorDiscoverOperator

RETIRED_NAMES = (
    "multipart_query",
    "nl2query_router",
    "plan_discover",
    "query_breakdown",
)
ACTIVE_V3_NAMES = {
    "avg",
    "classify",
    "cluster",
    "insert",
    "insert_table",
    "intersect",
    "join",
    "max",
    "min",
    "nl2bn",
    "nl2llm",
    "nl2sql",
    "project",
    "semantic_extract",
    "semantic_filter",
    "semantic_join",
    "semantic_project",
    "semantic_transform",
    "vector_embed",
    "vector_search",
    "vector_similarity",
}


def test_registry_factories_have_the_3_0_inventory() -> None:
    raw = default_registry().list_cards()
    active = active_registry().list_cards()
    history = versioned_registry().list_cards()

    assert len(raw) == len(active) == 33
    assert len(history) == 88
    assert all(card.version == "1.0.0" and not card.tags for card in raw)
    assert {card.name for card in active if card.version == "3.0.0"} == ACTIVE_V3_NAMES - {"nl2sql"}
    assert sum(card.version == "2.0.0" for card in active) == 12
    assert all(card.tags and card.when_to_invoke and not card.deprecated for card in active)


def test_active_registry_returns_fresh_instances() -> None:
    first = active_registry()
    second = active_registry()
    assert first is not second
    assert first.resolve("select@2.0.0") is not second.resolve("select@2.0.0")


@pytest.mark.parametrize("name", RETIRED_NAMES)
def test_retired_operator_modules_and_ids_are_absent(name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(f"blue_data_ops.operators.{name}_operator")
    for version in ("1.0.0", "2.0.0"):
        with pytest.raises(ResolveError):
            versioned_registry().resolve(f"{name}@{version}")


def test_operator_discovery_defaults_to_the_active_catalog() -> None:
    rows = OperatorDiscoverOperator().apply(
        [[]],
        {"search_query": "", "tags": ["capability-average"]},
    )[0]
    assert {row["operator_id"] for row in rows} == {"avg@3.0.0"}

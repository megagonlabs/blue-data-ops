from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from blue_data_ops.operators import OperatorCard

_LIB = Path(__file__).resolve().parents[3]
_FIXTURE = json.loads((_LIB / "tests/fixtures/operator_discovery_legacy.json").read_text())
_RETIRED_NAMES = {
    "multipart_query",
    "nl2query_router",
    "plan_discover",
    "query_breakdown",
}
LEGACY_CARDS = tuple(
    OperatorCard(**cast(dict[str, Any], {**card, "tags": tuple(card["tags"])}))
    for card in _FIXTURE["cards"]
    if card["name"] not in _RETIRED_NAMES
)
LEGACY_OPERATOR_IDS = tuple(card.operator_id for card in LEGACY_CARDS)
ADDED_OPERATOR_IDS = (
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
SUPPLEMENTAL_OPERATOR_IDS = (
    "sklearn_estimator@2.0.0",
    "sklearn_estimator@1.0.0",
)
FULL_OPERATOR_IDS = tuple(
    sorted(
        (*LEGACY_OPERATOR_IDS, *ADDED_OPERATOR_IDS, *SUPPLEMENTAL_OPERATOR_IDS, "nl2sql@4.0.0"),
        key=lambda oid: (
            oid.split("@")[0],
            tuple(-int(part) for part in oid.split("@")[1].split(".")),
        ),
    )
)


def assert_legacy_cards(cards: Sequence[OperatorCard]) -> list[OperatorCard]:
    unexpected = {card.operator_id for card in cards} - set(FULL_OPERATOR_IDS)
    assert not unexpected, f"unexpected operator IDs: {sorted(unexpected)}"
    legacy = [card for card in cards if card.operator_id in LEGACY_OPERATOR_IDS]
    assert tuple(card.operator_id for card in legacy) == LEGACY_OPERATOR_IDS, (
        "legacy inventory/order changed"
    )
    for card, expected in zip(legacy, LEGACY_CARDS, strict=True):
        assert card == expected, f"legacy metadata changed: {card.operator_id}"
        assert card.deprecated is expected.deprecated, (
            f"legacy lifecycle changed: {card.operator_id}"
        )
    return legacy


def assert_full_inventory(cards: Sequence[OperatorCard]) -> None:
    ids = tuple(card.operator_id for card in cards)
    assert len(ids) == len(set(ids)) == 88, "expected 88 distinct operator IDs"
    assert ids == FULL_OPERATOR_IDS, "full inventory/order changed"


def assert_added_cards_active(cards: Sequence[OperatorCard]) -> None:
    added = [card for card in cards if card.operator_id in ADDED_OPERATOR_IDS]
    assert tuple(card.operator_id for card in added) == ADDED_OPERATOR_IDS
    for card in added:
        assert card.name == card.operator_id.split("@")[0]
        assert card.version == "3.0.0"
        assert card.deprecated is False, f"added card is not active: {card.operator_id}"

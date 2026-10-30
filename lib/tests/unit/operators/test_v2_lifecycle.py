"""Product lifecycle checks for the v2 fixtures and live legacy cards."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

from blue_data_ops.operators import versioned_registry
from tests.unit.operators._registry_catalog_expectations import assert_legacy_cards

_LIB = Path(__file__).resolve().parents[3]
_DISCOVERY_PATH = _LIB / "tests/fixtures/operator_discovery_legacy.json"
_OUTCOMES_PATH = _LIB / "tests/fixtures/operator_outcomes_legacy.json"
_ABSENT = object()

_ACTIVE_LEGACY_NAMES = frozenset(
    {
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
    }
)
_RETIRED_NAMES = frozenset(
    {
        "multipart_query",
        "nl2query_router",
        "plan_discover",
        "query_breakdown",
    }
)
_V2_FIXTURE_NAMES = _ACTIVE_LEGACY_NAMES | _RETIRED_NAMES
_ACTIVE_LEGACY_OPERATOR_IDS = frozenset(
    f"{name}@{version}" for name in _ACTIVE_LEGACY_NAMES for version in ("1.0.0", "2.0.0")
)
_RETIRED_OPERATOR_IDS = frozenset(
    f"{name}@{version}" for name in _RETIRED_NAMES for version in ("1.0.0", "2.0.0")
)
_V2_FIXTURE_OPERATOR_IDS = _ACTIVE_LEGACY_OPERATOR_IDS | _RETIRED_OPERATOR_IDS


def _load(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text()))


def _source_aggregate(files: dict[str, str]) -> str:
    lines = [
        f"{files[name]}  src/blue_data_ops/operators/{name}_operator.py" for name in sorted(files)
    ]
    return hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()


def _source_files(fixture: dict[str, Any]) -> dict[str, str]:
    manifest = cast("dict[str, Any]", fixture["source_manifest"])
    return cast("dict[str, str]", manifest["files"])


def test_discovery_fixture_has_the_v2_operator_ids_and_lifecycle() -> None:
    cards = cast("list[dict[str, Any]]", _load(_DISCOVERY_PATH)["cards"])
    operator_ids = [cast(str, card["operator_id"]) for card in cards]

    assert len(operator_ids) == len(set(operator_ids)) == 72
    assert set(operator_ids) == _V2_FIXTURE_OPERATOR_IDS
    assert operator_ids == sorted(
        operator_ids,
        key=lambda operator_id: (
            operator_id.split("@")[0],
            tuple(-int(part) for part in operator_id.split("@")[1].split(".")),
        ),
    )
    assert all(
        card["operator_id"] == f"{card['name']}@{card['version']}"
        and isinstance(card["deprecated"], bool)
        for card in cards
    )
    assert {card["operator_id"] for card in cards if card["deprecated"]} == _RETIRED_OPERATOR_IDS


def test_outcome_fixture_has_one_row_per_v2_operator() -> None:
    rows = cast("list[dict[str, Any]]", _load(_OUTCOMES_PATH)["rows"])
    names = [cast(str, row["name"]) for row in rows]

    assert len(names) == len(set(names)) == 36
    assert set(names) == _V2_FIXTURE_NAMES
    assert all(row["operator_id"] == f"{row['name']}@2.0.0" for row in rows)
    assert {row["name"] for row in rows if row["is_refinable"]} == _RETIRED_NAMES


def test_v2_fixture_source_manifests_are_consistent() -> None:
    discovery = _load(_DISCOVERY_PATH)
    outcomes = _load(_OUTCOMES_PATH)
    discovery_files = _source_files(discovery)
    outcome_files = _source_files(outcomes)

    assert discovery_files == outcome_files
    assert set(discovery_files) == _V2_FIXTURE_NAMES
    assert all(
        len(digest) == 64 and set(digest) <= set("0123456789abcdef")
        for digest in discovery_files.values()
    )
    for fixture in (discovery, outcomes):
        manifest = cast("dict[str, Any]", fixture["source_manifest"])
        assert manifest["aggregate_sha256"] == _source_aggregate(discovery_files)

    rows = cast("list[dict[str, Any]]", outcomes["rows"])
    assert {row["name"]: row["source_sha256"] for row in rows} == discovery_files


def test_live_legacy_cards_match_the_active_v2_ids() -> None:
    cards = assert_legacy_cards(versioned_registry().list_cards())
    operator_ids = [card.operator_id for card in cards]

    assert len(operator_ids) == len(set(operator_ids)) == 64
    assert set(operator_ids) == _ACTIVE_LEGACY_OPERATOR_IDS
    lifecycle = {card.operator_id: getattr(card, "deprecated", _ABSENT) for card in cards}
    missing = sorted(operator_id for operator_id, flag in lifecycle.items() if flag is _ABSENT)
    assert missing == [], f"OperatorCard.deprecated absent for {len(missing)} cards"
    assert all(flag is False for flag in lifecycle.values())

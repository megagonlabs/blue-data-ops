"""Scope guard for the v2.8 operator-lifecycle change.

v2.8 edits four operator modules, so both checked-in manifests recompute four source
digests each. This module pins everything else: the 32 unaffected module digests, every
behavioral expectation already carried by ``v2_discovery_catalog.json`` and
``v2_operator_outcomes.json``, and the lifecycle flags for the eight cohort cards.

``test_live_cards_carry_the_frozen_lifecycle_flags`` fails against 2.7.0 until
``OperatorCard`` gains a ``deprecated`` field. The flags it checks are the specification
for that field, not a reading of current behavior. Frozen values are literals in
``_v2_source_manifest_baseline``, so nothing here reads Git history at run time.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

from blue_data_ops.operators import versioned_registry
from tests.unit.operators._v2_source_manifest_baseline import (
    BASELINE_COMMIT,
    DEPRECATED_OPERATOR_IDS,
    DEPRECATION_COHORT,
    DISCOVERY_CARD_SHA256,
    DISCOVERY_MUTABLE_PATHS,
    DISCOVERY_SECTION_SHA256,
    OUTCOME_MUTABLE_PATHS,
    OUTCOME_ROW_SHA256,
    OUTCOME_SECTION_SHA256,
    UNAFFECTED_SOURCE_SHA256,
)

_LIB = Path(__file__).resolve().parents[3]
_SRC_OPERATORS = _LIB / "src/blue_data_ops/operators"
_DISCOVERY_PATH = _LIB / "tests/fixtures/v2_discovery_catalog.json"
_OUTCOMES_PATH = _LIB / "tests/fixtures/v2_operator_outcomes.json"

_ABSENT = object()


# --------------------------------------------------------------------------------------------------
# Projections. Each drops exactly the values v2.8 may recompute; the remainder is frozen.
# --------------------------------------------------------------------------------------------------
def _load(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text()))


def _digest(value: Any) -> str:
    canonical = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _without(mapping: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: value for key, value in mapping.items() if key not in keys}


def _frozen_manifest(fixture: dict[str, Any]) -> dict[str, Any]:
    """The manifest block minus the four cohort digests and the aggregate they feed."""
    manifest = cast("dict[str, Any]", fixture["source_manifest"])
    files = cast("dict[str, str]", manifest["files"])
    kept = {name: sha for name, sha in files.items() if name not in DEPRECATION_COHORT}
    return {**_without(manifest, "files", "aggregate_sha256"), "files": kept}


def _sections(fixture: dict[str, Any], collection: str) -> dict[str, str]:
    scalars = _without(fixture, collection, "source_manifest")
    digested = {key: _digest(value) for key, value in scalars.items()}
    digested["source_manifest"] = _digest(_frozen_manifest(fixture))
    return digested


def _discovery_cards(fixture: dict[str, Any]) -> dict[str, str]:
    """Per-card digests with ``deprecated`` removed.

    ``test_discovery_fixture_lifecycle_oracle`` pins the lifecycle flags instead, which
    keeps each digest comparable to its 2.7.0 value.
    """
    cards = cast("list[dict[str, Any]]", fixture["cards"])
    return {card["operator_id"]: _digest(_without(card, "deprecated")) for card in cards}


def _outcome_rows(fixture: dict[str, Any]) -> dict[str, str]:
    """Per-row digests, keyed by name.

    Keying is last-wins, so a repeated name would let a later row overwrite an edited one
    and keep its frozen digest visible. The precondition admits only the frozen names,
    once each, so the projection cannot drop a row.
    """
    rows = cast("list[dict[str, Any]]", fixture["rows"])
    names = sorted(row["name"] for row in rows)
    assert names == sorted(OUTCOME_ROW_SHA256), (
        f"outcome rows must be the {len(OUTCOME_ROW_SHA256)} frozen names once each, "
        f"got {len(names)} rows"
    )
    return {
        row["name"]: _digest(
            _without(row, "source_sha256") if row["name"] in DEPRECATION_COHORT else row
        )
        for row in rows
    }


def _live_source_digests() -> dict[str, str]:
    return {
        name: hashlib.sha256((_SRC_OPERATORS / f"{name}_operator.py").read_bytes()).hexdigest()
        for name in UNAFFECTED_SOURCE_SHA256
    }


def _resolve(fixture: dict[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = fixture
    for segment in path:
        if isinstance(node, list):
            rows = cast("list[dict[str, Any]]", node)
            node = next(row for row in rows if row["name"] == segment)
        else:
            node = cast("dict[str, Any]", node)[segment]
    return node


# --------------------------------------------------------------------------------------------------
# The guard
# --------------------------------------------------------------------------------------------------
def test_source_manifest_amendment_scope() -> None:
    discovery = _load(_DISCOVERY_PATH)
    outcomes = _load(_OUTCOMES_PATH)
    observed = {
        "source": _live_source_digests(),
        "discovery.section": _sections(discovery, "cards"),
        "discovery.card": _discovery_cards(discovery),
        "outcome.section": _sections(outcomes, "rows"),
        "outcome.row": _outcome_rows(outcomes),
    }
    frozen = {
        "source": dict(UNAFFECTED_SOURCE_SHA256),
        "discovery.section": dict(DISCOVERY_SECTION_SHA256),
        "discovery.card": dict(DISCOVERY_CARD_SHA256),
        "outcome.section": dict(OUTCOME_SECTION_SHA256),
        "outcome.row": dict(OUTCOME_ROW_SHA256),
    }
    drift = sorted(
        f"{group}:{key}"
        for group, expected in frozen.items()
        for key in set(expected) | set(observed[group])
        if expected.get(key) != observed[group].get(key)
    )
    assert drift == [], f"frozen at {BASELINE_COMMIT}, moved: {drift}"


def test_duplicate_outcome_row_is_rejected() -> None:
    outcomes = _load(_OUTCOMES_PATH)
    rows = cast("list[dict[str, Any]]", outcomes["rows"])
    rows.append(copy.deepcopy(rows[0]))
    last_wins = {row["name"]: row for row in rows}

    assert len(rows) == len(OUTCOME_ROW_SHA256) + 1
    assert set(last_wins) == set(OUTCOME_ROW_SHA256)
    with pytest.raises(AssertionError, match="once each"):
        _outcome_rows(outcomes)


def test_changed_outcome_row_behind_a_duplicate_is_rejected() -> None:
    outcomes = _load(_OUTCOMES_PATH)
    rows = cast("list[dict[str, Any]]", outcomes["rows"])
    changed = next(row for row in rows if row["name"] == "argmax")
    original = copy.deepcopy(changed)
    changed["cases"]["success"]["expected_output"] = [[]]
    rows.append(original)
    last_wins = {row["name"]: row for row in rows}

    assert _digest(changed) != OUTCOME_ROW_SHA256["argmax"]
    assert _digest(last_wins["argmax"]) == OUTCOME_ROW_SHA256["argmax"]
    with pytest.raises(AssertionError, match="once each"):
        _outcome_rows(outcomes)


def test_frozen_source_set_is_the_32_unaffected_modules() -> None:
    names = {card["name"] for card in cast("list[dict[str, Any]]", _load(_DISCOVERY_PATH)["cards"])}
    assert len(names) == 36
    assert set(UNAFFECTED_SOURCE_SHA256) == names - set(DEPRECATION_COHORT)
    assert len(UNAFFECTED_SOURCE_SHA256) == 32
    assert all(len(sha) == 64 for sha in UNAFFECTED_SOURCE_SHA256.values())


def test_permitted_mutable_value_set_is_exact() -> None:
    cohort = tuple(sorted(DEPRECATION_COHORT))
    assert DISCOVERY_MUTABLE_PATHS == (
        *[("source_manifest", "files", name) for name in cohort],
        ("source_manifest", "aggregate_sha256"),
    )
    assert OUTCOME_MUTABLE_PATHS == (
        *[("source_manifest", "files", name) for name in cohort],
        ("source_manifest", "aggregate_sha256"),
        *[("rows", name, "source_sha256") for name in cohort],
    )
    assert len(DISCOVERY_MUTABLE_PATHS) + len(OUTCOME_MUTABLE_PATHS) == 14
    for path, paths in (
        (_DISCOVERY_PATH, DISCOVERY_MUTABLE_PATHS),
        (_OUTCOMES_PATH, OUTCOME_MUTABLE_PATHS),
    ):
        fixture = _load(path)
        for mutable in paths:
            value = _resolve(fixture, mutable)
            assert isinstance(value, str) and len(value) == 64, f"{path.name}: {mutable}"


# --------------------------------------------------------------------------------------------------
# Lifecycle oracle: the v2.8 contract for OperatorCard.deprecated, not a reading of 2.7.0.
# --------------------------------------------------------------------------------------------------
def test_discovery_fixture_lifecycle_oracle() -> None:
    cards = cast("list[dict[str, Any]]", _load(_DISCOVERY_PATH)["cards"])
    assert len(cards) == 72
    assert all(isinstance(card["deprecated"], bool) for card in cards)
    flagged = {card["operator_id"] for card in cards if card["deprecated"]}
    assert flagged == set(DEPRECATED_OPERATOR_IDS)
    assert len(flagged) == 8
    assert len([card for card in cards if not card["deprecated"]]) == 64
    assert {oid.split("@")[0] for oid in flagged} == set(DEPRECATION_COHORT)
    assert {oid.split("@")[1] for oid in flagged} == {"1.0.0", "2.0.0"}


def test_live_cards_carry_the_frozen_lifecycle_flags() -> None:
    # Fails until OperatorCard gains `deprecated`. getattr keeps this module type-checkable
    # against 2.7.0, where the attribute does not exist.
    cards = versioned_registry().list_cards()
    assert len(cards) == 72
    lifecycle = {card.operator_id: getattr(card, "deprecated", _ABSENT) for card in cards}
    missing = sorted(oid for oid, flag in lifecycle.items() if flag is _ABSENT)
    assert missing == [], f"OperatorCard.deprecated absent for {len(missing)} cards"
    wrong = {
        oid: flag for oid, flag in lifecycle.items() if flag is not (oid in DEPRECATED_OPERATOR_IDS)
    }
    assert wrong == {}, f"live flags disagree with the frozen oracle: {wrong}"

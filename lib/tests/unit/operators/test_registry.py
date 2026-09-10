"""The basic OperatorRegistry: register / discover / resolve pinned name@version.

A design-governed portable component (packaging, not upstream behavior parity):
resolution accepts only pinned semver ids and registrations are immutable;
discovery is rule-based over name/description/tags and returns pinned cards.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from blue_data_ops import ErrorCode, ErrorStage
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.registry import (
    OperatorCard,
    OperatorRegistry,
    ResolveError,
    default_registry,
    versioned_registry,
)
from blue_data_ops.operators.types import Attributes, DataBundle, Properties
from tests.unit.operators._registry_catalog_expectations import ADDED_OPERATOR_IDS


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
    assert len(cards) == 36
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


@pytest.mark.parametrize("operator_id", ADDED_OPERATOR_IDS)
def test_added_card_identity_schema_and_latest_selection(operator_id: str) -> None:
    registry = versioned_registry()
    operator = registry.resolve(operator_id)
    card = registry.get_card(operator_id)
    assert card is not None
    assert operator.operator_id == card.operator_id == operator_id
    assert operator.name == card.name == operator_id.split("@")[0]
    assert card.version == "3.0.0"
    assert card.deprecated is False
    assert registry.find_latest(card.name) == card
    assert card in registry.find(card.name)
    expected_schema = {
        "avg": {"avg_key": ("str", True), "output_key": ("str", False)},
        "insert_table": {
            "source": ("str", True),
            "database": ("str", True),
            "collection": ("str", False),
            "table": ("str", True),
            "batch_size": ("int", False),
        },
        "join": {
            "join_on": ("list[list[str]]", True),
            "join_type": ("str", False),
            "join_suffix": ("list[str]", False),
            "keep_keys": ("str", False),
        },
    }
    assert {key: (spec.type, spec.required) for key, spec in operator.attributes.items()} == (
        expected_schema[card.name]
    )


def _known_version_outcome(operator: Operator) -> tuple[Any, ...]:
    if operator.name == "avg":
        data, attributes, meta = operator.run([[{"score": 0}, {"score": 0}]], {"avg_key": "score"})
        assert data == [[{"avg": 0.0}]]
        assert attributes == {"num_values_used": 2}
        assert type(attributes["num_values_used"]) is int
        assert meta.is_empty is False
        assert meta.errors == []
    elif operator.name == "insert_table":
        from blue_data_ops.data import RegistrySeam
        from tests.doubles.data import RegistrySeamDouble, SQLSourceDouble

        class EmptyInsertRegistry(RegistrySeamDouble, RegistrySeam):
            pass

        seam = EmptyInsertRegistry()
        source = SQLSourceDouble("src")
        seam.sources["src"] = source
        data, attributes, meta = operator.run(
            [[]],
            {"source": "src", "database": "db", "table": "t"},
            {"data_registry": seam},
        )
        assert data == [[]]
        assert attributes == {"num_rows_insert": 0}
        assert type(attributes["num_rows_insert"]) is int
        assert meta.is_empty is True
        assert meta.errors == []
        assert source.connections == {}
    else:
        assert operator.name == "join"
        data, attributes, meta = operator.run(
            [[{"id": 1, "value": 1}], [{"id": 1, "value": 2}]],
            {"join_on": [["id"], ["id"]], "join_suffix": ["_same", "_same"]},
        )
        assert data == [[]]
        assert attributes == {}
        assert meta.is_empty is False
        assert any(
            error.code is ErrorCode.INVALID_INPUT and error.stage is ErrorStage.VALIDATE
            for error in meta.errors
        )
    assert all(error.operator_id == operator.operator_id for error in meta.errors)
    return (
        data,
        attributes,
        meta.is_empty,
        tuple((error.operator_id, error.code, error.stage) for error in meta.errors),
    )


@pytest.mark.parametrize("operator_id", ADDED_OPERATOR_IDS)
def test_known_default_override_selects_the_new_outcome(operator_id: str) -> None:
    name = operator_id.split("@")[0]
    registry = default_registry(**{name: "3.0.0"})
    cards = registry.list_cards()
    assert len(cards) == 36
    assert all(card.tags == () and card.when_to_invoke == "" for card in cards)
    assert registry.get_card(f"{name}@1.0.0") is None
    assert all(card.version == "1.0.0" for card in cards if card.name != name)
    card = registry.get_card(operator_id)
    assert card is not None and card.deprecated is False
    operator = registry.resolve(operator_id)
    assert operator.name == name
    assert operator.operator_id == operator_id
    _known_version_outcome(operator)


@pytest.mark.parametrize("operator_id", ADDED_OPERATOR_IDS)
def test_known_default_override_agrees_with_versioned_outcome(operator_id: str) -> None:
    name = operator_id.split("@")[0]
    versioned = versioned_registry().resolve(operator_id)
    overridden = default_registry(**{name: "3.0.0"}).resolve(operator_id)
    assert versioned.operator_id == overridden.operator_id == operator_id
    assert versioned.attributes == overridden.attributes
    assert _known_version_outcome(versioned) == _known_version_outcome(overridden)


def test_all_known_default_overrides_keep_unselected_raw_cards() -> None:
    registry = default_registry(avg="3.0.0", insert_table="3.0.0", join="3.0.0")
    baseline = default_registry()
    selected_names = {operator_id.split("@")[0] for operator_id in ADDED_OPERATOR_IDS}
    assert len(registry.list_cards()) == 36
    assert (
        tuple(card.operator_id for card in registry.list_cards() if card.name in selected_names)
        == ADDED_OPERATOR_IDS
    )
    assert [card for card in registry.list_cards() if card.name not in selected_names] == [
        card for card in baseline.list_cards() if card.name not in selected_names
    ]
    for operator_id in ADDED_OPERATOR_IDS:
        _known_version_outcome(registry.resolve(operator_id))


def test_unrelated_arbitrary_default_override_keeps_legacy_outcome() -> None:
    registry = default_registry(select="9.8.7", unknown_operator="3.0.0")
    operator = registry.resolve("select@9.8.7")
    baseline = default_registry().resolve("select@1.0.0")
    assert operator.operator_id == "select@9.8.7"
    assert registry.get_card("select@1.0.0") is None
    assert registry.get_card("unknown_operator@3.0.0") is None
    assert len(registry.list_cards()) == 36
    data = [[{"score": 1}, {"score": 3}]]
    attributes = {"operand_key": "score", "operand": ">", "operand_val": 1}
    observed = operator.run(data, attributes)
    expected = baseline.run(data, attributes)
    assert observed[0] == expected[0] == [[{"score": 3}]]
    assert observed[1] == expected[1] == {}
    assert observed[2].errors == expected[2].errors == []
    assert observed[2].is_empty is expected[2].is_empty is False


def test_operator_card_is_frozen() -> None:
    card = OperatorCard(operator_id="x@1.0.0", name="x", version="1.0.0", description="")
    with pytest.raises(dataclasses.FrozenInstanceError):
        card.name = "y"  # type: ignore[misc]


# --- lifecycle ---
def test_a_card_is_active_unless_the_caller_says_otherwise(registry: OperatorRegistry) -> None:
    card = registry.register(_op("select"), "1.0.0")
    assert card.deprecated is False
    assert registry.get_card("select@1.0.0") == card


def test_register_takes_the_lifecycle_flag_by_keyword_only(registry: OperatorRegistry) -> None:
    card = registry.register(_op("select"), "1.0.0", ["relational"], deprecated=True)
    assert card.deprecated is True
    with pytest.raises(TypeError):
        registry.register(_op("join"), "1.0.0", ["relational"], True)  # type: ignore[misc]


def test_the_lifecycle_field_is_last_and_defaulted() -> None:
    assert [f.name for f in dataclasses.fields(OperatorCard)][-1] == "deprecated"
    positional = OperatorCard("x@1.0.0", "x", "1.0.0", "", ("t",), "when")
    assert positional.deprecated is False
    assert positional == OperatorCard(
        operator_id="x@1.0.0",
        name="x",
        version="1.0.0",
        description="",
        tags=("t",),
        when_to_invoke="when",
    )


def test_public_registration_never_derives_the_flag(registry: OperatorRegistry) -> None:
    """A caller class sharing a built-in's name is still its own operator, and still active."""
    assert registry.register(_op("plan_discover"), "2.0.0").deprecated is False


def test_the_builtin_factory_deprecates_the_plan_producing_operators() -> None:
    cards = default_registry().list_cards()
    assert sorted(c.operator_id for c in cards if c.deprecated) == [
        "multipart_query@1.0.0",
        "nl2query_router@1.0.0",
        "plan_discover@1.0.0",
        "query_breakdown@1.0.0",
    ]
    assert len([c for c in cards if not c.deprecated]) == 32

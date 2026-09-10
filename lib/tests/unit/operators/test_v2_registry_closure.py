"""Dual-version registry and refinement compatibility.

The suite covers the 36-card default registry, the 75-card versioned registry,
selection behavior, and refinement at both versions.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar, cast

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
from blue_data_ops.operators import query_breakdown_operator as query_breakdown_module
from blue_data_ops.plan import DataPipeline, RefinableOperator
from blue_data_ops.plan import pipeline as pipeline_module
from tests.unit.operators._plan_operator_helpers import cte, operator_ids
from tests.unit.operators._registry_catalog_expectations import (
    ADDED_OPERATOR_IDS,
    assert_full_inventory,
    assert_legacy_cards,
)

# The 36 built-in logical operators in name order.
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
    "multipart_query",
    "nl2bn",
    "nl2llm",
    "nl2query_router",
    "nl2sql",
    "normalize_text",
    "plan_discover",
    "project",
    "query_breakdown",
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
REFINABLE_NAMES: tuple[str, ...] = (
    "multipart_query",
    "nl2query_router",
    "plan_discover",
    "query_breakdown",
)
V1_IDS: tuple[str, ...] = tuple(f"{name}@1.0.0" for name in BUILTIN_NAMES)
V2_IDS: tuple[str, ...] = tuple(f"{name}@2.0.0" for name in BUILTIN_NAMES)

INPUT: DataBundle = [[]]
NO_ATTRIBUTES: Attributes = {}
# A non-positive timeout short-circuits run()/refine() before any operator body or
# external dependency runs, while still stamping the *selected* operator id on the
# returned metadata -- a uniform, dependency-free selected-id probe for all cards.
INVALID_TIMEOUT: Properties = {"execution.timeout_seconds": 0}


def _select_deployment(
    registry: OperatorRegistry,
    operator_ids: tuple[str, ...] | None = None,
) -> tuple[OperatorCard, ...]:
    """The deployment-selection contract, expressed against a product registry.

    A `None` selection means the 36 default v2 ids; ids must be unique, resolvable,
    and carry one version per logical name; the result is name-sorted.
    """
    selected = V2_IDS if operator_ids is None else operator_ids
    if len(set(selected)) != len(selected):
        raise ValueError("deployment selection contains a repeated operator id")
    cards: list[OperatorCard] = []
    for operator_id in selected:
        registry.resolve(operator_id)  # raises ResolveError on malformed/missing ids
        card = registry.get_card(operator_id)
        if card is None:  # pragma: no cover - resolve() already guarantees presence
            raise ResolveError(f"no operator card registered as {operator_id!r}")
        cards.append(card)
    names = [card.name for card in cards]
    if len(set(names)) != len(names):
        raise ValueError("deployment selection contains multiple versions of one tool name")
    return tuple(sorted(cards, key=lambda card: card.name))


# --- 36-card v1 inventory and resolution identity -----------------------------------
def test_default_registry_v1_inventory_and_resolution_identity() -> None:
    registry = default_registry()
    cards = registry.list_cards()

    assert len(cards) == 36
    assert tuple(card.operator_id for card in cards) == V1_IDS
    assert all(card.version == "1.0.0" for card in cards)

    for name, operator_id in zip(BUILTIN_NAMES, V1_IDS, strict=True):
        resolved = registry.resolve(operator_id)
        assert resolved.operator_id == operator_id
        assert resolved.name == name


# --- 72-card dual inventory and deterministic order ---------------------------------
def test_versioned_registry_dual_inventory_and_order() -> None:
    cards = assert_legacy_cards(versioned_registry().list_cards())
    ids = [card.operator_id for card in cards]

    assert len(ids) == 72
    assert len(set(ids)) == 72
    # name-ascending, version-descending: 2.0.0 precedes 1.0.0 for each name.
    expected = [f"{name}@{version}" for name in BUILTIN_NAMES for version in ("2.0.0", "1.0.0")]
    assert ids == expected


def test_versioned_registry_full_inventory_and_order() -> None:
    assert_full_inventory(versioned_registry().list_cards())


# --- unrelated exported subclasses do not change inventory --------------------------
def test_bogus_export_cannot_change_either_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    patched_all = [*operators_package.__all__, "_BogusOperator"]
    monkeypatch.setattr(operators_package, "_BogusOperator", _BogusOperator, raising=False)
    monkeypatch.setattr(operators_package, "__all__", patched_all)

    default_cards = default_registry().list_cards()
    versioned_cards = versioned_registry().list_cards()

    assert len(default_cards) == 36
    assert len(assert_legacy_cards(versioned_cards)) == 72
    assert_full_inventory(versioned_cards)
    assert all(not card.operator_id.startswith("bogus@") for card in default_cards)
    assert all(not card.operator_id.startswith("bogus@") for card in versioned_cards)


# --- selected v2 identity through run() ---------------------------------------------
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


# --- selected v2 identity through refine() ------------------------------------------
@pytest.mark.parametrize("name", REFINABLE_NAMES)
def test_refinable_v2_card_reports_selected_id_through_refine(name: str) -> None:
    operator_id = f"{name}@2.0.0"
    resolved = cast(RefinableOperator, versioned_registry().resolve(operator_id))

    plans, meta = resolved.refine(INPUT, NO_ATTRIBUTES, INVALID_TIMEOUT)

    assert resolved.operator_id == operator_id
    assert plans == []
    assert len(meta.errors) == 1
    assert meta.errors[0].operator_id == operator_id


# --- v1 compatibility paths ---------------------------------------------------------
@pytest.mark.parametrize("name", BUILTIN_NAMES)
def test_v1_card_keeps_compatibility_path(name: str) -> None:
    operator_id = f"{name}@1.0.0"
    versioned = versioned_registry().resolve(operator_id)
    compat = default_registry().resolve(operator_id)

    assert versioned.operator_id == operator_id
    assert compat.operator_id == operator_id
    # The versioned-catalog v1 card behaves identically to the default-catalog v1 card.
    assert versioned.run(INPUT, NO_ATTRIBUTES, INVALID_TIMEOUT) == compat.run(
        INPUT, NO_ATTRIBUTES, INVALID_TIMEOUT
    )


# --- default selection from the dual-version catalog --------------------------------
def test_default_selection_yields_exactly_the_36_v2_ids() -> None:
    snapshot = _select_deployment(versioned_registry())
    ids = tuple(card.operator_id for card in snapshot)

    assert ids == V2_IDS
    assert len(ids) == 36
    assert all(operator_id.endswith("@2.0.0") for operator_id in ids)


# --- explicit empty and subset selections -------------------------------------------
def test_empty_and_subset_selections_remain_valid() -> None:
    registry = versioned_registry()

    assert _select_deployment(registry, ()) == ()

    subset = ("select@2.0.0", "join@1.0.0", "sum@2.0.0")
    snapshot = _select_deployment(registry, subset)
    assert tuple(card.operator_id for card in snapshot) == (
        "join@1.0.0",
        "select@2.0.0",
        "sum@2.0.0",
    )


def test_added_versions_are_explicitly_selectable() -> None:
    snapshot = _select_deployment(versioned_registry(), ADDED_OPERATOR_IDS)
    assert tuple(card.operator_id for card in snapshot) == ADDED_OPERATOR_IDS
    assert all(card.deprecated is False for card in snapshot)


# --- invalid selections and ids -----------------------------------------------------
def test_duplicate_ids_fail() -> None:
    with pytest.raises(ValueError, match="repeated operator id"):
        _select_deployment(versioned_registry(), ("select@2.0.0", "select@2.0.0"))


def test_two_versions_of_one_name_fail() -> None:
    with pytest.raises(ValueError, match="multiple versions of one tool name"):
        _select_deployment(versioned_registry(), ("select@2.0.0", "select@1.0.0"))


def test_missing_id_fails() -> None:
    with pytest.raises(ResolveError):
        _select_deployment(versioned_registry(), ("ghost@2.0.0",))


@pytest.mark.parametrize(
    "bad_id",
    ["select", "select@", "select@1.0", "select@01.0.0", "@2.0.0", "select@latest"],
)
def test_bare_malformed_and_leading_zero_ids_fail(bad_id: str) -> None:
    with pytest.raises(ResolveError):
        versioned_registry().resolve(bad_id)


def test_incomplete_default_catalog_fails() -> None:
    complete = versioned_registry()
    incomplete = OperatorRegistry()
    for card in complete.list_cards():
        if card.operator_id == "select@2.0.0":
            continue  # drop one required default (v2) card
        incomplete.register(complete.resolve(card.operator_id), card.version)

    with pytest.raises(ResolveError):
        _select_deployment(incomplete)


# --- v1 MCP registry isolation ------------------------------------------------------
def test_mcp_gets_v1_registry_and_no_root_versioned_export() -> None:
    # The surface the v1 MCP adapter consumes is the unchanged 36-card v1 catalog.
    cards = default_registry().list_cards()
    assert len(cards) == 36
    assert all(card.operator_id.endswith("@1.0.0") for card in cards)

    # No enriched catalog can reach the v1 MCP implicitly: versioned_registry() is
    # published only under blue_data_ops.operators, never at the root package.
    assert not hasattr(blue_data_ops, "versioned_registry")
    assert "versioned_registry" not in getattr(blue_data_ops, "__all__", ())
    from blue_data_ops.operators import versioned_registry as operators_versioned_registry

    assert callable(operators_versioned_registry)


# --- Valid selected refinement through the product factory -------------------------
# "select" discovery ranks differently by version. The raw v1 default view scores only name and
# description, so `select` (name, 10) precedes `semantic_project` (description, 5) -- two plans. The
# enriched v2 catalog also scores `when_to_invoke` and tags, so
# `semantic_project` (when 6 + description 5 = 11) outranks the `select` name hit (10), then two
# `capability-record-selection` tag hits (argmax, argmin; 8 each) follow name-ascending -- four
# plans. Both lists are asserted as exact ordered ids, never a bare count.
DISCOVER_ATTRIBUTES: Attributes = {"task": "select", "data": "rows", "approximate": True}
ROUTER_ATTRIBUTES: Attributes = {
    "search_query": "find rows",
    "columns": [{"name": "value"}],
    "execute_query": False,
    "protocol": "sqlite",
}
ROUTER_SOURCE: dict[str, Any] = {
    "name": "s",
    "type": "source",
    "scope": "/source/s",
    "properties": {"connection": {"protocol": "sqlite"}},
}
EXPECTED_PLAN_COUNTS: dict[str, int] = {
    "multipart_query": 1,
    "nl2query_router": 1,
    "plan_discover": 2,
    "query_breakdown": 1,
}
# Exact ordered discovery ids for the shared "select" query, keyed by PlanDiscover refinement
# version. v1 is the raw default view (name > description); v2 is the enriched discovery catalog
# (name/tag/when_to_invoke/description). These lists, not counts, are the discovery expectation.
DISCOVER_SELECT_IDS: dict[str, tuple[str, ...]] = {
    "1.0.0": ("select@1.0.0", "semantic_project@1.0.0"),
    "2.0.0": (
        "semantic_project@2.0.0",
        "select@2.0.0",
        "argmax@2.0.0",
        "argmin@2.0.0",
    ),
}


class _ScriptedLLMClient:
    """Deterministic double for the existing resolve_llm_client provider seam."""

    def __init__(self, result: list[list[dict[str, Any]]]) -> None:
        self._result = result

    def execute_api_call(
        self,
        input: Any,  # noqa: A002
        properties: Properties | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        del input, properties, additional_data
        return self._result


def _id_sequence() -> Callable[[], str]:
    current = 0

    def next_id() -> str:
        nonlocal current
        current += 1
        return f"closure-{current:04d}"

    return next_id


def _valid_refinement(
    registry: OperatorRegistry,
    name: str,
    version: str,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[DataPipeline], Any]:
    """Run one refinable card with a deterministic valid fixture."""
    operator = cast(RefinableOperator, registry.resolve(f"{name}@{version}"))
    if name == "multipart_query":
        return operator.refine([[cte("x")]], {})
    if name == "nl2query_router":
        return operator.refine(INPUT, {**ROUTER_ATTRIBUTES, "sources": [dict(ROUTER_SOURCE)]})
    if name == "plan_discover":
        return operator.refine(INPUT, dict(DISCOVER_ATTRIBUTES))
    assert name == "query_breakdown"
    client = _ScriptedLLMClient([[cte("base"), cte("child", dependency=["base"])]])

    def _resolve(properties: Properties) -> _ScriptedLLMClient:
        del properties
        return client

    monkeypatch.setattr(query_breakdown_module, "resolve_llm_client", _resolve)
    return operator.refine(INPUT, {"query": "q"})


@pytest.mark.parametrize("version", ["2.0.0", "1.0.0"])
@pytest.mark.parametrize("name", REFINABLE_NAMES)
def test_catalog_refinement_is_nonempty_single_version_and_resolvable(
    name: str,
    version: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = versioned_registry()

    plans, meta = _valid_refinement(registry, name, version, monkeypatch)

    assert meta.errors == []
    assert meta.is_empty is False
    observed = [operator_ids(plan.to_dict()) for plan in plans]
    if name == "plan_discover":
        # Discovery is asserted as an exact ordered id list, not a count: the raw v1 default view
        # and the enriched v2 discovery catalog rank "select" differently (see DISCOVER_SELECT_IDS).
        assert observed == [[operator_id] for operator_id in DISCOVER_SELECT_IDS[version]]
    else:
        assert len(plans) == EXPECTED_PLAN_COUNTS[name]
    for child_ids in observed:
        assert child_ids
        assert {child_id.rpartition("@")[2] for child_id in child_ids} == {version}
        for child_id in child_ids:
            assert registry.resolve(child_id).name == child_id.partition("@")[0]


def test_v2_plan_discover_discovers_from_the_product_catalog() -> None:
    registry = versioned_registry()
    operator = cast(RefinableOperator, registry.resolve("plan_discover@2.0.0"))

    plans, meta = operator.refine(INPUT, dict(DISCOVER_ATTRIBUTES))

    assert meta.errors == []
    expected = [card.operator_id for card in registry.find("select") if card.version == "2.0.0"]
    # The enriched v2 catalog scores name/tag/when_to_invoke/description: semantic_project
    # (when_to_invoke + description) outranks the select name hit, then two
    # capability-record-selection tag hits, name-ascending. Exact order is pinned, not a count.
    assert expected == list(DISCOVER_SELECT_IDS["2.0.0"])
    # One starter plan per matching v2 card, in the catalog's find() order.
    assert [operator_ids(plan.to_dict()) for plan in plans] == [
        [operator_id] for operator_id in expected
    ]


def test_v1_plan_discover_raw_refiner_stays_v1_and_matches_default_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_operator = cast(RefinableOperator, versioned_registry().resolve("plan_discover@1.0.0"))
    compat_operator = cast(RefinableOperator, default_registry().resolve("plan_discover@1.0.0"))

    monkeypatch.setattr(pipeline_module, "_new_id", _id_sequence())
    catalog_plans = catalog_operator.refiner(INPUT, dict(DISCOVER_ATTRIBUTES))
    monkeypatch.setattr(pipeline_module, "_new_id", _id_sequence())
    compat_plans = compat_operator.refiner(INPUT, dict(DISCOVER_ATTRIBUTES))

    assert catalog_plans == compat_plans
    assert len(catalog_plans) == EXPECTED_PLAN_COUNTS["plan_discover"]
    # The raw v1 view keeps its two-plan default expectation, in exact score order.
    assert [operator_ids(record) for record in catalog_plans] == [
        [operator_id] for operator_id in DISCOVER_SELECT_IDS["1.0.0"]
    ]
    for record in catalog_plans:
        child_ids = operator_ids(record)
        assert child_ids
        assert {child_id.rpartition("@")[2] for child_id in child_ids} == {"1.0.0"}


def test_catalog_plan_discover_instances_stay_separate_and_isolated() -> None:
    registry = versioned_registry()
    v2_operator = registry.resolve("plan_discover@2.0.0")
    v1_operator = registry.resolve("plan_discover@1.0.0")

    assert v2_operator is not v1_operator
    assert v2_operator.operator_id == "plan_discover@2.0.0"
    assert v1_operator.operator_id == "plan_discover@1.0.0"
    v2_operator.properties["closure-isolation-marker"] = "v2"
    assert "closure-isolation-marker" not in v1_operator.properties

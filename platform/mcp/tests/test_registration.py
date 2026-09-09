from __future__ import annotations

from typing import Any, ClassVar

import pytest
from blue_data_ops.operators import (
    AttributeSpec,
    MultipartQueryOperator,
    Operator,
    OperatorCard,
    OperatorRegistry,
    ResolveError,
    versioned_registry,
)
from blue_data_ops.plan import RefinableOperator
from blue_data_ops.plan.types import PlanRecord

from blue_data_ops_mcp.registration import (
    REFINE_SUFFIX,
    V2_OPERATOR_IDS,
    DeploymentSnapshot,
    OperatorBinding,
    freeze_deployment,
    register_snapshot,
)
from blue_data_ops_mcp.server import create_server

REFINE_NAMES = (
    "multipart_query__refine",
    "nl2query_router__refine",
    "plan_discover__refine",
    "query_breakdown__refine",
)
# The eight tools the default deployment annotates, written out rather than derived, so a change
# in how the adapter decides has to be reconciled against a fixed list.
ANNOTATED_DEFAULT_NAMES = frozenset(
    {
        "multipart_query",
        "nl2query_router",
        "plan_discover",
        "query_breakdown",
        "multipart_query__refine",
        "nl2query_router__refine",
        "plan_discover__refine",
        "query_breakdown__refine",
    }
)
PRIMARY_SENTENCE = "Deprecated in blue-data-ops 2.8.0; removed in 3.0.0."
COMPANION_SENTENCE = (
    "Deprecated in blue-data-ops 2.8.0; removed in 3.0.0. "
    "The refinement seam is deprecated for every operator."
)


class EchoOperator(Operator):
    name: ClassVar[str] = "echo"
    description: ClassVar[str] = "Return the supplied attributes."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        del input_data, properties
        return [[attributes]]


class RetainedRefiner(RefinableOperator):
    name: ClassVar[str] = "retained_refiner"
    description: ClassVar[str] = "Return no refinement plan."
    attributes: ClassVar[dict[str, AttributeSpec]] = {}

    def apply(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[list[dict[str, Any]]]:
        del input_data, attributes, properties
        return [[]]

    def refiner(
        self,
        input_data: list[list[dict[str, Any]]],
        attributes: dict[str, Any],
        properties: dict[str, Any] | None = None,
    ) -> list[PlanRecord]:
        del input_data, attributes, properties
        return []


class MismatchRegistry(OperatorRegistry):
    """Return a card whose logical name disagrees with the resolved operator."""

    def __init__(self) -> None:
        super().__init__()
        self._base = versioned_registry()
        self._echo = EchoOperator()

    def list_cards(self) -> list[OperatorCard]:
        return self._base.list_cards()

    def resolve(self, operator_id: str) -> Operator:
        if operator_id == "select@2.0.0":
            return self._echo
        return self._base.resolve(operator_id)

    def get_card(self, operator_id: str) -> OperatorCard | None:
        return self._base.get_card(operator_id)


class DuplicateNameRegistry(OperatorRegistry):
    """Expose two distinct 2.0.0 ids that share one logical name."""

    def __init__(self) -> None:
        super().__init__()
        self._base = versioned_registry()
        self._alt = EchoOperator()
        self._alt_card = OperatorCard("select_alt@2.0.0", "select", "2.0.0", "alternate select")

    def list_cards(self) -> list[OperatorCard]:
        return self._base.list_cards()

    def resolve(self, operator_id: str) -> Operator:
        if operator_id == self._alt_card.operator_id:
            return self._alt
        return self._base.resolve(operator_id)

    def get_card(self, operator_id: str) -> OperatorCard | None:
        if operator_id == self._alt_card.operator_id:
            return self._alt_card
        return self._base.get_card(operator_id)


class SubstituteCardRegistry(OperatorRegistry):
    """Serve a *different* valid card than the requested id names.

    `resolve` stays honest and every served card is a genuine, otherwise-acceptable catalog card;
    only `get_card(requested_id)` lies, returning the card registered under `served_id`. This is the
    exact card-substitution the freeze must reject: the requested id must stay bound to its own card
    through validation, so a swapped-in card can neither pass the version gate nor reach a tool.
    """

    def __init__(self, requested_id: str, served_id: str) -> None:
        super().__init__()
        self._base = versioned_registry()
        self._requested_id = requested_id
        self._served_id = served_id

    def list_cards(self) -> list[OperatorCard]:
        return self._base.list_cards()

    def resolve(self, operator_id: str) -> Operator:
        return self._base.resolve(operator_id)

    def get_card(self, operator_id: str) -> OperatorCard | None:
        if operator_id == self._requested_id:
            return self._base.get_card(self._served_id)
        return self._base.get_card(operator_id)


def _split(snapshot: DeploymentSnapshot) -> tuple[list[OperatorBinding], list[OperatorBinding]]:
    primaries = [binding for binding in snapshot if binding.kind == "primary"]
    companions = [binding for binding in snapshot if binding.kind == "refine"]
    return primaries, companions


def _tool_names(snapshot: DeploymentSnapshot) -> list[str]:
    return [
        binding.card.name if binding.kind == "primary" else f"{binding.card.name}{REFINE_SUFFIX}"
        for binding in snapshot
    ]


async def test_default_inventory_is_40_tools_in_pinned_order() -> None:
    server = create_server()
    first = await server.list_tools()
    second = await server.list_tools()
    assert first == second  # repeated listing is definition-identical
    names = [tool.name for tool in first]
    primaries = [operator_id.partition("@")[0] for operator_id in V2_OPERATOR_IDS]
    assert names == list(primaries) + list(REFINE_NAMES)
    assert primaries == sorted(primaries)
    assert list(REFINE_NAMES) == sorted(REFINE_NAMES)
    assert len(names) == 40


def test_default_snapshot_binds_the_36_v2_ids_without_inventory_equality() -> None:
    snapshot = freeze_deployment(versioned_registry())
    primaries, companions = _split(snapshot)
    assert tuple(binding.card.operator_id for binding in primaries) == tuple(
        sorted(V2_OPERATOR_IDS, key=lambda oid: oid.partition("@")[0])
    )
    assert all(binding.card.version == "2.0.0" for binding in snapshot)
    assert [binding.card.name for binding in companions] == list(
        name.removesuffix(REFINE_SUFFIX) for name in REFINE_NAMES
    )
    # every companion is the same instance as its primary (one dispatch target per operator)
    by_name = {binding.card.name: binding.operator for binding in primaries}
    for binding in companions:
        assert binding.operator is by_name[binding.card.name]


def test_registry_superset_is_accepted() -> None:
    registry = versioned_registry()
    registry.register(EchoOperator(), "3.0.0")  # an unrelated later version
    snapshot = freeze_deployment(registry)
    assert _tool_names(snapshot) == [
        operator_id.partition("@")[0] for operator_id in V2_OPERATOR_IDS
    ] + list(REFINE_NAMES)
    assert all(binding.card.operator_id in V2_OPERATOR_IDS for binding in snapshot)


def test_explicit_selection_replaces_default_and_sorts() -> None:
    assert freeze_deployment(operator_ids=()) == ()
    snapshot = freeze_deployment(operator_ids=("select@2.0.0", "argmax@2.0.0"))
    primaries, companions = _split(snapshot)
    assert [binding.card.name for binding in primaries] == ["argmax", "select"]
    assert companions == []  # neither is refinable → no companion


def test_selection_adds_companions_only_for_selected_refinables() -> None:
    snapshot = freeze_deployment(
        operator_ids=("select@2.0.0", "multipart_query@2.0.0", "avg@2.0.0")
    )
    assert _tool_names(snapshot) == ["avg", "multipart_query", "select", "multipart_query__refine"]


@pytest.mark.parametrize(
    "operator_ids,error_type",
    [
        (("select@2.0.0", "select@2.0.0"), ValueError),  # repeated id
        (("missing@2.0.0",), ResolveError),  # unknown id
        (("select",), ResolveError),  # bare name
        (("select@01.0.0",), ResolveError),  # leading-zero version
    ],
)
def test_malformed_or_repeated_selections_fail_before_construction(
    operator_ids: tuple[str, ...],
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        freeze_deployment(operator_ids=operator_ids)
    # a failed freeze constructs no server (freeze precedes FastMCP construction)
    with pytest.raises(error_type):
        create_server(operator_ids=operator_ids)


def test_two_versions_of_one_name_fail() -> None:
    # Two distinct 2.0.0 ids that resolve to one logical name are rejected. (A 1.0.0 duplicate is
    # rejected earlier by the v2-only check, so the name-uniqueness branch needs same-version ids.)
    with pytest.raises(ValueError, match="multiple versions"):
        freeze_deployment(DuplicateNameRegistry(), ("select@2.0.0", "select_alt@2.0.0"))


def test_non_v2_selection_is_rejected() -> None:
    with pytest.raises(ValueError, match="2.0.0 only"):
        freeze_deployment(operator_ids=("select@1.0.0",))
    with pytest.raises(ValueError, match="2.0.0 only"):
        create_server(operator_ids=("select@1.0.0",))


def test_card_operator_mismatch_fails_before_server() -> None:
    with pytest.raises(ValueError, match="mismatch"):
        freeze_deployment(MismatchRegistry(), ("select@2.0.0",))


def test_selected_v2_id_cannot_be_served_a_different_v2_card() -> None:
    # A registry returns the real avg@2.0.0 card for a select@2.0.0 lookup. The substitute is itself
    # a valid 2.0.0 card, so only the requested-id binding — not the version or malformed gate — can
    # catch the swap. It must be rejected before any server is built (no avg tool under `select`).
    registry = SubstituteCardRegistry("select@2.0.0", "avg@2.0.0")
    served = registry.get_card("select@2.0.0")
    assert served is not None
    assert served.operator_id == "avg@2.0.0" and served.version == "2.0.0"
    with pytest.raises(ValueError, match="requested id"):
        freeze_deployment(registry, ("select@2.0.0",))
    with pytest.raises(ValueError, match="requested id"):
        create_server(registry=registry, operator_ids=("select@2.0.0",))


def test_selected_non_v2_id_cannot_be_served_a_v2_card() -> None:
    # A selected 1.0.0 id is served a valid 2.0.0 card. Without the requested-id binding the 2.0.0
    # substitute would pass the version gate and smuggle a v2 tool in under a v1 selection; the
    # binding check rejects it atomically, before FastMCP construction.
    registry = SubstituteCardRegistry("select@1.0.0", "avg@2.0.0")
    served = registry.get_card("select@1.0.0")
    assert served is not None
    assert served.operator_id == "avg@2.0.0" and served.version == "2.0.0"
    with pytest.raises(ValueError, match="requested id"):
        freeze_deployment(registry, ("select@1.0.0",))
    with pytest.raises(ValueError, match="requested id"):
        create_server(registry=registry, operator_ids=("select@1.0.0",))


def test_register_snapshot_binds_primary_and_companion_metadata() -> None:
    from mcp.server.fastmcp import FastMCP

    refinable = MultipartQueryOperator()
    card = OperatorCard(
        "multipart_query@2.0.0",
        "multipart_query",
        "2.0.0",
        refinable.description,
        ("domain-plan", "flow-plan"),
        "when to invoke text",
    )
    snapshot: DeploymentSnapshot = (
        OperatorBinding(card=card, operator=refinable, kind="primary"),
        OperatorBinding(card=card, operator=refinable, kind="refine"),
    )
    server: FastMCP[Any] = FastMCP("test")
    register_snapshot(server, snapshot)

    tools = server._tool_manager.list_tools()  # pyright: ignore[reportPrivateUsage]
    assert [tool.name for tool in tools] == ["multipart_query", "multipart_query__refine"]
    # The hand-made card is retained, so the primary stays unannotated and the companion is
    # annotated by its kind alone.
    assert tools[0].meta == {
        "operator_id": "multipart_query@2.0.0",
        "version": "2.0.0",
        "tags": ["domain-plan", "flow-plan"],
    }
    assert tools[1].meta == {
        "operator_id": "multipart_query@2.0.0",
        "version": "2.0.0",
        "tags": ["domain-plan", "flow-plan"],
        "deprecated": True,
    }
    # composed description; companion prefixes the fixed refinement and lifecycle sentences
    assert tools[0].description == f"when to invoke text\n\n{refinable.description}"
    assert tools[1].description == (
        "Build candidate data-pipeline plans.\n\n"
        "Deprecated in blue-data-ops 2.8.0; removed in 3.0.0. The refinement seam is deprecated "
        "for every operator.\n\n"
        f"when to invoke text\n\n{refinable.description}"
    )


# Lifecycle annotation


def _meta_of(tool: Any) -> dict[str, Any]:
    meta: dict[str, Any] = tool.meta or {}
    return meta


def _annotated_names(tools: list[Any]) -> set[str]:
    return {tool.name for tool in tools if _meta_of(tool).get("deprecated") is True}


async def test_default_surface_annotates_the_four_pairs_and_nothing_else() -> None:
    tools = await create_server().list_tools()
    assert len(tools) == 40
    assert _annotated_names(tools) == set(ANNOTATED_DEFAULT_NAMES)
    # a retained tool carries no lifecycle key at all, rather than a false one
    for tool in tools:
        if tool.name not in ANNOTATED_DEFAULT_NAMES:
            assert "deprecated" not in (tool.meta or {})


async def test_the_32_retained_primaries_keep_their_description_and_metadata() -> None:
    tools = {tool.name: tool for tool in await create_server().list_tools()}
    cards = {card.operator_id: card for card in versioned_registry().list_cards()}
    retained = [
        cards[operator_id] for operator_id in V2_OPERATOR_IDS if not cards[operator_id].deprecated
    ]
    assert len(retained) == 32
    for card in retained:
        tool = tools[card.name]
        assert tool.description == f"{card.when_to_invoke}\n\n{card.description}"
        assert tool.meta == {
            "operator_id": card.operator_id,
            "version": "2.0.0",
            "tags": list(card.tags),
        }


async def test_deprecated_primaries_prepend_the_lifecycle_sentence() -> None:
    tools = {tool.name: tool for tool in await create_server().list_tools()}
    cards = {card.operator_id: card for card in versioned_registry().list_cards()}
    for name in ("multipart_query", "nl2query_router", "plan_discover", "query_breakdown"):
        card = cards[f"{name}@2.0.0"]
        assert tools[name].description == (
            f"{PRIMARY_SENTENCE}\n\n{card.when_to_invoke}\n\n{card.description}"
        )
        assert tools[name].meta == {
            "operator_id": f"{name}@2.0.0",
            "version": "2.0.0",
            "tags": list(card.tags),
            "deprecated": True,
        }


async def test_every_companion_states_that_the_seam_is_deprecated() -> None:
    tools = {tool.name: tool for tool in await create_server().list_tools()}
    cards = {card.operator_id: card for card in versioned_registry().list_cards()}
    for name in REFINE_NAMES:
        card = cards[f"{name.removesuffix(REFINE_SUFFIX)}@2.0.0"]
        assert tools[name].description == (
            "Build candidate data-pipeline plans.\n\n"
            f"{COMPANION_SENTENCE}\n\n{card.when_to_invoke}\n\n{card.description}"
        )
        assert (tools[name].meta or {})["deprecated"] is True


async def test_a_retained_custom_refinable_annotates_its_companion_only() -> None:
    registry = versioned_registry()
    registry.register(RetainedRefiner(), "2.0.0", when_to_invoke="when to invoke text")
    server = create_server(
        registry=registry,
        operator_ids=(*V2_OPERATOR_IDS, "retained_refiner@2.0.0"),
    )
    tools = await server.list_tools()
    assert len(tools) == 42
    annotated = _annotated_names(tools)
    assert annotated == set(ANNOTATED_DEFAULT_NAMES) | {"retained_refiner__refine"}
    assert len(annotated) == 9

    by_name = {tool.name: tool for tool in tools}
    assert by_name["retained_refiner"].meta == {
        "operator_id": "retained_refiner@2.0.0",
        "version": "2.0.0",
        "tags": [],
    }
    assert by_name["retained_refiner"].description == (
        "when to invoke text\n\nReturn no refinement plan."
    )
    assert by_name["retained_refiner__refine"].meta == {
        "operator_id": "retained_refiner@2.0.0",
        "version": "2.0.0",
        "tags": [],
        "deprecated": True,
    }
    assert by_name["retained_refiner__refine"].description == (
        "Build candidate data-pipeline plans.\n\n"
        f"{COMPANION_SENTENCE}\n\n"
        "when to invoke text\n\nReturn no refinement plan."
    )


async def test_a_custom_primary_registered_deprecated_is_annotated() -> None:
    registry = versioned_registry()
    registry.register(EchoOperator(), "2.0.0", ("legacy",), deprecated=True)
    [tool] = await create_server(registry=registry, operator_ids=("echo@2.0.0",)).list_tools()
    assert tool.name == "echo"
    # `echo` declares no invocation guidance, so the sentence sits directly on the description
    assert tool.description == f"{PRIMARY_SENTENCE}\n\nReturn the supplied attributes."
    assert tool.meta == {
        "operator_id": "echo@2.0.0",
        "version": "2.0.0",
        "tags": ["legacy"],
        "deprecated": True,
    }


async def test_no_partial_registration_on_failure() -> None:
    # a valid build after a rejected one yields exactly the 40-tool surface (no residue)
    with pytest.raises(ValueError):
        create_server(operator_ids=("select@1.0.0",))
    server = create_server()
    assert len(await server.list_tools()) == 40

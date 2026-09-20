from __future__ import annotations

from dataclasses import replace
from typing import Any, ClassVar

import pytest
from blue_data_ops.operators import (
    AttributeSpec,
    Operator,
    OperatorCard,
    OperatorRegistry,
    ResolveError,
    default_registry,
    versioned_registry,
)
from blue_data_ops.operators.registry import is_reviewed_builtin_card
from mcp.server.fastmcp import FastMCP

import blue_data_ops_mcp.registration as registration
from blue_data_ops_mcp.registration import (
    ACTIVE_OPERATOR_IDS,
    DEPRECATION_SENTENCE,
    TOOL_PREFIX,
    V2_OPERATOR_IDS,
    DeploymentSnapshot,
    OperatorBinding,
    freeze_deployment,
    register_snapshot,
    tool_name,
)
from blue_data_ops_mcp.server import create_server

EXPECTED_ACTIVE_OPERATOR_IDS = (
    "argmax@2.0.0",
    "argmin@2.0.0",
    "avg@3.0.0",
    "classify@3.0.0",
    "cluster@3.0.0",
    "create_database@2.0.0",
    "create_table@2.0.0",
    "data_discover@2.0.0",
    "delete@2.0.0",
    "insert@3.0.0",
    "insert_table@3.0.0",
    "intersect@3.0.0",
    "join@3.0.0",
    "max@3.0.0",
    "min@3.0.0",
    "nl2bn@3.0.0",
    "nl2llm@3.0.0",
    "nl2sql@3.0.0",
    "normalize_text@2.0.0",
    "project@3.0.0",
    "segment_text@2.0.0",
    "select@2.0.0",
    "semantic_extract@3.0.0",
    "semantic_filter@3.0.0",
    "semantic_join@3.0.0",
    "semantic_project@3.0.0",
    "semantic_transform@3.0.0",
    "sklearn_estimator@2.0.0",
    "sum@2.0.0",
    "union@2.0.0",
    "vector_embed@3.0.0",
    "vector_search@3.0.0",
    "vector_similarity@3.0.0",
)

# The served wire names, pinned literally rather than derived, so a change to the prefix or
# to one logical name has to be made here as well as at the registration site.
EXPECTED_TOOL_NAMES = [
    "ops_argmax",
    "ops_argmin",
    "ops_avg",
    "ops_classify",
    "ops_cluster",
    "ops_create_database",
    "ops_create_table",
    "ops_data_discover",
    "ops_delete",
    "ops_insert",
    "ops_insert_table",
    "ops_intersect",
    "ops_join",
    "ops_max",
    "ops_min",
    "ops_nl2bn",
    "ops_nl2llm",
    "ops_nl2sql",
    "ops_normalize_text",
    "ops_project",
    "ops_segment_text",
    "ops_select",
    "ops_semantic_extract",
    "ops_semantic_filter",
    "ops_semantic_join",
    "ops_semantic_project",
    "ops_semantic_transform",
    "ops_sklearn_estimator",
    "ops_sum",
    "ops_union",
    "ops_vector_embed",
    "ops_vector_search",
    "ops_vector_similarity",
]

EXPECTED_V2_OPERATOR_IDS = tuple(
    f"{operator_id.partition('@')[0]}@2.0.0" for operator_id in EXPECTED_ACTIVE_OPERATOR_IDS
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


class FakeSelectOperator(EchoOperator):
    name: ClassVar[str] = "select"


class CallerMultipartOperator(EchoOperator):
    name: ClassVar[str] = "multipart_query"


class SubstituteCardRegistry(OperatorRegistry):
    def __init__(self, requested_id: str, served_id: str) -> None:
        super().__init__()
        self._base = versioned_registry()
        self._requested_id = requested_id
        self._served_id = served_id

    def resolve(self, operator_id: str) -> Operator:
        return self._base.resolve(operator_id)

    def get_card(self, operator_id: str) -> OperatorCard | None:
        if operator_id == self._requested_id:
            return self._base.get_card(self._served_id)
        return self._base.get_card(operator_id)


def _ids(snapshot: DeploymentSnapshot) -> tuple[str, ...]:
    return tuple(binding.card.operator_id for binding in snapshot)


def test_selection_constants_are_exact_name_unique_contracts() -> None:
    assert ACTIVE_OPERATOR_IDS == EXPECTED_ACTIVE_OPERATOR_IDS
    assert V2_OPERATOR_IDS == EXPECTED_V2_OPERATOR_IDS
    assert len(ACTIVE_OPERATOR_IDS) == len(V2_OPERATOR_IDS) == 33
    assert len({value.partition("@")[0] for value in ACTIVE_OPERATOR_IDS}) == 33
    assert len(set(ACTIVE_OPERATOR_IDS)) == len(set(V2_OPERATOR_IDS)) == 33
    assert [value.partition("@")[0] for value in ACTIVE_OPERATOR_IDS] == sorted(
        value.partition("@")[0] for value in ACTIVE_OPERATOR_IDS
    )
    assert sum(value.endswith("@3.0.0") for value in ACTIVE_OPERATOR_IDS) == 21
    assert sum(value.endswith("@2.0.0") for value in ACTIVE_OPERATOR_IDS) == 12


async def test_default_inventory_is_33_active_primaries_in_order() -> None:
    first = await create_server().list_tools()
    second = await create_server().list_tools()
    assert [tool.name for tool in first] == EXPECTED_TOOL_NAMES
    assert [tool.name for tool in second] == EXPECTED_TOOL_NAMES
    assert [(tool.meta or {})["operator_id"] for tool in first] == list(ACTIVE_OPERATOR_IDS)
    assert not any(tool.name.endswith("__refine") for tool in first)


async def test_every_served_name_carries_the_prefix_and_no_bare_name_survives() -> None:
    tools = await create_server().list_tools()
    logical_names = [operator_id.partition("@")[0] for operator_id in ACTIVE_OPERATOR_IDS]
    assert len(EXPECTED_TOOL_NAMES) == 33
    assert EXPECTED_TOOL_NAMES == [tool_name(name) for name in logical_names]
    served = {tool.name for tool in tools}
    assert served.isdisjoint(logical_names)
    for tool in tools:
        assert tool.name.startswith(TOOL_PREFIX)
        # The prefix is the adapter's; `_meta.operator_id` stays the core library's own id.
        assert (tool.meta or {})["operator_id"].partition("@")[0] == tool.name[len(TOOL_PREFIX) :]


def test_default_snapshot_binds_exact_active_instances() -> None:
    registry = versioned_registry()
    snapshot = freeze_deployment(registry)
    assert _ids(snapshot) == ACTIVE_OPERATOR_IDS
    for binding in snapshot:
        assert binding.operator is registry.resolve(binding.card.operator_id)
        assert registry.get_card(binding.card.operator_id) is binding.card


def test_registry_superset_does_not_leak() -> None:
    registry = versioned_registry()
    registry.register(EchoOperator(), "2.0.0")
    snapshot = freeze_deployment(registry)
    assert _ids(snapshot) == ACTIVE_OPERATOR_IDS
    assert all(binding.card.name != "echo" for binding in snapshot)


async def test_explicit_selection_replaces_default_sorts_and_preserves_empty() -> None:
    assert freeze_deployment(operator_ids=()) == ()
    empty_server = create_server(operator_ids=())
    assert await empty_server.list_tools() == []

    snapshot = freeze_deployment(operator_ids=("select@2.0.0", "avg@3.0.0"))
    assert _ids(snapshot) == ("avg@3.0.0", "select@2.0.0")
    tools = await create_server(operator_ids=("select@2.0.0", "avg@3.0.0")).list_tools()
    assert [tool.name for tool in tools] == ["ops_avg", "ops_select"]


def test_explicit_retained_v2_selection_is_supported() -> None:
    assert _ids(freeze_deployment(operator_ids=V2_OPERATOR_IDS)) == V2_OPERATOR_IDS


async def test_explicit_raw_v2_package_registry_is_execution_only() -> None:
    registry = default_registry(select="2.0.0")
    card = registry.get_card("select@2.0.0")
    assert card is not None
    assert card.tags == ()
    assert card.when_to_invoke == ""
    assert not is_reviewed_builtin_card(registry, card)

    [binding] = freeze_deployment(registry, (card.operator_id,))
    assert binding.card is card
    assert binding.operator is registry.resolve(card.operator_id)

    [tool] = await create_server(registry=registry, operator_ids=(card.operator_id,)).list_tools()
    assert tool.meta == {
        "operator_id": "select@2.0.0",
        "version": "2.0.0",
        "tags": [],
    }
    assert tool.description == card.description


@pytest.mark.parametrize(
    "operator_ids,error_type,message",
    [
        (("select@2.0.0", "select@2.0.0"), ValueError, "repeated operator id"),
        (("missing@2.0.0",), ResolveError, "no operator card"),
        (("select",), ResolveError, "no operator card"),
        (("select@01.0.0",), ResolveError, "no operator card"),
        (("select@1.0.0",), ValueError, "v2/v3"),
    ],
)
def test_bad_selection_fails_before_server(
    operator_ids: tuple[str, ...],
    error_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error_type, match=message):
        freeze_deployment(operator_ids=operator_ids)
    with pytest.raises(error_type, match=message):
        create_server(operator_ids=operator_ids)


def test_duplicate_logical_name_fails_closed() -> None:
    with pytest.raises(ValueError, match="multiple versions"):
        freeze_deployment(operator_ids=("avg@2.0.0", "avg@3.0.0"))


def test_returned_card_substitution_fails_closed() -> None:
    registry = SubstituteCardRegistry("select@2.0.0", "avg@2.0.0")
    with pytest.raises(ValueError, match="requested id"):
        freeze_deployment(registry, ("select@2.0.0",))


def test_requested_card_version_mismatch_fails_closed() -> None:
    registry = versioned_registry()
    card = registry.get_card("select@2.0.0")
    assert card is not None
    registry._cards[card.operator_id] = replace(  # pyright: ignore[reportPrivateUsage]
        card, version="3.0.0"
    )
    with pytest.raises(ValueError, match="requested/card identity mismatch"):
        freeze_deployment(registry, ("select@2.0.0",))


def test_copied_builtin_card_fails_provenance() -> None:
    copied = versioned_registry().get_card("select@2.0.0")
    assert copied is not None

    class CopiedCardRegistry(OperatorRegistry):
        def __init__(self) -> None:
            super().__init__()
            self._base = versioned_registry()

        def resolve(self, operator_id: str) -> Operator:
            return self._base.resolve(operator_id)

        def get_card(self, operator_id: str) -> OperatorCard | None:
            return copied if operator_id == copied.operator_id else None

    with pytest.raises(ValueError, match="provenance mismatch"):
        freeze_deployment(CopiedCardRegistry(), ("select@2.0.0",))


def test_publicly_registered_builtin_identity_fails_provenance() -> None:
    registry = OperatorRegistry()
    registry.register(FakeSelectOperator(), "2.0.0")
    with pytest.raises(ValueError, match="provenance mismatch"):
        freeze_deployment(registry, ("select@2.0.0",))


def test_resolved_implementation_substitution_with_same_id_fails_closed() -> None:
    registry = versioned_registry()
    replacement_registry = OperatorRegistry()
    replacement_registry.register(FakeSelectOperator(), "2.0.0")
    replacement = replacement_registry.resolve("select@2.0.0")
    registry._operators["select@2.0.0"] = replacement  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(ValueError, match="implementation mismatch"):
        freeze_deployment(registry, ("select@2.0.0",))


def test_missing_retired_package_builtin_fails_resolution() -> None:
    with pytest.raises(
        ResolveError, match="no operator card registered as 'multipart_query@2.0.0'"
    ):
        freeze_deployment(versioned_registry(), ("multipart_query@2.0.0",))


def test_unsupported_package_builtin_and_custom_v3_fail() -> None:
    with pytest.raises(ValueError, match="supports exact v2/v3 selections only"):
        freeze_deployment(versioned_registry(), ("avg@1.0.0",))

    registry = OperatorRegistry()
    registry.register(EchoOperator(), "3.0.0")
    with pytest.raises(ValueError, match="custom operators are supported at 2.0.0 only"):
        freeze_deployment(registry, ("echo@3.0.0",))


async def test_custom_v2_and_generic_deprecated_metadata_are_preserved() -> None:
    registry = OperatorRegistry()
    registry.register(
        CallerMultipartOperator(),
        "2.0.0",
        ("caller",),
        when_to_invoke="Use for caller-owned echo work.",
        deprecated=True,
    )
    [tool] = await create_server(
        registry=registry, operator_ids=("multipart_query@2.0.0",)
    ).list_tools()
    assert tool.name == "ops_multipart_query"
    assert tool.meta == {
        "operator_id": "multipart_query@2.0.0",
        "version": "2.0.0",
        "tags": ["caller"],
        "deprecated": True,
    }
    assert tool.description == (
        f"{DEPRECATION_SENTENCE}\n\n"
        "Use for caller-owned echo work.\n\nReturn the supplied attributes."
    )
    assert "2.8.0" not in (tool.description or "")
    assert "removed in 3.0.0" not in (tool.description or "")


def test_register_snapshot_binds_only_primaries() -> None:
    registry = OperatorRegistry()
    card = registry.register(EchoOperator(), "2.0.0", when_to_invoke="Use echo.")
    selected = registry.resolve(card.operator_id)
    snapshot: DeploymentSnapshot = (OperatorBinding(card=card, operator=selected),)
    server: FastMCP[Any] = FastMCP("test")
    register_snapshot(server, snapshot)
    [tool] = server._tool_manager.list_tools()  # pyright: ignore[reportPrivateUsage]
    assert tool.name == "ops_echo"
    assert tool.description == "Use echo.\n\nReturn the supplied attributes."
    assert not tool.name.endswith("__refine")


def test_refinement_api_is_absent() -> None:
    for name in (
        "REFINE_SUFFIX",
        "REFINE_DESCRIPTION_PREFIX",
        "REFINE_DEPRECATION_SENTENCE",
        "make_refine_handler",
        "refine_payload",
    ):
        assert not hasattr(registration, name)
    assert set(OperatorBinding.__dataclass_fields__) == {"card", "operator"}


async def test_no_partial_registration_after_failure() -> None:
    with pytest.raises(ValueError):
        create_server(operator_ids=("select@1.0.0",))
    assert len(await create_server().list_tools()) == 33

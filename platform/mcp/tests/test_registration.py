from __future__ import annotations

from typing import Any, ClassVar

import pytest
from blue_data_ops.operators import (
    AttributeSpec,
    Operator,
    OperatorCard,
    OperatorRegistry,
    ResolveError,
    default_registry,
)

from blue_data_ops_mcp.registration import (
    DEFAULT_OPERATOR_IDS,
    OperatorBinding,
    freeze_deployment,
    register_snapshot,
)
from blue_data_ops_mcp.server import create_server


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


class MultiVersionSelectionRegistry(OperatorRegistry):
    def __init__(self) -> None:
        super().__init__()
        self._base = default_registry()
        self._alternate = EchoOperator()
        self._alternate.name = "select"  # type: ignore[misc]
        self._alternate_card = OperatorCard(
            "select@2.0.0",
            "select",
            "2.0.0",
            "Alternate select",
        )

    def list_cards(self) -> list[OperatorCard]:
        return self._base.list_cards()

    def resolve(self, operator_id: str) -> Operator:
        if operator_id == self._alternate_card.operator_id:
            return self._alternate
        return self._base.resolve(operator_id)

    def get_card(self, operator_id: str) -> OperatorCard | None:
        if operator_id == self._alternate_card.operator_id:
            return self._alternate_card
        return self._base.get_card(operator_id)


def test_default_snapshot_is_exact_and_instance_pinned() -> None:
    registry = default_registry()
    snapshot = freeze_deployment(registry)
    assert len(DEFAULT_OPERATOR_IDS) == 36
    assert tuple(binding.card.operator_id for binding in snapshot) == DEFAULT_OPERATOR_IDS
    assert tuple(binding.card.name for binding in snapshot) == tuple(
        sorted(binding.card.name for binding in snapshot)
    )
    assert {
        "multipart_query@1.0.0",
        "nl2query_router@1.0.0",
        "plan_discover@1.0.0",
        "query_breakdown@1.0.0",
    } <= set(DEFAULT_OPERATOR_IDS)
    for binding in snapshot:
        assert registry.resolve(binding.card.operator_id) is binding.operator


def test_explicit_selection_replaces_default_and_sorts() -> None:
    snapshot = freeze_deployment(
        operator_ids=("select@1.0.0", "argmax@1.0.0"),
    )
    assert [binding.card.name for binding in snapshot] == ["argmax", "select"]
    assert freeze_deployment(operator_ids=()) == ()


@pytest.mark.parametrize(
    "operator_ids,error_type",
    [
        (("select@1.0.0", "select@1.0.0"), ValueError),
        (("select",), ResolveError),
        (("select@01.0.0",), ResolveError),
        (("missing@1.0.0",), ResolveError),
    ],
)
def test_bad_selections_fail_before_server_construction(
    operator_ids: tuple[str, ...],
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        create_server(operator_ids=operator_ids)


def test_inventory_drift_fails_even_for_explicit_subset() -> None:
    registry = default_registry()
    registry.register(EchoOperator(), "1.0.0")
    with pytest.raises(ValueError, match="inventory"):
        freeze_deployment(registry, ("select@1.0.0",))


def test_same_logical_name_at_two_versions_fails_before_registration() -> None:
    registry = MultiVersionSelectionRegistry()
    with pytest.raises(ValueError, match="multiple versions"):
        freeze_deployment(registry, ("select@1.0.0", "select@2.0.0"))


def test_register_snapshot_preserves_card_metadata_and_closure_binding() -> None:
    from mcp.server.fastmcp import FastMCP

    first = EchoOperator()
    second = EchoOperator()
    first.name = "first"  # type: ignore[misc]
    second.name = "second"  # type: ignore[misc]
    snapshot = (
        OperatorBinding(
            OperatorCard("first@1.0.0", "first", "1.0.0", "First", ("a",)),
            first,
        ),
        OperatorBinding(
            OperatorCard("second@1.0.0", "second", "1.0.0", "Second", ("b", "c")),
            second,
        ),
    )
    server: FastMCP[Any] = FastMCP("test")
    register_snapshot(server, snapshot)

    tools = server._tool_manager.list_tools()  # pyright: ignore[reportPrivateUsage]
    assert [tool.name for tool in tools] == ["first", "second"]
    assert [tool.meta for tool in tools] == [
        {"operator_id": "first@1.0.0", "version": "1.0.0", "tags": ["a"]},
        {"operator_id": "second@1.0.0", "version": "1.0.0", "tags": ["b", "c"]},
    ]


async def test_all_default_tool_definitions_are_complete_and_stable() -> None:
    server = create_server()
    first = await server.list_tools()
    second = await server.list_tools()
    assert first == second
    assert [tool.name for tool in first] == [
        operator_id.partition("@")[0] for operator_id in DEFAULT_OPERATOR_IDS
    ]
    for tool, operator_id in zip(first, DEFAULT_OPERATOR_IDS, strict=True):
        assert tool.description
        assert tool.inputSchema
        assert tool.outputSchema is None
        assert tool.meta == {"operator_id": operator_id, "version": "1.0.0", "tags": []}

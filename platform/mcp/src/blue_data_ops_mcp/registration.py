from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from blue_data_ops.operators import (
    Operator,
    OperatorCard,
    OperatorRegistry,
    ResolveError,
    default_registry,
)
from mcp.server.fastmcp import FastMCP

from blue_data_ops_mcp.schema import Attributes, InputData, Properties, handler_signature

DEFAULT_OPERATOR_IDS: tuple[str, ...] = (
    "argmax@1.0.0",
    "argmin@1.0.0",
    "avg@1.0.0",
    "classify@1.0.0",
    "cluster@1.0.0",
    "create_database@1.0.0",
    "create_table@1.0.0",
    "data_discover@1.0.0",
    "delete@1.0.0",
    "insert@1.0.0",
    "insert_table@1.0.0",
    "intersect@1.0.0",
    "join@1.0.0",
    "max@1.0.0",
    "min@1.0.0",
    "multipart_query@1.0.0",
    "nl2bn@1.0.0",
    "nl2llm@1.0.0",
    "nl2query_router@1.0.0",
    "nl2sql@1.0.0",
    "normalize_text@1.0.0",
    "plan_discover@1.0.0",
    "project@1.0.0",
    "query_breakdown@1.0.0",
    "segment_text@1.0.0",
    "select@1.0.0",
    "semantic_extract@1.0.0",
    "semantic_filter@1.0.0",
    "semantic_join@1.0.0",
    "semantic_project@1.0.0",
    "semantic_transform@1.0.0",
    "sum@1.0.0",
    "union@1.0.0",
    "vector_embed@1.0.0",
    "vector_search@1.0.0",
    "vector_similarity@1.0.0",
)

ToolHandler = Callable[..., Any]


@dataclass(frozen=True)
class OperatorBinding:
    card: OperatorCard
    operator: Operator


DeploymentSnapshot = tuple[OperatorBinding, ...]


def freeze_deployment(
    registry: OperatorRegistry | None = None,
    operator_ids: Iterable[str] | None = None,
) -> DeploymentSnapshot:
    active_registry = registry if registry is not None else default_registry()
    inventory = active_registry.list_cards()
    inventory_ids = tuple(card.operator_id for card in inventory)
    if inventory_ids != DEFAULT_OPERATOR_IDS:
        raise ValueError("core operator inventory differs from DEFAULT_OPERATOR_IDS")

    selected_ids = DEFAULT_OPERATOR_IDS if operator_ids is None else tuple(operator_ids)
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError("deployment selection contains a repeated operator id")

    selected: list[OperatorCard] = []
    for operator_id in selected_ids:
        active_registry.resolve(operator_id)
        card = active_registry.get_card(operator_id)
        if card is None:
            raise ResolveError(f"no operator card registered as {operator_id!r}")
        selected.append(card)

    names = [card.name for card in selected]
    if len(set(names)) != len(names):
        raise ValueError("deployment selection contains multiple versions of one tool name")

    bindings: list[OperatorBinding] = []
    for card in sorted(selected, key=lambda item: item.name):
        operator = active_registry.resolve(card.operator_id)
        if operator.name != card.name:
            raise ValueError(f"operator/card name mismatch for {card.operator_id!r}")
        bindings.append(OperatorBinding(card=card, operator=operator))
    return tuple(bindings)


def make_handler(operator: Operator) -> ToolHandler:
    async def handler(
        input_data: InputData,
        attributes: Attributes | None = None,
        properties: Properties | None = None,
    ) -> str:
        call_attributes: Attributes = {} if attributes is None else attributes
        result = await asyncio.to_thread(
            operator.apply,
            input_data,
            call_attributes,
            properties,
        )
        return json.dumps(result, default=str, allow_nan=False)

    handler.__name__ = operator.name
    setattr(handler, "__signature__", handler_signature(operator))
    return handler


def register_snapshot(server: FastMCP[Any], snapshot: DeploymentSnapshot) -> None:
    for binding in snapshot:
        card = binding.card
        server.add_tool(
            make_handler(binding.operator),
            name=card.name,
            description=card.description,
            meta={
                "operator_id": card.operator_id,
                "version": card.version,
                "tags": list(card.tags),
            },
            structured_output=False,
        )

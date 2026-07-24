from __future__ import annotations

from typing import ClassVar

from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.registry import OperatorRegistry, default_registry
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    DataBundle,
    OperatorError,
    Properties,
)


class OperatorDiscoverOperator(Operator):
    """Deterministic local operator-discovery facade, outside the 36-card catalog and MCP inventory.

    Portable mode delegates to the registry's deterministic level-1 discovery (exact tag filter
    then rule-based text scoring). Approximate, vector, or hybrid search needs an optional platform
    backend and fails explicitly when that backend is absent — the facade never silently degrades or
    swallows a requested approximate search into an empty result. It has no ``DISCOVERY`` record and
    is never registered as a primary card.
    """

    name: ClassVar[str] = "operator_discover"
    description: ClassVar[str] = (
        "Discover pinned operator cards by deterministic local text and exact-tag matching; "
        "approximate, vector, and hybrid modes require an optional platform backend"
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "search_query": AttributeSpec(
            type="str", description="Text query matched against operator metadata", default=""
        ),
        "tags": AttributeSpec(
            type="list", description="Exact tags to AND-filter candidates", default=[]
        ),
        "approximate": AttributeSpec(
            type="bool", description="Whether to use approximate (vector) search", default=False
        ),
        "hybrid": AttributeSpec(
            type="bool", description="Whether to use hybrid (text + vector) search", default=False
        ),
        "limit": AttributeSpec(
            type="int", description="Max results to return (-1, unlimited)", default=-1
        ),
    }

    def __init__(self, registry: OperatorRegistry | None = None) -> None:
        super().__init__()
        self._registry = registry

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        del input_data
        approximate = bool(attributes.get("approximate", False))
        hybrid = bool(attributes.get("hybrid", False))
        backend = (properties or {}).get("discovery_backend")
        if (approximate or hybrid) and backend is None:
            raise OperatorError(
                "approximate/vector/hybrid discovery requires a platform backend; none was provided"
            )

        registry = self._registry if self._registry is not None else default_registry()
        query = attributes.get("search_query", "")
        tags = attributes.get("tags") or None
        cards = registry.find(query, tags=tags)
        limit = attributes.get("limit", -1)
        if isinstance(limit, int) and limit >= 0:
            cards = cards[:limit]
        return [
            [
                {
                    "operator_id": card.operator_id,
                    "name": card.name,
                    "version": card.version,
                    "description": card.description,
                    "tags": list(card.tags),
                    "when_to_invoke": card.when_to_invoke,
                }
                for card in cards
            ]
        ]


__all__: list[str] = ["OperatorDiscoverOperator"]

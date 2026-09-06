from __future__ import annotations

from typing import ClassVar

from blue_data_ops.operators.embedding_discovery import (
    EmbeddingDiscoveryError,
    OperatorEmbeddingIndex,
)
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.registry import OperatorRegistry, default_registry
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    DataBundle,
    Properties,
)


class OperatorDiscoverOperator(Operator):
    """Discover cards through lexical search or an explicit embedding index.

    Lexical search uses the registry's level-1 text scoring after exact tag filtering. Approximate
    callers must pass the same explicit registry to this facade and its index; a missing or invalid
    index fails without fallback. Hybrid search is unavailable. This facade has no ``DISCOVERY``
    record and stays outside the built-in card catalog and MCP inventory.
    """

    name: ClassVar[str] = "operator_discover"
    description: ClassVar[str] = (
        "Discover pinned operator cards by lexical or caller-supplied embedding search; "
        "hybrid search is unavailable"
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
        if approximate and hybrid:
            raise EmbeddingDiscoveryError("INVALID_MODE")
        if hybrid:
            raise EmbeddingDiscoveryError("MODE_UNAVAILABLE")

        registry = self._registry if self._registry is not None else default_registry()
        query = attributes.get("search_query", "")
        tags = attributes.get("tags") or None
        if approximate:
            backend = (properties or {}).get("discovery_backend")
            if type(backend) is not OperatorEmbeddingIndex or backend.registry is not registry:
                raise EmbeddingDiscoveryError("BACKEND_MISMATCH")
            cards = backend.find(query, tags=tags)
        else:
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

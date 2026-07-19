from __future__ import annotations

from typing import Any, ClassVar

from blue_data_ops.operators.registry import OperatorRegistry, default_registry
from blue_data_ops.operators.types import Attributes, AttributeSpec, DataBundle, Properties
from blue_data_ops.plan import DataPipeline, PlanRecord, RefinableOperator, Status


def plan_discover_operator_function(
    input_data: DataBundle,
    attributes: Attributes,
    properties: Properties | None = None,
) -> DataBundle:
    """Return the empty compute result for this refinement-only operator."""
    del input_data, attributes, properties
    return [[]]


def plan_discover_operator_refiner(
    input_data: DataBundle,
    attributes: Attributes,
    properties: Properties | None = None,
    *,
    registry: OperatorRegistry | None = None,
) -> list[PlanRecord]:
    """Discover pinned operator cards and emit one starter plan per card."""
    task = attributes["task"]
    data = attributes["data"]
    limit = attributes.get("limit", -1)
    del data, input_data, properties

    active_registry = registry if registry is not None else default_registry()
    cards = active_registry.find(task)
    plans: list[PlanRecord] = []
    for card in cards:
        pipeline = DataPipeline()
        input_node = pipeline.define_input(value=None)
        output_node = pipeline.define_output()
        pipeline.set_plan_input(input_node)
        pipeline.set_plan_output(output_node)

        operator_node = pipeline.define_operator(card.operator_id)
        operator_node.set_data("status", str(Status.INITED))
        pipeline.connect_nodes(input_node, operator_node)
        pipeline.connect_nodes(operator_node, output_node)
        plans.append(pipeline.to_dict())

    if limit >= 0:
        return plans[:limit]
    return plans


def plan_discover_operator_validator(
    input_data: DataBundle,
    attributes: Attributes,
    properties: Properties | None = None,
) -> bool:
    """Validate the declared plan schema and unchanged operator-discovery constraints."""
    del input_data, properties
    if not PlanDiscoverOperator()._validate_attributes(  # pyright: ignore[reportPrivateUsage]
        attributes
    ):
        return False

    search_query = attributes.get("search_query", "")
    page = attributes.get("page", 0)
    page_size = attributes.get("page_size", 10)
    threshold = attributes.get("threshold", 0.5)

    if not search_query or not search_query.strip():
        return False
    if page < 0 or page_size <= 0:
        return False
    if threshold < 0 or threshold > 1:
        return False
    return True


def plan_discover_operator_explainer(
    output: DataBundle,
    input_data: DataBundle,
    attributes: Attributes,
) -> dict[str, Any]:
    """Explain the starter-plan discovery result."""
    return {
        "output": output,
        "input_data": input_data,
        "attributes": attributes,
        "explanation": (
            "plan discover operator searched for top-level operators with query "
            f"'{attributes.get('search_query', '')}' and returned "
            f"{len(output[0]) if output and len(output) > 0 else 0} results."
        ),
    }


class PlanDiscoverOperator(RefinableOperator):
    """Discover pinned top-level operators as starter plans."""

    name: ClassVar[str] = "plan_discover"
    description: ClassVar[str] = (
        "Discovers plans using the operator registry to search for top-level operators "
        "as plan starters"
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "task": AttributeSpec(
            type="str",
            description="Task to discover plans/operators",
            required=True,
            default="",
        ),
        "data": AttributeSpec(
            type="str",
            description="Data to operate the task on",
            required=True,
            default="",
        ),
        "approximate": AttributeSpec(
            type="bool",
            description="Whether to use approximate (vector) search",
            required=True,
            default=True,
        ),
        "hybrid": AttributeSpec(
            type="bool",
            description="Whether to use hybrid search (text + vector)",
            default=False,
        ),
        "limit": AttributeSpec(
            type="int",
            description="Max number of results to return (-1, unlimited)",
            default=-1,
        ),
        "page": AttributeSpec(
            type="int",
            description="Page number for pagination",
            default=0,
        ),
        "page_size": AttributeSpec(
            type="int",
            description="Number of results per page (default: 10, max: 100)",
            default=10,
        ),
        "include_metadata": AttributeSpec(
            type="bool",
            description=(
                "Whether to include metadata in results (description and properties "
                "always included)"
            ),
            default=False,
        ),
        "threshold": AttributeSpec(
            type="float",
            description=(
                "Similarity threshold for filtering results (0.0-1.0, lower = more "
                "similar, only applies to approximate/hybrid search)"
            ),
            default=0.5,
        ),
        "progressive_pagination": AttributeSpec(
            type="bool",
            description=(
                "Whether to use progressive pagination for approximate/hybrid search "
                "(searches all pages until threshold exceeded)"
            ),
            default=False,
        ),
    }
    PROPERTIES: ClassVar[dict[str, Any]] = {"refine": True}

    def __init__(self, registry: OperatorRegistry | None = None) -> None:
        self._registry = registry

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        return plan_discover_operator_function(input_data, attributes, properties)

    def refiner(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> list[PlanRecord]:
        return plan_discover_operator_refiner(
            input_data,
            attributes,
            properties,
            registry=self._registry,
        )

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        return plan_discover_operator_validator(input_data, attributes, properties)

    def explain(
        self,
        output: DataBundle,
        input_data: DataBundle,
        attributes: Attributes,
    ) -> dict[str, Any]:
        return plan_discover_operator_explainer(output, input_data, attributes)


__all__ = [
    "PlanDiscoverOperator",
    "plan_discover_operator_explainer",
    "plan_discover_operator_function",
    "plan_discover_operator_refiner",
    "plan_discover_operator_validator",
]

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar, cast

from blue_data_ops.operators._discovery import (
    DiscoveryError,
    DiscoverySpec,
    normalize_filter_tag,
)
from blue_data_ops.operators.operator import default_operator_validator
from blue_data_ops.operators.registry import OperatorRegistry, default_registry
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    DataBundle,
    FunctionResult,
    Properties,
    ValidationResult,
)
from blue_data_ops.plan import DataPipeline, PlanRecord, RefinableOperator, Status
from blue_data_ops.plan.refiner import (
    _selected_refinement_version,  # pyright: ignore[reportPrivateUsage]
)


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
    version: str | None = None,
    use_tag_filter: bool = False,
) -> list[PlanRecord]:
    """Discover pinned operator cards and emit one starter plan per card.

    The canonical v2 path (``use_tag_filter=True``) reads an optional exact ``tags`` list from the
    call attributes and filters the view before ranking, version selection, and limiting. The raw v1
    path ignores it, so v1 behavior and the live metadata view are unchanged.
    """
    task = attributes["task"]
    data = attributes["data"]
    limit = attributes.get("limit", -1)
    filter_tags = attributes.get("tags") if use_tag_filter else None
    del data, input_data, properties

    active_registry = registry if registry is not None else default_registry()
    cards = active_registry.find(task, tags=filter_tags)
    if version is not None:
        cards = [card for card in cards if card.version == version]
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
    """Validate an explicit Blue-shaped property schema and discovery constraints."""
    if not default_operator_validator(input_data, attributes, properties):
        return False

    return _plan_discover_constraints(attributes)


def _validate_v2_tags(tags: Any) -> str | None:
    """Validate the optional v2 exact-tag filter; return a suggestion if invalid, else None.

    The v2 canonical refinement rejects a malformed filter at VALIDATE, before the refiner can touch
    the registry, so bad planner input is a recoverable INVALID_INPUT rather than a refinement
    failure and no registry work begins.
    """
    if not isinstance(tags, (list, tuple)):
        return "tags must be a list of exact tag strings"
    for token in cast("Sequence[object]", tags):
        if not isinstance(token, str):
            return "tags must be a list of exact tag strings"
        try:
            normalize_filter_tag(token)
        except DiscoveryError:
            return "supply well-formed namespaced exact tags without whitespace"
    return None


def _plan_discover_constraints(attributes: Attributes) -> bool:
    """Apply the Blue-compatible discovery-specific value constraints."""

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
        super().__init__()
        self._registry = registry

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        return self._execute(input_data, attributes, properties).output_data

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        return FunctionResult(
            plan_discover_operator_function(input_data, attributes, properties),
            {},
        )

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

    def _refiner(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> list[PlanRecord]:
        version = _selected_refinement_version(self)
        return plan_discover_operator_refiner(
            input_data,
            attributes,
            properties,
            registry=self._registry,
            version=version,
            use_tag_filter=version == "2.0.0",
        )

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        """Validate against this instance's live metadata and discovery constraints."""
        del input_data, properties
        if not self._validate_attributes(attributes):
            return False
        return _plan_discover_constraints(attributes)

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        reason = "supply valid input attributes"
        if not super().validate(input_data, attributes, properties):
            return ValidationResult(False, reason)

        # v2 canonical refinement accepts an optional exact-tag filter; reject a malformed one
        # here, before the refiner reaches the registry (v1 raw path and live metadata view).
        if _selected_refinement_version(self) == "2.0.0" and "tags" in attributes:
            tag_reason = _validate_v2_tags(attributes["tags"])
            if tag_reason is not None:
                return ValidationResult(False, tag_reason)

        canonical_attributes = dict(attributes)
        canonical_attributes["search_query"] = canonical_attributes.get("task", "")
        valid = _plan_discover_constraints(canonical_attributes)
        return ValidationResult(
            valid,
            None if valid else reason,
        )

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


DISCOVERY = DiscoverySpec(
    when_to_invoke=(
        "Use when a task description must be matched to pinned operators and emitted as "
        "starter plans."
    ),
    tags=(
        "domain-plan",
        "flow-plan",
        "accepts-none",
        "produces-plan",
        "capability-operator-discovery",
        "requires-operator-registry",
    ),
)

from __future__ import annotations

from typing import Any, ClassVar

from blue_data_ops.operators._multipart_plan import build_multipart_pipelines
from blue_data_ops.operators.types import Attributes, AttributeSpec, DataBundle, Properties
from blue_data_ops.plan import PlanRecord, RefinableOperator


def multipart_query_operator_function(
    input_data: DataBundle,
    attributes: Attributes,
    properties: Properties | None = None,
) -> DataBundle:
    """Return the empty compute result for this refinement-only operator."""
    del input_data, attributes, properties
    return [[]]


def multipart_query_operator_refiner(
    input_data: DataBundle,
    attributes: Attributes,
    properties: Properties | None = None,
) -> list[PlanRecord]:
    """Build one multipart pipeline per input alternative."""
    return build_multipart_pipelines(
        input_data,
        attributes.get("serialize", True),
        properties,
    )


def multipart_query_operator_validator(
    attributes: Attributes,
    properties: Properties | None = None,
) -> bool:
    """Validate the raw two-argument attribute contract."""
    del properties
    return MultipartQueryOperator()._validate_attributes(  # pyright: ignore[reportPrivateUsage]
        attributes
    )


def multipart_query_operator_explainer(
    output: DataBundle,
    input_data: DataBundle,
    attributes: Attributes,
) -> dict[str, Any]:
    """Explain the multipart orchestration result."""
    return {
        "output": output,
        "input_data": input_data,
        "attributes": attributes,
        "explanation": "multipart query orchestrated the execution of...",
    }


class MultipartQueryOperator(RefinableOperator):
    """Orchestrate multipart queries as portable execution plans."""

    name: ClassVar[str] = "multipart_query"
    description: ClassVar[str] = (
        "Orchestrates the execution of multi-part query, starting with data discovery, "
        "leading to execution"
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "serialize": AttributeSpec(
            type="bool",
            description="Whether to use serialize each part of the query",
            default=True,
        )
    }
    PROPERTIES: ClassVar[dict[str, Any]] = {"refine": True}

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        return multipart_query_operator_function(input_data, attributes, properties)

    def refiner(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> list[PlanRecord]:
        return multipart_query_operator_refiner(input_data, attributes, properties)

    def validate(self, *args: Any, **kwargs: Any) -> bool:
        """Keep the source's direct validator and canonical call mismatch."""
        if "input_data" in kwargs or len(args) == 3:
            raise TypeError(
                "default_attributes_validator() got an unexpected keyword argument 'input_data'"
            )
        if args:
            attributes = args[0]
            properties = args[1] if len(args) > 1 else kwargs.get("properties")
        else:
            attributes = kwargs["attributes"]
            properties = kwargs.get("properties")
        return multipart_query_operator_validator(attributes, properties)

    def explain(
        self,
        output: DataBundle,
        input_data: DataBundle,
        attributes: Attributes,
    ) -> dict[str, Any]:
        return multipart_query_operator_explainer(output, input_data, attributes)


__all__ = [
    "MultipartQueryOperator",
    "multipart_query_operator_explainer",
    "multipart_query_operator_function",
    "multipart_query_operator_refiner",
    "multipart_query_operator_validator",
]

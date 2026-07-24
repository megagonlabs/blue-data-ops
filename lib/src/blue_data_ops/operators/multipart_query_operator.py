from __future__ import annotations

from typing import Any, ClassVar, cast

from blue_data_ops.operators._discovery import DiscoverySpec
from blue_data_ops.operators._multipart_plan import build_multipart_pipelines
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    DataBundle,
    FunctionResult,
    Properties,
    ValidationResult,
)
from blue_data_ops.plan import PlanRecord, RefinableOperator
from blue_data_ops.plan.refiner import (
    _rewrite_plan_operator_version,  # pyright: ignore[reportPrivateUsage]
    _selected_refinement_version,  # pyright: ignore[reportPrivateUsage]
)


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


def _valid_cte_plans(value: object) -> bool:
    if not isinstance(value, list):
        return False
    for group in cast(list[object], value):
        if not isinstance(group, list):
            return False
        for cte_value in cast(list[object], group):
            if not isinstance(cte_value, dict):
                return False
            cte = cast(dict[str, Any], cte_value)
            if not all(
                name in cte for name in ("description", "sql", "table", "columns", "dependency")
            ):
                return False
            if not all(isinstance(cte[name], str) for name in ("description", "sql", "table")):
                return False
            columns = cte["columns"]
            dependency = cte["dependency"]
            if not isinstance(columns, list) or not isinstance(dependency, list):
                return False
            if not all(
                isinstance(column, dict)
                and isinstance(cast(dict[str, Any], column).get("name"), str)
                and (
                    "type" not in cast(dict[str, Any], column)
                    or isinstance(cast(dict[str, Any], column)["type"], str)
                )
                for column in cast(list[object], columns)
            ):
                return False
            if not all(isinstance(name, str) for name in cast(list[object], dependency)):
                return False
            generality = cte.get("generality", 0)
            if isinstance(generality, bool) or not isinstance(generality, (int, float)):
                return False
    return True


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
        return self._execute(input_data, attributes, properties).output_data

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        return FunctionResult(
            multipart_query_operator_function(input_data, attributes, properties),
            {},
        )

    def refiner(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> list[PlanRecord]:
        return multipart_query_operator_refiner(input_data, attributes, properties)

    def _pre_validate_normalize(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None,
    ) -> tuple[DataBundle, Attributes]:
        normalized_input, normalized_attributes = super()._pre_validate_normalize(
            input_data,
            attributes,
            properties,
        )
        if "plans" not in normalized_attributes:
            normalized_attributes["plans"] = normalized_input
        return [[]], normalized_attributes

    def _refiner(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> list[PlanRecord]:
        del input_data
        records = build_multipart_pipelines(
            attributes["plans"],
            attributes.get("serialize", True),
            properties,
        )
        return _rewrite_plan_operator_version(
            records,
            _selected_refinement_version(self),
        )

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        reason = "supply valid multipart-query attributes"
        if not super().validate(input_data, attributes, properties):
            return ValidationResult(False, reason)
        if "plans" in attributes and not _valid_cte_plans(attributes["plans"]):
            return ValidationResult(False, reason)
        return ValidationResult(True, None)

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


DISCOVERY = DiscoverySpec(
    when_to_invoke=(
        "Use when alternative multi-part query specifications must be refined into ordered "
        "data-query plans."
    ),
    tags=(
        "domain-plan",
        "flow-plan",
        "accepts-query",
        "produces-plan",
        "capability-query-orchestration",
    ),
)

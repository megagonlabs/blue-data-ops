from __future__ import annotations

from typing import ClassVar, cast

from blue_data_ops.operators._coercion import coerce_numeric
from blue_data_ops.operators._discovery import DiscoverySpec
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    DataBundle,
    FunctionResult,
    Properties,
    ValidationResult,
)


class AvgOperator(Operator):
    """Calculate the average of values for a specified key across all records."""

    name: ClassVar[str] = "avg"
    description: ClassVar[str] = (
        "Given an input data, calculate the average (arithmetic mean) of values for a specified "
        "key across all records."
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "avg_key": AttributeSpec(
            type="str", description="The key to average the values for", required=True
        ),
        "output_key": AttributeSpec(
            type="str", description="The key name for the result average", default="avg"
        ),
    }

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
        avg_key = cast(str, attributes.get("avg_key"))
        output_key = attributes.get("output_key", "avg")

        if not input_data or not input_data[0]:
            return FunctionResult([[{output_key: 0}]], {})

        total_sum: int | float = 0
        count = 0
        for record in input_data[0]:
            val_to_add = coerce_numeric(record.get(avg_key))
            if val_to_add is not None:
                total_sum += val_to_add
                count += 1

        average = total_sum / count if count > 0 else 0
        return FunctionResult([[{output_key: average}]], {})

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        result = self._validate_input(input_data, attributes, properties)
        return type(result) is ValidationResult and result.ok is True

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        valid = super().validate(input_data, attributes, properties) and bool(
            attributes.get("avg_key")
        )
        return ValidationResult(valid, None if valid else "supply a non-empty avg_key")


DISCOVERY = DiscoverySpec(
    when_to_invoke="Use when a numeric key must be reduced to its arithmetic mean across records.",
    tags=(
        "domain-arithmetic",
        "flow-aggregate",
        "accepts-data",
        "produces-data",
        "capability-average",
        "capability-reduction",
    ),
)

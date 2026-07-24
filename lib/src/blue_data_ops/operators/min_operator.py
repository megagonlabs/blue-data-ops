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


class MinOperator(Operator):
    """Find the minimum value for a specified key across all records."""

    name: ClassVar[str] = "min"
    description: ClassVar[str] = (
        "Given an input data, find the minimum value for a specified key across all records."
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "min_key": AttributeSpec(
            type="str", description="The key to find the minimum value for", required=True
        ),
        "output_key": AttributeSpec(
            type="str", description="The key name for the result min value", default="min"
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
        min_key = cast(str, attributes.get("min_key"))
        output_key = attributes.get("output_key", "min")

        if not input_data or not input_data[0]:
            return FunctionResult([[{output_key: None}]], {})

        min_val: int | float | None = None
        for record in input_data[0]:
            val_to_compare = coerce_numeric(record.get(min_key))
            if val_to_compare is not None:
                if min_val is None or val_to_compare < min_val:
                    min_val = val_to_compare

        return FunctionResult([[{output_key: min_val}]], {})

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
            attributes.get("min_key")
        )
        return ValidationResult(valid, None if valid else "supply a non-empty min_key")


DISCOVERY = DiscoverySpec(
    when_to_invoke="Use when a numeric key must be reduced to its smallest value.",
    tags=(
        "domain-arithmetic",
        "flow-aggregate",
        "accepts-data",
        "produces-data",
        "capability-extrema",
        "capability-reduction",
    ),
)

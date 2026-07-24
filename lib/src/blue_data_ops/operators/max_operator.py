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


class MaxOperator(Operator):
    """Find the maximum value for a specified key across all records."""

    # Initialize the comparison value before iteration; non-coercible values are
    # skipped, and the aggregate is null only when no value coerces.

    name: ClassVar[str] = "max"
    description: ClassVar[str] = (
        "Given an input data, find the maximum value for a specified key across all records."
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "max_key": AttributeSpec(
            type="str", description="The key to find the maximum value for", required=True
        ),
        "output_key": AttributeSpec(
            type="str", description="The key name for the result max value", default="max"
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
        max_key = cast(str, attributes.get("max_key"))
        output_key = attributes.get("output_key", "max")

        if not input_data or not input_data[0]:
            return FunctionResult([[{output_key: None}]], {})

        max_val: int | float | None = None
        for record in input_data[0]:
            val_to_compare = coerce_numeric(record.get(max_key))
            if val_to_compare is not None:
                if max_val is None or val_to_compare > max_val:
                    max_val = val_to_compare

        return FunctionResult([[{output_key: max_val}]], {})

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
            attributes.get("max_key")
        )
        return ValidationResult(valid, None if valid else "supply a non-empty max_key")


DISCOVERY = DiscoverySpec(
    when_to_invoke="Use when a numeric key must be reduced to its largest value.",
    tags=(
        "domain-arithmetic",
        "flow-aggregate",
        "accepts-data",
        "produces-data",
        "capability-extrema",
        "capability-reduction",
    ),
)

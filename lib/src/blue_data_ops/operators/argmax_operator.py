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
    Record,
    ValidationResult,
)


class ArgmaxOperator(Operator):
    """Find the record(s) containing the maximum value for a specified key."""

    name: ClassVar[str] = "argmax"
    description: ClassVar[str] = (
        "Given an input data, find the record(s) that contain the maximum value for a "
        "specified key."
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "argmax_key": AttributeSpec(
            type="str", description="The key to find the maximum value for", required=True
        ),
        "return_index": AttributeSpec(
            type="bool",
            description="If True, returns indices (0-based) instead of records, "
            "otherwise returns records",
            default=False,
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
        argmax_key = cast(str, attributes.get("argmax_key"))
        return_index = attributes.get("return_index", False)

        if not input_data or not input_data[0]:
            if return_index:
                return FunctionResult([[{"indices": []}]], {})
            return FunctionResult([[]], {})

        max_val: int | float | None = None
        max_records_indices: list[tuple[int, Record]] = []
        for i, record in enumerate(input_data[0]):
            val_to_compare = coerce_numeric(record.get(argmax_key))
            if val_to_compare is not None:
                if max_val is None or val_to_compare > max_val:
                    max_val = val_to_compare
                    max_records_indices = [(i, record)]
                elif val_to_compare == max_val:
                    max_records_indices.append((i, record))

        if return_index:
            return FunctionResult(
                [[{"indices": [idx for idx, _ in max_records_indices]}]],
                {},
            )
        return FunctionResult([[rec for _, rec in max_records_indices]], {})

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
            attributes.get("argmax_key")
        )
        return ValidationResult(valid, None if valid else "supply a non-empty argmax_key")


DISCOVERY = DiscoverySpec(
    when_to_invoke=(
        "Use when the result must retain the input record or tied records with the largest "
        "value for one key."
    ),
    tags=(
        "domain-arithmetic",
        "flow-aggregate",
        "accepts-data",
        "produces-data",
        "capability-extrema",
        "capability-record-selection",
    ),
)

from __future__ import annotations

from typing import ClassVar, cast

from blue_data_ops.operators._coercion import coerce_numeric
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import Attributes, AttributeSpec, DataBundle, Properties


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
        min_key = cast(str, attributes.get("min_key"))
        output_key = attributes.get("output_key", "min")

        if not input_data or not input_data[0]:
            return [[{output_key: None}]]

        min_val: int | float | None = None
        for record in input_data[0]:
            val_to_compare = coerce_numeric(record.get(min_key))
            if val_to_compare is not None:
                if min_val is None or val_to_compare < min_val:
                    min_val = val_to_compare

        return [[{output_key: min_val}]]

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        if not super().validate(input_data, attributes, properties):
            return False
        return bool(attributes.get("min_key"))

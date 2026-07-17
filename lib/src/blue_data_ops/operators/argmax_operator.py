from __future__ import annotations

from typing import ClassVar, cast

from blue_data_ops.operators._coercion import coerce_numeric
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import Attributes, AttributeSpec, DataBundle, Properties, Record


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
        argmax_key = cast(str, attributes.get("argmax_key"))
        return_index = attributes.get("return_index", False)

        if not input_data or not input_data[0]:
            if return_index:
                return [[{"indices": []}]]
            return [[]]

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
            return [[{"indices": [idx for idx, _ in max_records_indices]}]]
        return [[rec for _, rec in max_records_indices]]

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        if not super().validate(input_data, attributes, properties):
            return False
        return bool(attributes.get("argmax_key"))

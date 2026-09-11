from __future__ import annotations

from typing import cast

from blue_data_ops.operators._coercion import coerce_numeric
from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.max_operator import MaxOperator
from blue_data_ops.operators.types import Attributes, DataBundle, FunctionResult, Properties


class MaxOutcomeOperator(_OutcomeOperator, MaxOperator):
    """Return an empty tensor when no value can be compared."""

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        del properties
        max_key = cast(str, attributes.get("max_key"))
        output_key = attributes.get("output_key", "max")

        max_value: int | float | None = None
        for record in input_data[0] if input_data else []:
            value = coerce_numeric(record.get(max_key))
            if value is not None and (max_value is None or value > max_value):
                max_value = value
        if max_value is None:
            return FunctionResult([[]], {})
        return FunctionResult([[{output_key: max_value}]], {})

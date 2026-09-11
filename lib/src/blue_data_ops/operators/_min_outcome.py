from __future__ import annotations

from typing import cast

from blue_data_ops.operators._coercion import coerce_numeric
from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.min_operator import MinOperator
from blue_data_ops.operators.types import Attributes, DataBundle, FunctionResult, Properties


class MinOutcomeOperator(_OutcomeOperator, MinOperator):
    """Return an empty tensor when no value can be compared."""

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        del properties
        min_key = cast(str, attributes.get("min_key"))
        output_key = attributes.get("output_key", "min")

        min_value: int | float | None = None
        for record in input_data[0] if input_data else []:
            value = coerce_numeric(record.get(min_key))
            if value is not None and (min_value is None or value < min_value):
                min_value = value
        if min_value is None:
            return FunctionResult([[]], {})
        return FunctionResult([[{output_key: min_value}]], {})

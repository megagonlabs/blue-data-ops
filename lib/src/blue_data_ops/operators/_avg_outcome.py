from __future__ import annotations

from blue_data_ops.operators._coercion import coerce_numeric
from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.avg_operator import AvgOperator
from blue_data_ops.operators.types import Attributes, DataBundle, FunctionResult, Properties


class AvgOutcomeOperator(_OutcomeOperator, AvgOperator):
    """Average accepted values in the first group and report their count."""

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        total: int | float = 0
        count = 0
        for record in input_data[0] if input_data else []:
            value = coerce_numeric(record.get(attributes["avg_key"]))
            if value is not None:
                total += value
                count += 1
        output: DataBundle = (
            [[{attributes.get("output_key", "avg"): total / count}]] if count else [[]]
        )
        return FunctionResult(output, {"num_values_used": count})

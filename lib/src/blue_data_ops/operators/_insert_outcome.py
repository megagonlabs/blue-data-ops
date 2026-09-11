from __future__ import annotations

from typing import cast

from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.insert_operator import (
    InsertOperator,
    _build_result_with_multiple_inserts,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.types import (
    Attributes,
    Data,
    DataBundle,
    FunctionResult,
    Properties,
)


class InsertOutcomeOperator(_OutcomeOperator, InsertOperator):
    """Allow supplied records to populate an existing empty first group."""

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        del properties
        insert_index = attributes.get("insert_idx", -1)
        if not input_data:
            return FunctionResult([], {})

        if len(input_data) >= 2 and input_data[1]:
            insert_records = input_data[1]
        else:
            insert_records = cast(Data, attributes.get("insert_records", []))
        if not insert_records:
            return FunctionResult([input_data[0].copy()], {})

        base_data = input_data[0]
        base_length = len(base_data)
        if isinstance(insert_index, int):
            if insert_index < 0 or insert_index > base_length:
                return FunctionResult([base_data + insert_records], {})
            return FunctionResult(
                [base_data[:insert_index] + insert_records + base_data[insert_index:]],
                {},
            )

        insert_positions = cast(list[int], insert_index.copy())
        while len(insert_positions) < len(insert_records):
            insert_positions.append(-1)
        return FunctionResult(
            [_build_result_with_multiple_inserts(base_data, insert_records, insert_positions)],
            {},
        )

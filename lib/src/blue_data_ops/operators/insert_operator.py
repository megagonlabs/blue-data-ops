from __future__ import annotations

from typing import ClassVar, cast

from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    Data,
    DataBundle,
    Properties,
)


class InsertOperator(Operator):
    """Insert records into the first data source by position."""

    name: ClassVar[str] = "insert"
    description: ClassVar[str] = "Given input data, insert records by position(s)"
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "insert_records": AttributeSpec(
            type="list[dict]",
            description=(
                "List of records to insert into the first data source "
                "(optional if second data group provided)"
            ),
            default=[],
        ),
        "insert_idx": AttributeSpec(
            type="Union[int, list[int]]",
            description=(
                "Position(s) to insert records (-1 for append, 0+ for specific position). "
                "If list, each element corresponds to position for each record"
            ),
            default=-1,
        ),
    }

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        insert_index = attributes.get("insert_idx", -1)
        if not input_data or not input_data[0]:
            return []

        if len(input_data) >= 2 and input_data[1]:
            insert_records = input_data[1]
        else:
            insert_records = cast(Data, attributes.get("insert_records", []))
        if not insert_records:
            return [input_data[0].copy()]

        base_data = input_data[0]
        base_length = len(base_data)
        if isinstance(insert_index, int):
            if insert_index < 0 or insert_index > base_length:
                return [base_data + insert_records]
            return [base_data[:insert_index] + insert_records + base_data[insert_index:]]

        insert_positions = cast(list[int], insert_index.copy())
        while len(insert_positions) < len(insert_records):
            insert_positions.append(-1)
        return [_build_result_with_multiple_inserts(base_data, insert_records, insert_positions)]

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        if not super().validate(input_data, attributes, properties):
            return False

        insert_index = attributes.get("insert_idx", -1)
        try:
            if isinstance(insert_index, int):
                return insert_index >= -1
            if isinstance(insert_index, list):
                raw_indices = cast(list[int], insert_index)
                return all(index >= -1 for index in raw_indices)
        except (TypeError, ValueError, AttributeError):
            # Lax attribute coercion can still produce values that cannot be compared
            # with an integer; validation reports them as invalid instead of raising.
            return False
        return True


def _build_result_with_multiple_inserts(
    base_data: Data,
    insert_records: Data,
    insert_positions: list[int],
) -> Data:
    base_length = len(base_data)
    position_to_records: dict[int, Data] = {}
    append_records: Data = []

    for record, position in zip(insert_records, insert_positions, strict=False):
        if position < 0 or position > base_length:
            append_records.append(record)
        else:
            position_to_records.setdefault(position, []).append(record)

    result: Data = []
    for index in range(base_length):
        if index in position_to_records:
            result.extend(position_to_records[index])
        result.append(base_data[index])
    if base_length in position_to_records:
        result.extend(position_to_records[base_length])
    result.extend(append_records)
    return result

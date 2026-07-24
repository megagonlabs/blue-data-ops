from __future__ import annotations

from typing import ClassVar, cast

from blue_data_ops.operators._discovery import DiscoverySpec
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    Data,
    DataBundle,
    FunctionResult,
    Properties,
    ValidationResult,
)


class DeleteOperator(Operator):
    """Delete records from the first data source by position."""

    name: ClassVar[str] = "delete"
    description: ClassVar[str] = (
        "Given input data, delete records from the first data source at specified positions"
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "delete_idx": AttributeSpec(
            type="Union[int, list[int]]",
            description=(
                "Position(s) to delete records. Supports negative indexing "
                "(-1 = last, -2 = second to last, etc.)"
            ),
            default=[],
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
        delete_index = attributes.get("delete_idx", [])
        if not input_data or not input_data[0]:
            return FunctionResult([], {})
        if delete_index == [] or delete_index is None:
            return FunctionResult([input_data[0].copy()], {})

        base_data = input_data[0]
        base_length = len(base_data)
        if base_length == 0:
            return FunctionResult([base_data], {})

        if isinstance(delete_index, int):
            position = _normalize_index(delete_index, base_length)
            if position is None:
                return FunctionResult([base_data], {})
            return FunctionResult([base_data[:position] + base_data[position + 1 :]], {})

        return FunctionResult(
            [_delete_multiple_positions(base_data, cast(list[int], delete_index))],
            {},
        )

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
        suggestion = "delete_idx must be an integer or a list of integers"
        if not super().validate(input_data, attributes, properties):
            return ValidationResult(False, suggestion)

        delete_index = attributes.get("delete_idx", [])
        if isinstance(delete_index, int):
            return ValidationResult(True, None)
        if isinstance(delete_index, list):
            raw_indices = cast(list[object], delete_index)
            valid = all(isinstance(index, int) for index in raw_indices)
            return ValidationResult(valid, None if valid else suggestion)
        valid = delete_index == [] or delete_index is None
        return ValidationResult(valid, None if valid else suggestion)


def _normalize_index(index: int, length: int) -> int | None:
    if index < 0:
        index = length + index
    if index < 0 or index >= length:
        return None
    return index


def _delete_multiple_positions(base_data: Data, delete_indices: list[int]) -> Data:
    base_length = len(base_data)
    valid_indices: set[int] = set()
    for index in delete_indices:
        normalized = _normalize_index(index, base_length)
        if normalized is not None:
            valid_indices.add(normalized)

    return [record for index, record in enumerate(base_data) if index not in valid_indices]


DISCOVERY = DiscoverySpec(
    when_to_invoke="Use when records must be removed from the first input group by position.",
    tags=(
        "domain-relational",
        "flow-transform",
        "accepts-data",
        "produces-data",
        "capability-delete",
    ),
)

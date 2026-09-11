from __future__ import annotations

from typing import cast

from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.intersect_operator import (
    IntersectOperator,
    _find_intersect_records,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.types import (
    Attributes,
    DataBundle,
    FunctionResult,
    Properties,
    ValidationResult,
)


class IntersectOutcomeOperator(_OutcomeOperator, IntersectOperator):
    """Treat every supplied group as an intersection operand."""

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        validation = super()._validate_input(input_data, attributes, properties)
        if not validation.ok:
            return validation
        if len(input_data) < 2:
            return ValidationResult(False, "supply at least two data groups")
        return ValidationResult(True, None)

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        del properties
        if not input_data or len(input_data) < 2:
            return FunctionResult([], {})
        if any(not group for group in input_data):
            return FunctionResult([[]], {})
        match_option = cast(str, attributes.get("match_option", "key_match"))
        return FunctionResult([_find_intersect_records(input_data, match_option)], {})

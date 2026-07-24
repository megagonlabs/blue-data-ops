from __future__ import annotations

from typing import Any, ClassVar

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


class SelectOperator(Operator):
    """Filter records by a single type-aware condition (record-wise)."""

    name: ClassVar[str] = "select"
    description: ClassVar[str] = (
        "Given an input data, filter data elements based on a specified condition "
        "by type-aware comparison (record-wise)"
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "operand_key": AttributeSpec(
            type="str", description="The key to check in each record", required=True
        ),
        "operand": AttributeSpec(
            type="str", description="Comparison operator: =, !=, >, >=, <, <=", required=True
        ),
        "operand_val": AttributeSpec(
            type="Any", description="Value to compare with", required=True
        ),
        "approximate_match": AttributeSpec(
            type="bool", description="Use epsilon tolerance for numeric comparison", default=False
        ),
        "eps": AttributeSpec(
            type="float",
            description="Epsilon tolerance for approximate numeric comparison",
            default=1e-9,
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
        operand_key = attributes.get("operand_key")
        operand = attributes.get("operand")
        operand_val = attributes.get("operand_val")
        approximate_match = attributes.get("approximate_match", False)
        eps = attributes.get("eps", 1e-9)

        if not input_data or not input_data[0]:
            return FunctionResult([], {})

        data = input_data[0]
        result: Data = []
        for record in data:
            if operand_key not in record:
                continue
            record_value = record[operand_key]
            if _evaluate_condition(record_value, operand, operand_val, approximate_match, eps):
                result.append(record)
        return FunctionResult([result], {})

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
        suggestion = "supply a supported operand and a nonnegative eps value"
        if not super().validate(input_data, attributes, properties):
            return ValidationResult(False, suggestion)
        operand = attributes.get("operand")
        if operand and operand not in ("=", "!=", ">", ">=", "<", "<="):
            return ValidationResult(False, suggestion)
        eps = attributes.get("eps", 1e-9)
        if eps < 0:
            return ValidationResult(False, suggestion)
        return ValidationResult(True, None)


def _evaluate_condition(
    record_value: Any,
    operand: Any,
    operand_val: Any,
    approximate_match: bool,
    eps: float,
) -> bool:
    record_is_numeric = isinstance(record_value, (int, float))
    operand_is_numeric = isinstance(operand_val, (int, float))

    if record_is_numeric and operand_is_numeric:
        record_float = float(record_value)
        operand_float = float(operand_val)
        if operand == "=":
            return (
                abs(record_float - operand_float) <= eps
                if approximate_match
                else record_float == operand_float
            )
        if operand == "!=":
            return (
                abs(record_float - operand_float) > eps
                if approximate_match
                else record_float != operand_float
            )
        if operand == ">":
            return record_float > operand_float
        if operand == ">=":
            return record_float >= operand_float
        if operand == "<":
            return record_float < operand_float
        if operand == "<=":
            return record_float <= operand_float
    elif record_is_numeric != operand_is_numeric:
        return operand == "!="
    elif isinstance(record_value, str) and isinstance(operand_val, str):
        if operand == "=":
            return record_value == operand_val
        if operand == "!=":
            return record_value != operand_val
        if operand == ">":
            return record_value > operand_val
        if operand == ">=":
            return record_value >= operand_val
        if operand == "<":
            return record_value < operand_val
        if operand == "<=":
            return record_value <= operand_val
    else:
        if operand == "=":
            return record_value == operand_val
        if operand == "!=":
            return record_value != operand_val
        return False

    return False


DISCOVERY = DiscoverySpec(
    when_to_invoke=(
        "Use when records should be filtered by a type-aware comparison against one key."
    ),
    tags=(
        "domain-relational",
        "flow-transform",
        "accepts-data",
        "produces-data",
        "capability-filter",
    ),
)

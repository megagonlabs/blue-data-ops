from __future__ import annotations

from typing import cast

from blue_data_ops.llm import prepare_llm_operator_properties, resolve_llm_client
from blue_data_ops.llm.client import validate_llm_caller_controls
from blue_data_ops.llm.errors import raise_reply_failure
from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.semantic_filter_operator import SemanticFilterOperator
from blue_data_ops.operators.types import (
    Attributes,
    DataBundle,
    FunctionResult,
    Properties,
    Record,
    ValidationResult,
)


def _strict_boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise_reply_failure()


class SemanticFilterOutcomeOperator(_OutcomeOperator, SemanticFilterOperator):
    """Process every group and accept only explicit boolean filter responses."""

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        validate_llm_caller_controls(
            properties, service_prefix=str(self.DEFAULT_PROPERTIES.get("service_prefix", "openai"))
        )
        filter_conditions = cast(dict[str, str], attributes.get("filter_conditions", {}))
        context = cast(str, attributes.get("context", ""))
        demonstrations = cast(str, attributes.get("demonstrations", ""))
        return_idx = cast(bool, attributes.get("return_idx", False))
        if not input_data or not filter_conditions:
            return FunctionResult([], {})
        if all(not group for group in input_data):
            if return_idx:
                return FunctionResult([[{"indices": []}] for _ in input_data], {})
            return FunctionResult([], {})

        merged = {**self.DEFAULT_PROPERTIES, **(properties or {})}
        merged = prepare_llm_operator_properties(merged, self.DEFAULT_PROPERTIES, properties)
        client = resolve_llm_client(merged)
        results: DataBundle = []
        for data_group in input_data:
            if not data_group:
                results.append([{"indices": []}] if return_idx else [])
                continue
            filtered_records: list[Record] = []
            filtered_indices: list[int] = []
            for index, record in enumerate(data_group):
                conditions_text: list[str] = []
                for number, (field, condition) in enumerate(filter_conditions.items(), 1):
                    if field in record:
                        conditions_text.append(
                            f"{number}. Field '{field}' (value: {record[field]}) should "
                            f"satisfy: {condition}"
                        )
                    else:
                        conditions_text.append(
                            f"{number}. Field '{field}' (not present in record) should "
                            f"satisfy: {condition}"
                        )
                result = client.execute_api_call(
                    {},
                    properties=merged,
                    additional_data={
                        "record": record,
                        "conditions": "\n".join(conditions_text),
                        "context": context,
                        "demonstrations": demonstrations,
                    },
                )
                if _strict_boolean(result):
                    filtered_records.append(record)
                    filtered_indices.append(index)
            results.append([{"indices": filtered_indices}] if return_idx else filtered_records)
        return FunctionResult(results, {})

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        validation = super()._validate_input(input_data, attributes, properties)
        if not validation.ok:
            return validation
        if type(attributes.get("return_idx", False)) is not bool:
            return ValidationResult(False, "return_idx must be boolean")
        return validation

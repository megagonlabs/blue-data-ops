from __future__ import annotations

from typing import Any, cast

from blue_data_ops.llm import prepare_llm_operator_properties, resolve_llm_client
from blue_data_ops.llm.client import validate_llm_caller_controls
from blue_data_ops.llm.errors import raise_reply_failure
from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.semantic_project_operator import SemanticProjectOperator
from blue_data_ops.operators.types import (
    Attributes,
    DataBundle,
    FunctionResult,
    Properties,
    Record,
)


def _mapping(value: object, schema: set[str]) -> dict[str, str]:
    if not isinstance(value, dict):
        raise_reply_failure()
    raw_mapping = cast(dict[Any, Any], value)
    if any(
        not isinstance(old_name, str)
        or old_name not in schema
        or not isinstance(new_name, str)
        or not new_name.strip()
        for old_name, new_name in raw_mapping.items()
    ):
        raise_reply_failure()
    mapping = cast(dict[str, str], raw_mapping)
    if len(set(mapping.values())) != len(mapping):
        raise_reply_failure()
    return mapping


class SemanticProjectOutcomeOperator(_OutcomeOperator, SemanticProjectOperator):
    """Process every group and validate projection mappings before applying them."""

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        validate_llm_caller_controls(
            properties, service_prefix=str(self.DEFAULT_PROPERTIES.get("service_prefix", "openai"))
        )
        instructions = cast(str, attributes.get("projection_instructions", ""))
        if not input_data or not instructions or all(not group for group in input_data):
            return FunctionResult([], {})

        merged = {**self.DEFAULT_PROPERTIES, **(properties or {})}
        merged = prepare_llm_operator_properties(merged, self.DEFAULT_PROPERTIES, properties)
        client = resolve_llm_client(merged)
        results: DataBundle = []
        for data_group in input_data:
            if not data_group:
                results.append([])
                continue
            typed_schema = self._extract_typed_schema(data_group)
            schema_display = [
                f"- {column_name} ({data_type})" for column_name, data_type in typed_schema.items()
            ]
            resolved_mapping = _mapping(
                client.execute_api_call(
                    {},
                    properties=merged,
                    additional_data={
                        "schema": "\n".join(schema_display),
                        "projection_instructions": instructions,
                    },
                ),
                set(typed_schema),
            )
            if not resolved_mapping:
                results.append([])
                continue
            projected_records: list[Record] = []
            for record in data_group:
                projected_records.append(
                    {
                        new_name: record[old_name]
                        for old_name, new_name in resolved_mapping.items()
                        if old_name in record
                    }
                )
            results.append(projected_records)
        return FunctionResult(results, {})

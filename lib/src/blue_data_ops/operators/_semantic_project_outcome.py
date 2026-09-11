from __future__ import annotations

from typing import Any, cast

from blue_data_ops.llm import resolve_llm_client
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
        raise ValueError("semantic projection response must be an object")
    raw_mapping = cast(dict[Any, Any], value)
    if any(
        not isinstance(old_name, str)
        or old_name not in schema
        or not isinstance(new_name, str)
        or not new_name.strip()
        for old_name, new_name in raw_mapping.items()
    ):
        raise ValueError("semantic projection response has invalid field names")
    mapping = cast(dict[str, str], raw_mapping)
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("semantic projection response has duplicate output fields")
    return mapping


class SemanticProjectOutcomeOperator(_OutcomeOperator, SemanticProjectOperator):
    """Process every group and validate projection mappings before applying them."""

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        instructions = cast(str, attributes.get("projection_instructions", ""))
        if not input_data or not instructions or all(not group for group in input_data):
            return FunctionResult([], {})

        merged = {**self.DEFAULT_PROPERTIES, **(properties or {})}
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

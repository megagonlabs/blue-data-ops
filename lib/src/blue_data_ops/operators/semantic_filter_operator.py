from __future__ import annotations

from typing import Any, ClassVar, cast

from blue_data_ops.llm import resolve_llm_client
from blue_data_ops.operators._discovery import DiscoverySpec
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    DataBundle,
    FunctionResult,
    Properties,
    Record,
    ValidationResult,
)

_FILTER_PROMPT = """## Task
You are given a data record and natural language filter conditions. Your job is to determine if the record should be included in the filtered results.

## Record to Evaluate
${record}

## Filter Conditions
${conditions}

## Context
${context}

## Demonstrations
${demonstrations}

## Output Requirements
- Return **only a boolean value**: true or false
- Return **true** if the record satisfies ALL the filter conditions
- Return **false** if the record does NOT satisfy any of the filter conditions
- Be precise in your evaluation based on the natural language conditions
- Consider the semantic meaning of the conditions, not just exact text matching

## Additional Notes
- If a field is not present in the record, evaluate the condition as if the field has no value
- Use your understanding of natural language to interpret conditions.
- Return only the boolean result, no explanations or additional text

---

### Output
"""


class SemanticFilterOperator(Operator):
    """Filter records by natural-language conditions through an LLM."""

    name: ClassVar[str] = "semantic_filter"
    description: ClassVar[str] = (
        "Filters records based on natural language conditions using LLM models"
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "filter_conditions": AttributeSpec(
            type="dict[str, str]",
            description="Dictionary mapping field names to natural language filter conditions",
            required=True,
        ),
        "context": AttributeSpec(
            type="str",
            description=("Optional context to provide domain knowledge or additional instructions"),
            default="",
        ),
        "demonstrations": AttributeSpec(
            type="str",
            description="Optional demonstrations to help in-context learning",
            default="",
        ),
        # Blue spells this unknown primitive "boolean"; the base therefore treats the
        # declaration as Any. Preserve that validator quirk exactly.
        "return_idx": AttributeSpec(
            type="boolean",
            description=(
                "If true, return indices of records that satisfy all conditions, else "
                "return filtered records"
            ),
            default=False,
        ),
    }
    FILTER_PROMPT: ClassVar[str] = _FILTER_PROMPT
    DEFAULT_PROPERTIES: ClassVar[dict[str, Any]] = {
        "openai.api": "ChatCompletion",
        "openai.model": "gpt-4o",
        "openai.stream": False,
        "openai.max_tokens": 1024,
        "openai.temperature": 0,
        "input_json": '[{"role": "user"}]',
        "input_context": "$[0]",
        "input_context_field": "content",
        "input_field": "messages",
        "input_template": _FILTER_PROMPT,
        "output_path": "$.choices[0].message.content",
        "service_prefix": "openai",
        "output_transformations": [
            {"transformation": "replace", "from": "```", "to": ""},
            {"transformation": "replace", "from": "json", "to": ""},
        ],
        "output_strip": True,
        "output_cast": "bool",
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
        filter_conditions = cast(dict[str, str], attributes.get("filter_conditions", {}))
        context = cast(str, attributes.get("context", ""))
        demonstrations = cast(str, attributes.get("demonstrations", ""))
        return_idx = attributes.get("return_idx", False)
        if not input_data or not input_data[0] or not filter_conditions:
            return FunctionResult([], {})

        merged = {**self.DEFAULT_PROPERTIES, **(properties or {})}
        client = resolve_llm_client(merged)
        results: DataBundle = []
        for data_group in input_data:
            if not data_group:
                results.append([])
                continue
            filtered_records: list[Record] = []
            filtered_indices: list[int] = []
            for idx, record in enumerate(data_group):
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
                additional_data = {
                    "record": record,
                    "conditions": "\n".join(conditions_text),
                    "context": context,
                    "demonstrations": demonstrations,
                }
                result = client.execute_api_call(
                    {}, properties=merged, additional_data=additional_data
                )
                if isinstance(result, str):
                    result = result.lower().strip() in ["true", "yes", "1", "include"]
                elif not isinstance(result, bool):
                    result = bool(result)
                if result:
                    filtered_records.append(record)
                    filtered_indices.append(idx)
            if return_idx:
                results.append([{"indices": filtered_indices}])
            else:
                results.append(filtered_records)
        return FunctionResult(results, {})

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
        reason = "supply valid semantic filter attributes"
        if not super().validate(input_data, attributes, properties):
            return ValidationResult(False, reason)
        filter_conditions_value = attributes.get("filter_conditions", {})
        if not isinstance(filter_conditions_value, dict) or not filter_conditions_value:
            return ValidationResult(False, reason)
        filter_conditions = cast(dict[Any, Any], filter_conditions_value)
        for key, value in filter_conditions.items():
            if not isinstance(key, str) or not isinstance(value, str):
                return ValidationResult(False, reason)
            if not key.strip() or not value.strip():
                return ValidationResult(False, reason)
        return ValidationResult(True, None)


DISCOVERY = DiscoverySpec(
    when_to_invoke=(
        "Use when records must be filtered by a natural-language condition that cannot be "
        "expressed as a simple comparison."
    ),
    tags=(
        "domain-semantic",
        "flow-transform",
        "accepts-data",
        "produces-data",
        "capability-filter",
        "requires-llm",
    ),
)

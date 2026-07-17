from __future__ import annotations

from typing import Any, ClassVar, cast

from blue_data_ops.llm import resolve_llm_client
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import Attributes, AttributeSpec, DataBundle, Properties, Record

_MAPPING_PROMPT = """## Task
You are given a database schema with data types and natural language projection instructions. Your job is to generate a JSON mapping that specifies which columns to keep and how to rename them.

## Available Schema (with data types)
${schema}

## Projection Instructions
${projection_instructions}

## Output Requirements
- Return a **single JSON object** as the output
- The JSON object must contain key-value pairs where:
  - **Keys**: original column names from the schema (exact matches)
  - **Values**: new column names for the output
- **Column Selection Rules**:
  - Only include columns that should be kept in the output
  - If a column should be dropped, do not include it in the mapping
  - If a column should be renamed, map the old name to the new name
  - If a column should keep its original name, map it to itself
- **Validation Rules**:
  - All keys must exist in the provided schema
  - All values must be unique (no duplicate output column names)
  - All values must be valid column names (no special characters, extra spaces, etc.)
- **Examples**:
  - Keep and rename: `{"fname": "full_name", "lname": "last_name"}`
  - Keep without rename: `{"skills": "skills", "experience": "experience"}`
  - Drop column: simply don't include it in the mapping

## Additional Notes
- Interpret the natural language requirements carefully
- Be precise about which columns to keep vs drop
- Follow standard naming conventions for column names
- Return only the JSON object, no explanations or additional text

---

### Output JSON Object
"""


class SemanticProjectOperator(Operator):
    """Select and rename columns from a natural-language projection request."""

    name: ClassVar[str] = "semantic_project"
    description: ClassVar[str] = (
        "Projects records to select and rename columns using LLM-based mapping resolution"
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "projection_instructions": AttributeSpec(
            type="str",
            description=(
                "Natural language description of which columns to keep and how to rename them"
            ),
            required=True,
        )
    }
    MAPPING_PROMPT: ClassVar[str] = _MAPPING_PROMPT
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
        "input_template": _MAPPING_PROMPT,
        "output_path": "$.choices[0].message.content",
        "service_prefix": "openai",
        "output_transformations": [
            {"transformation": "replace", "from": "```", "to": ""},
            {"transformation": "replace", "from": "json", "to": ""},
        ],
        "output_strip": True,
        "output_cast": "json",
    }

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        projection_instructions = cast(str, attributes.get("projection_instructions", ""))
        if not input_data or not input_data[0] or not projection_instructions:
            return []

        merged = {**self.DEFAULT_PROPERTIES, **(properties or {})}
        client = resolve_llm_client(merged)
        results: DataBundle = []
        for data_group in input_data:
            if not data_group:
                results.append([])
                continue
            schema = self._extract_typed_schema(data_group)
            schema_display = [
                f"- {column_name} ({data_type})" for column_name, data_type in schema.items()
            ]
            result = client.execute_api_call(
                {},
                properties=merged,
                additional_data={
                    "schema": "\n".join(schema_display),
                    "projection_instructions": projection_instructions,
                },
            )
            resolved_mapping = cast(dict[Any, Any], result) if isinstance(result, dict) else {}
            if not resolved_mapping:
                results.append([])
                continue
            projected_records: list[Record] = []
            for record in data_group:
                projected_record: Record = {}
                for old_key_value, new_key_value in resolved_mapping.items():
                    old_key = cast(str, old_key_value)
                    new_key = cast(str, new_key_value)
                    if old_key in record:
                        projected_record[new_key] = record[old_key]
                projected_records.append(projected_record)
            results.append(projected_records)
        return results

    @staticmethod
    def _extract_typed_schema(data_group: list[Record]) -> dict[str, str]:
        type_mapping: dict[type[Any], str] = {
            type(None): "null",
            bool: "boolean",
            int: "integer",
            float: "float",
            str: "string",
            list: "array",
            dict: "object",
        }
        schema: dict[str, set[str]] = {}
        for record in data_group:
            for key, value in record.items():
                value_type = cast(type[Any], type(value))
                schema.setdefault(key, set()).add(type_mapping.get(value_type, "unknown"))
        return {key: "|".join(sorted(types)) for key, types in schema.items()}

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        if not super().validate(input_data, attributes, properties):
            return False
        projection_instructions = attributes.get("projection_instructions", "")
        return isinstance(projection_instructions, str) and bool(projection_instructions.strip())

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

_SINGLE_EXTRACT_PROMPT = """## Task
You are given one data record in JSON format. Your job is to extract specific entities from this record and return them in strict JSON format.

## Entities to Extract
${entities}

## Context
${context}

## Demonstrations
${demonstrations}

## Output Requirements
- Return a **single JSON object** as the output.
- The JSON object must contain:
  - Keys: exact entity names from the list above (preserve original case and formatting).
  - Values: arrays of extracted items (may be empty if nothing is found).
- Do not introduce extra keys or change entity names.
- **Deduplication rule (within the same entity key):**
  - Remove duplicates and near-duplicates (e.g., case/spacing/punctuation variants, obvious aliases, or versioned forms).
  - Keep **one canonical value** if there are multiple semantically equivalent values.
  - Example: `"skill": ["python", "python3.10", "Python "]` → `"skill": ["python"]`.
- Only extract entities from the specified fields for each entity name.
- Be precise and only return relevant entities.

## Additional Notes
- If no entities are found, still return an object with all keys mapped to empty arrays.
- Do not include explanations, comments, or text outside the JSON object.
- Validate that the final output is syntactically valid JSON.

---

### Data Record
${data_record}

---

### Output JSON Object
"""

_INDIVIDUAL_EXTRACT_PROMPT = """## Task
You are given text content and need to extract specific entities of type "${entity_name}" from it.

## Entity to Extract
- **Name**: ${entity_name}${entity_type_info}
- **Description**: ${entity_description}
- **Extract from fields**: ${extract_fields}${type_line}

## Context
${context}

## Demonstrations
${demonstrations}

## Output Requirements
- Return a **JSON array** of extracted ${entity_name} entities
- Each element should be a string representing one ${entity_name}
- If no ${entity_name} entities are found, return an empty array []
- Be precise and only extract relevant ${entity_name} entities
- **Deduplication rule:**
  - Remove duplicates and near-duplicates (e.g., case/spacing/punctuation variants, obvious aliases, or versioned forms)
  - Keep **one canonical value** if there are multiple semantically equivalent values
  - Example: `["python", "python3.10", "Python "]` → `["python"]`
- Do not include explanations, comments, or text outside the JSON array
- Validate that the final output is syntactically valid JSON

---

### Text to Extract From
${text_to_extract}

---

### Output JSON Array
"""


class SemanticExtractOperator(Operator):
    """Extract entities from natural-language fields through an LLM."""

    name: ClassVar[str] = "semantic_extract"
    description: ClassVar[str] = (
        "Extracts entities from natural language text fields using LLM models"
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "entities": AttributeSpec(
            type="list[dict]",
            description=(
                "List of entities to extract. Each dict has 'name', 'description' "
                "(optional), 'extract_on_fields' (optional list of field names - if not "
                "provided, extracts from all fields), and 'type' (optional)"
            ),
            required=True,
        ),
        "context": AttributeSpec(
            type="str",
            description=(
                "Additional context information that provides domain knowledge or "
                "additional instructions for the extraction"
            ),
            default="",
        ),
        "demonstrations": AttributeSpec(
            type="str",
            description="Additional demonstrations to help in-context learning",
            default="",
        ),
        "extract_with_single_prompt": AttributeSpec(
            type="bool",
            description=(
                "If true, extract all entities in a single prompt, else extract each "
                "entity with individual prompt"
            ),
            default=True,
        ),
    }

    SINGLE_EXTRACT_PROMPT: ClassVar[str] = _SINGLE_EXTRACT_PROMPT
    INDIVIDUAL_EXTRACT_PROMPT: ClassVar[str] = _INDIVIDUAL_EXTRACT_PROMPT
    DEFAULT_PROPERTIES: ClassVar[dict[str, Any]] = {
        "openai.api": "ChatCompletion",
        "openai.model": "gpt-4o",
        "openai.stream": False,
        "openai.max_tokens": 4096,
        "openai.temperature": 0,
        "input_json": '[{"role": "user"}]',
        "input_context": "$[0]",
        "input_context_field": "content",
        "input_field": "messages",
        "input_template": _SINGLE_EXTRACT_PROMPT,
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
        return self._execute(input_data, attributes, properties).output_data

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        entities = cast(list[dict[str, Any]], attributes.get("entities", []))
        context = attributes.get("context", "")
        demonstrations = attributes.get("demonstrations", "")
        extract_with_single_prompt = attributes.get("extract_with_single_prompt", True)

        if not input_data or not input_data[0] or not entities:
            return FunctionResult([], {})

        merged = {**self.DEFAULT_PROPERTIES, **(properties or {})}
        client = resolve_llm_client(merged)
        results: DataBundle = []
        for data_group in input_data:
            if not data_group:
                results.append([])
                continue

            if extract_with_single_prompt:
                result = self._extract_all_entities_single_prompt(
                    data_group,
                    entities,
                    cast(str, context),
                    cast(str, demonstrations),
                    client,
                    merged,
                )
            else:
                result = self._extract_entities_individual_prompts(
                    data_group,
                    entities,
                    cast(str, context),
                    cast(str, demonstrations),
                    client,
                    merged,
                )
            results.append(result)
        return FunctionResult(results, {})

    @staticmethod
    def _extract_all_entities_single_prompt(
        data_group: list[Record],
        entities: list[dict[str, Any]],
        context: str,
        demonstrations: str,
        client: Any,
        properties: dict[str, Any],
    ) -> list[Record]:
        results: list[Record] = []
        for record in data_group:
            entity_descriptions: list[str] = []
            relevant_fields: set[str] = set()
            for entity in entities:
                name = entity["name"]
                description = entity.get("description", f"Extract {name} from the text")
                extract_on_fields = entity.get("extract_on_fields", [])
                entity_type = entity.get("type")
                type_info = f" ({entity_type})" if entity_type else ""
                if extract_on_fields:
                    fields = ", ".join(extract_on_fields)
                    entity_descriptions.append(
                        f"- {name}{type_info}: {description} (from fields: {fields})"
                    )
                    relevant_fields.update(extract_on_fields)
                else:
                    entity_descriptions.append(
                        f"- {name}{type_info}: {description} (from all fields)"
                    )
                    relevant_fields.update(record.keys())

            filtered_record = {field: record[field] for field in relevant_fields if field in record}
            additional_data = {
                "entities": "\n".join(entity_descriptions),
                "context": context,
                "demonstrations": demonstrations,
                "data_record": filtered_record,
            }
            result = client.execute_api_call(
                {}, properties=properties, additional_data=additional_data
            )
            if isinstance(result, dict):
                results.append(cast(Record, result))
            else:
                results.append({entity["name"]: [] for entity in entities})
        return results

    @staticmethod
    def _extract_entities_individual_prompts(
        data_group: list[Record],
        entities: list[dict[str, Any]],
        context: str,
        demonstrations: str,
        client: Any,
        properties: dict[str, Any],
    ) -> list[Record]:
        results: list[Record] = []
        for record in data_group:
            extracted_record: Record = {}
            for entity in entities:
                entity_name = entity["name"]
                entity_description = entity.get("description", "")
                extract_on_fields = entity.get("extract_on_fields", [])
                entity_type = entity.get("type")
                if not extract_on_fields:
                    extract_on_fields = list(record.keys())

                text_to_extract = [
                    f"{field}: {record[field]}"
                    for field in extract_on_fields
                    if field in record and record[field]
                ]
                if not text_to_extract:
                    extracted_record[entity_name] = []
                    continue

                individual_properties = properties.copy()
                individual_properties["input_template"] = _INDIVIDUAL_EXTRACT_PROMPT
                if entity_type:
                    entity_type_info = f" ({entity_type})"
                    type_line = f"\n- **Type**: {entity_type}"
                else:
                    entity_type_info = ""
                    type_line = ""
                additional_data = {
                    "entity_name": entity_name,
                    "entity_description": entity_description,
                    "entity_type_info": entity_type_info,
                    "type_line": type_line,
                    "extract_fields": (
                        ", ".join(extract_on_fields) if extract_on_fields else "all fields"
                    ),
                    "context": context,
                    "demonstrations": demonstrations,
                    "text_to_extract": "\n".join(text_to_extract),
                }
                entity_result = client.execute_api_call(
                    {}, properties=individual_properties, additional_data=additional_data
                )
                if isinstance(entity_result, list):
                    extracted_record[entity_name] = entity_result
                else:
                    extracted_record[entity_name] = [entity_result] if entity_result else []
            results.append(extracted_record)
        return results

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
        reason = "supply valid semantic extraction attributes"
        if not super().validate(input_data, attributes, properties):
            return ValidationResult(False, reason)
        entities_value = attributes.get("entities", [])
        if not isinstance(entities_value, list) or not entities_value:
            return ValidationResult(False, reason)
        entities = cast(list[Any], entities_value)
        for entity in entities:
            if not isinstance(entity, dict) or "name" not in entity:
                return ValidationResult(False, reason)
            entity = cast(dict[Any, Any], entity)
            if "description" in entity and not isinstance(entity["description"], str):
                return ValidationResult(False, reason)
            if "type" in entity and not isinstance(entity["type"], str):
                return ValidationResult(False, reason)
            if "extract_on_fields" in entity:
                if not isinstance(entity["extract_on_fields"], list):
                    return ValidationResult(False, reason)
                if len(cast(list[Any], entity["extract_on_fields"])) == 0:
                    return ValidationResult(False, reason)
        return ValidationResult(True, None)


DISCOVERY = DiscoverySpec(
    when_to_invoke=(
        "Use when entities must be extracted from text fields using natural-language instructions."
    ),
    tags=(
        "domain-semantic",
        "flow-transform",
        "accepts-data",
        "produces-data",
        "capability-extraction",
        "requires-llm",
    ),
)

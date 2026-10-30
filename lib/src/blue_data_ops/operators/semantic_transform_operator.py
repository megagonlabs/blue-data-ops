from __future__ import annotations

import json
import warnings
from typing import Any, ClassVar, cast

from blue_data_ops.llm import LLMClient, prepare_llm_operator_properties, resolve_llm_client
from blue_data_ops.llm.client import validate_llm_caller_controls
from blue_data_ops.llm.errors import raise_reply_failure
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

_PLAN_RESOLUTION_PROMPT = """## Task
You are a data transformation planner. Analyze the input schema and output requirements to create a transformation plan.

## Input Schema
${schema}

## Input Metadata (if provided)
${input_metadata}

## Sample Data (first 5 records)
${sample_data}

## Output Requirements
${output_requirements}

## Instructions
Create a transformation plan that maps each target field to its source fields and transformation type.

For each target field, determine:
1. **source_fields**: List of input fields needed to create this target field
2. **transformation_type**: Either "field_mapping_without_value_change" or "field_mapping_with_value_change"
   - Use "field_mapping_without_value_change" when you can simply rename/copy a field without any value modification
   - Use "field_mapping_with_value_change" when you need to modify, combine, derive, or transform values

## Output Format
Return a JSON object where each key is a target field name and the value is:
{
  "source_fields": ["field1", "field2", ...],
  "transformation_type": "field_mapping_without_value_change" | "field_mapping_with_value_change"
}

## Examples
- Simple rename: `{"full_name": {"source_fields": ["name"], "transformation_type": "field_mapping_without_value_change"}}`
- Value transformation: `{"age_group": {"source_fields": ["age"], "transformation_type": "field_mapping_with_value_change"}}`
- Field combination: `{"full_address": {"source_fields": ["street", "city", "state"], "transformation_type": "field_mapping_with_value_change"}}`

Return only the JSON object, no additional text.
"""

_TRANSFORM_PROMPT = """## Task
You are a data transformation expert. Transform the input data to match the required output schema.

## Available Input Fields
${schema}

## Target Output Fields
${output_requirements}

## Input Data Record
${input_data}

## Instructions
1. Transform the input data record to create the target output fields
2. Use the field descriptions, optional types, optional required flags, and optional hints to guide your transformations.
3. Ensure output values match the specified data types (str, integer, boolean, etc.) if specified.
4. **Field Inclusion Rules**:
   - If a field is marked as "required: True", it MUST be present in the output with an appropriate value
   - If a field is marked as "required: False", it can be omitted if you cannot reasonably infer its value from the input data
   - If no "required" information is provided, only include fields that you confidently infer or derive from the available input data
5. **Required Field Generation**: If a required field cannot be created from available data, use a null value (None).

6. **Conservative Approach**: When in doubt about whether to include a field, err on the side of omitting it rather than generating speculative values
7. **Do NOT generate fake or speculative values** for fields that cannot be reasonably inferred from the input data
8. Return the transformed data as a JSON object

Return only the transformed JSON object, no additional text.
"""


def _extract_typed_schema(data_group: list[Record]) -> str:
    type_mapping: dict[type[Any], str] = {
        type(None): "null",
        bool: "boolean",
        int: "integer",
        float: "float",
        str: "str",
        list: "array",
        dict: "object",
    }
    schema: dict[str, set[str]] = {}
    for record in data_group:
        for key, value in record.items():
            value_type = cast(type[Any], type(value))
            schema.setdefault(key, set()).add(type_mapping.get(value_type, "unknown"))
    schema_display = [
        f"- {column_name} ({'|'.join(sorted(data_types))})"
        for column_name, data_types in schema.items()
    ]
    return "Available input fields:\n" + "\n".join(schema_display)


def _generate_transformation_plan(
    data_group: list[Record],
    input_meta: dict[str, dict[str, Any]],
    output_desc: dict[str, dict[str, Any]],
    client: LLMClient,
    properties: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if input_meta:
        schema_text = "Available input fields:\n"
        for field in data_group[0].keys():
            if field in input_meta:
                meta_info = input_meta[field]
                schema_text += f"- {field}: {meta_info.get('description', 'No description')}"
                if "type" in meta_info:
                    schema_text += f" (type: {meta_info['type']})"
                schema_text += "\n"
            else:
                schema_text += f"- {field}\n"
    else:
        schema_text = _extract_typed_schema(data_group)

    input_metadata_text = ""
    if input_meta:
        input_metadata_text = "Input field metadata:\n"
        for field, meta_info in input_meta.items():
            input_metadata_text += f"- {field}: {meta_info.get('description', 'No description')}"
            if "type" in meta_info:
                input_metadata_text += f" (type: {meta_info['type']})"
            if "hints" in meta_info:
                input_metadata_text += f" (hints: {meta_info['hints']})"
            input_metadata_text += "\n"

    output_text = "Required output fields:\n"
    for field_name, field_info in output_desc.items():
        description = field_info.get("description", "")
        field_type = field_info.get("type", "")
        required = field_info.get("required", "")
        hints = field_info.get("hints", "")
        output_text += f"- {field_name}: {description}"
        if field_type:
            output_text += f" (type: {field_type})"
        if required != "":
            output_text += f" (required: {required})"
        if hints:
            output_text += f" (hints: {hints})"
        output_text += "\n"

    sample_data_text = ""
    if data_group:
        sample_data_text = "Sample data records:\n"
        for index, record in enumerate(data_group[:5]):
            sample_data_text += f"Record {index + 1}: {record}\n"

    plan_properties = properties.copy() if properties else {}
    plan_properties["input_template"] = _PLAN_RESOLUTION_PROMPT
    result = client.execute_api_call(
        {},
        properties=plan_properties,
        additional_data={
            "schema": schema_text,
            "input_metadata": input_metadata_text,
            "sample_data": sample_data_text,
            "output_requirements": output_text,
        },
    )
    if isinstance(result, dict):
        plan: dict[Any, Any] = cast(dict[Any, Any], result)
    elif isinstance(result, str):
        try:
            candidate = json.loads(result)
            plan = cast(dict[Any, Any], candidate) if isinstance(candidate, dict) else {}
        except (json.JSONDecodeError, ValueError):
            plan = {}
    else:
        plan = {}

    # Blue's shallow copy means updating plan fields also mutates the nested caller
    # dictionaries in output_desc. Preserve that identity side effect.
    enhanced_output_desc = output_desc.copy()
    for target_field, plan_info in plan.items():
        if target_field in enhanced_output_desc:
            enhanced_output_desc[target_field].update(plan_info)
    return enhanced_output_desc


def _get_merged_field_groups(
    field_dependencies: dict[str, set[str]],
) -> list[dict[str, Any]]:
    source_combinations: dict[tuple[str, ...], list[str]] = {}
    for field_name, source_fields in field_dependencies.items():
        key = tuple(sorted(source_fields))
        source_combinations.setdefault(key, []).append(field_name)

    merged_groups: list[dict[str, Any]] = []
    processed_combinations: set[tuple[str, ...]] = set()
    sorted_combinations = sorted(
        source_combinations.items(), key=lambda item: len(item[0]), reverse=True
    )
    for source_fields, field_names in sorted_combinations:
        if source_fields in processed_combinations:
            continue
        mergeable_fields = field_names.copy()
        for other_source_fields, other_field_names in source_combinations.items():
            if other_source_fields in processed_combinations:
                continue
            if other_source_fields == source_fields:
                continue
            if set(other_source_fields).issubset(set(source_fields)):
                mergeable_fields.extend(other_field_names)
                processed_combinations.add(other_source_fields)
        merged_groups.append(
            {"source_fields": list(source_fields), "target_fields": mergeable_fields}
        )
        processed_combinations.add(source_fields)
    return merged_groups


def _calculate_distinct_required_values_cost(
    field_dependencies: dict[str, set[str]], data_group: list[Record]
) -> int:
    total_cost = 0
    for source_fields in field_dependencies.values():
        distinct_combinations = {
            tuple(record.get(field, "") for field in source_fields) for record in data_group
        }
        total_cost += len(distinct_combinations)
    return total_cost


def _calculate_distinct_required_values_with_merged_fields_cost(
    field_dependencies: dict[str, set[str]], data_group: list[Record]
) -> int:
    total_cost = 0
    for group in _get_merged_field_groups(field_dependencies):
        source_fields = cast(list[str], group["source_fields"])
        distinct_combinations = {
            tuple(record.get(field, "") for field in source_fields) for record in data_group
        }
        total_cost += len(distinct_combinations)
    return total_cost


def _select_execution_strategy(
    enhanced_output_desc: dict[str, dict[str, Any]], data_group: list[Record]
) -> dict[str, Any]:
    if not enhanced_output_desc:
        return {"strategy": "per_record", "simple_fields": [], "complex_fields": []}

    simple_fields: list[str] = []
    complex_fields: list[str] = []
    for field_name, field_info in enhanced_output_desc.items():
        transformation_type = field_info.get(
            "transformation_type", "field_mapping_with_value_change"
        )
        if transformation_type == "field_mapping_without_value_change":
            simple_fields.append(field_name)
        elif transformation_type == "field_mapping_with_value_change":
            complex_fields.append(field_name)
    if not complex_fields:
        return {
            "strategy": "simple_rename",
            "simple_fields": simple_fields,
            "complex_fields": [],
        }

    field_dependencies = {
        field_name: set(enhanced_output_desc[field_name].get("source_fields", []))
        for field_name in complex_fields
    }
    costs = {
        "per_record": len(data_group),
        "distinct_required_values": _calculate_distinct_required_values_cost(
            field_dependencies, data_group
        ),
        "distinct_required_values_with_merged_fields": (
            _calculate_distinct_required_values_with_merged_fields_cost(
                field_dependencies, data_group
            )
        ),
    }
    best_strategy = min(costs, key=costs.__getitem__)
    return {
        "strategy": best_strategy,
        "simple_fields": simple_fields,
        "complex_fields": complex_fields,
        "costs": costs,
        "field_dependencies": field_dependencies,
    }


def _force_strategy(
    enhanced_output_desc: dict[str, dict[str, Any]],
    specified_strategy: str,
) -> dict[str, Any]:
    if not enhanced_output_desc:
        return {
            "strategy": specified_strategy,
            "simple_fields": [],
            "complex_fields": [],
        }
    simple_fields: list[str] = []
    complex_fields: list[str] = []
    for field_name, field_info in enhanced_output_desc.items():
        transformation_type = field_info.get(
            "transformation_type", "field_mapping_with_value_change"
        )
        if transformation_type == "field_mapping_without_value_change":
            simple_fields.append(field_name)
        elif transformation_type == "field_mapping_with_value_change":
            complex_fields.append(field_name)

    valid_strategies = [
        "per_record",
        "distinct_required_values",
        "distinct_required_values_with_merged_fields",
    ]
    if specified_strategy not in valid_strategies:
        warnings.warn("Unknown strategy; using per_record.", UserWarning)
        specified_strategy = "per_record"
    if not complex_fields:
        return {
            "strategy": "per_record",
            "simple_fields": simple_fields,
            "complex_fields": [],
        }

    field_dependencies: dict[str, set[str]] = {}
    if specified_strategy in [
        "distinct_required_values",
        "distinct_required_values_with_merged_fields",
    ]:
        field_dependencies = {
            field_name: set(enhanced_output_desc[field_name].get("source_fields", []))
            for field_name in complex_fields
        }
    return {
        "strategy": specified_strategy,
        "simple_fields": simple_fields,
        "complex_fields": complex_fields,
        "field_dependencies": field_dependencies,
    }


def _execute_simple_rename(
    data_group: list[Record],
    enhanced_output_desc: dict[str, dict[str, Any]],
    simple_fields: list[str],
) -> list[Record]:
    results: list[Record] = []
    for record in data_group:
        transformed_record: Record = {}
        for field_name in simple_fields:
            source_fields = enhanced_output_desc.get(field_name, {}).get("source_fields", [])
            if source_fields and source_fields[0] in record:
                transformed_record[field_name] = record[source_fields[0]]
        results.append(transformed_record)
    return results


def _output_requirements(
    enhanced_output_desc: dict[str, dict[str, Any]], target_fields: list[str]
) -> str:
    output_text = "Required output fields:\n"
    for target_field in target_fields:
        if target_field not in enhanced_output_desc:
            continue
        field_info = enhanced_output_desc[target_field]
        source_fields = field_info.get("source_fields", [])
        description = field_info.get("description", "")
        transformation_type = field_info.get(
            "transformation_type", "field_mapping_with_value_change"
        )
        required_info = f", required: {field_info['required']}" if "required" in field_info else ""
        hints_info = f", hints: {field_info['hints']}" if "hints" in field_info else ""
        output_text += (
            f"- {target_field}: {description} (from {', '.join(source_fields)}, "
            f"{transformation_type}{required_info}{hints_info})\n"
        )
    return output_text


def _parse_dict_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return cast(dict[str, Any], result)
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            return cast(dict[str, Any], parsed) if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


def _execute_per_record(
    data_group: list[Record],
    enhanced_output_desc: dict[str, dict[str, Any]],
    simple_fields: list[str],
    complex_fields: list[str],
    client: LLMClient,
    properties: dict[str, Any],
) -> list[Record]:
    results: list[Record] = []
    for record in data_group:
        transformed_record = _execute_simple_rename([record], enhanced_output_desc, simple_fields)[
            0
        ]
        if complex_fields:
            schema_text = "Available input fields:\n"
            for field, value in record.items():
                schema_text += f"- {field} ({type(value).__name__})\n"
            result = client.execute_api_call(
                {},
                properties=properties,
                additional_data={
                    "schema": schema_text,
                    "output_requirements": _output_requirements(
                        enhanced_output_desc, complex_fields
                    ),
                    "input_data": record,
                },
            )
            transformed_record.update(_parse_dict_result(result))
        for field_name in enhanced_output_desc:
            if field_name not in simple_fields and field_name not in complex_fields:
                transformed_record[field_name] = None
        results.append(transformed_record)
    return results


def _execute_distinct_required_values(
    data_group: list[Record],
    enhanced_output_desc: dict[str, dict[str, Any]],
    simple_fields: list[str],
    complex_fields: list[str],
    client: LLMClient,
    properties: dict[str, Any],
) -> list[Record]:
    simple_results = _execute_simple_rename(data_group, enhanced_output_desc, simple_fields)
    if not complex_fields:
        return simple_results

    field_dependencies = {
        field_name: set(enhanced_output_desc.get(field_name, {}).get("source_fields", []))
        for field_name in complex_fields
    }
    value_mappings: dict[tuple[str, tuple[Any, ...]], Any] = {}
    for field_name in complex_fields:
        source_fields = field_dependencies[field_name]
        distinct_combinations = {
            tuple(record.get(field, "") for field in source_fields) for record in data_group
        }
        for combination in distinct_combinations:
            sample_record = {field: combination[index] for index, field in enumerate(source_fields)}
            schema_text = "Available input fields:\n"
            for field, value in sample_record.items():
                schema_text += f"- {field} ({type(value).__name__})\n"
            result = client.execute_api_call(
                {},
                properties=properties,
                additional_data={
                    "schema": schema_text,
                    "output_requirements": _output_requirements(enhanced_output_desc, [field_name]),
                    "input_data": sample_record,
                },
            )
            parsed = _parse_dict_result(result)
            if field_name in parsed:
                # Blue keys only by combination, so two target fields with the same
                # dependencies overwrite each other. The target is part of the key
                # here: the surrounding per-field loop makes that intent unambiguous.
                value_mappings[(field_name, combination)] = parsed[field_name]

    results: list[Record] = []
    for index, record in enumerate(data_group):
        transformed_record = simple_results[index].copy()
        for field_name in complex_fields:
            source_fields = field_dependencies[field_name]
            combination = (
                tuple(record.get(field, "") for field in source_fields) if source_fields else ()
            )
            mapping_key = (field_name, combination)
            if mapping_key in value_mappings:
                transformed_record[field_name] = value_mappings[mapping_key]
        for field_name in enhanced_output_desc:
            if field_name not in simple_fields and field_name not in complex_fields:
                transformed_record[field_name] = None
        results.append(transformed_record)

    return results


def _execute_distinct_required_values_with_merged_fields(
    data_group: list[Record],
    enhanced_output_desc: dict[str, dict[str, Any]],
    simple_fields: list[str],
    complex_fields: list[str],
    strategy_info: dict[str, Any],
    client: LLMClient,
    properties: dict[str, Any],
) -> list[Record]:
    simple_results = _execute_simple_rename(data_group, enhanced_output_desc, simple_fields)
    field_dependencies = cast(dict[str, set[str]], strategy_info.get("field_dependencies", {}))
    field_groups = _get_merged_field_groups(field_dependencies)

    complex_results: list[Record] = []
    for group in field_groups:
        group_source_fields = cast(list[str], group["source_fields"])
        target_fields = cast(list[str], group["target_fields"])
        combination_to_records: dict[tuple[Any, ...], list[int]] = {}
        for index, record in enumerate(data_group):
            combination = tuple(record.get(field, "") for field in group_source_fields)
            combination_to_records.setdefault(combination, []).append(index)

        combination_results: dict[tuple[Any, ...], dict[str, Any]] = {}
        for combination in set(combination_to_records):
            representative_record = data_group[combination_to_records[combination][0]]
            if group_source_fields:
                schema_text = "Available input fields:\n"
                for field in group_source_fields:
                    value = representative_record.get(field, "")
                    schema_text += f"- {field} ({type(value).__name__})\n"
            else:
                schema_text = "No specific input fields available for this transformation.\n"

            output_text = "Required output fields:\n"
            for target_field in target_fields:
                if target_field not in enhanced_output_desc:
                    continue
                field_info = enhanced_output_desc[target_field]
                target_source_fields = field_info.get("source_fields", [])
                description = field_info.get("description", "")
                transformation_type = field_info.get(
                    "transformation_type", "field_mapping_with_value_change"
                )
                required_info = (
                    f", required: {field_info['required']}" if "required" in field_info else ""
                )
                hints_info = f", hints: {field_info['hints']}" if "hints" in field_info else ""
                if target_source_fields:
                    output_text += (
                        f"- {target_field}: {description} (from "
                        f"{', '.join(target_source_fields)}, {transformation_type}"
                        f"{required_info}{hints_info})\n"
                    )
                else:
                    output_text += (
                        f"- {target_field}: {description} (no source fields available,  "
                        f"{transformation_type}{required_info}{hints_info}), \n"
                    )
            result = client.execute_api_call(
                {},
                properties=properties,
                additional_data={
                    "schema": schema_text,
                    "output_requirements": output_text,
                    "input_data": representative_record,
                },
            )
            combination_results[combination] = _parse_dict_result(result)

        for index, record in enumerate(data_group):
            # Blue accidentally reuses the last target's source_fields here, which
            # can make every group lookup miss. Apply with the group's dependencies.
            combination = tuple(record.get(field, "") for field in group_source_fields)
            if combination in combination_results:
                if index >= len(complex_results):
                    complex_results.extend([{} for _ in range(index + 1 - len(complex_results))])
                complex_results[index].update(combination_results[combination])

    results: list[Record] = []
    for index in range(len(data_group)):
        result = simple_results[index] if index < len(simple_results) else {}
        if index < len(complex_results):
            result.update(complex_results[index])
        for field_name in enhanced_output_desc:
            if field_name not in simple_fields and field_name not in complex_fields:
                result[field_name] = None
        results.append(result)

    return results


_TRANSFORMATION_TYPES = {
    "field_mapping_without_value_change",
    "field_mapping_with_value_change",
}


def _response_object(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            value = None
        if value is None:
            raise_reply_failure()
    if not isinstance(value, dict):
        raise_reply_failure()
    return cast(dict[str, Any], value)


class _StrictTransformClient(LLMClient):
    def __init__(
        self,
        delegate: LLMClient,
        output_desc: dict[str, dict[str, Any]],
    ) -> None:
        self._delegate = delegate
        self._output_desc = output_desc

    def execute_api_call(
        self,
        input: Any,
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        result = self._delegate.execute_api_call(
            input,
            properties=properties,
            additional_data=additional_data,
        )
        response = _response_object(result)
        if properties and properties.get("input_template") == _PLAN_RESOLUTION_PROMPT:
            missing = set(self._output_desc).difference(response)
            if missing:
                raise_reply_failure()
            for plan_value in response.values():
                if not isinstance(plan_value, dict):
                    raise_reply_failure()
                plan = cast(dict[str, Any], plan_value)
                source_fields = plan.get("source_fields")
                if not isinstance(source_fields, list) or any(
                    not isinstance(field, str) for field in cast(list[Any], source_fields)
                ):
                    raise_reply_failure()
                if plan.get("transformation_type") not in _TRANSFORMATION_TYPES:
                    raise_reply_failure()
            return response

        requirements = (
            "" if additional_data is None else str(additional_data.get("output_requirements", ""))
        )
        required_here = {
            name
            for name, field in self._output_desc.items()
            if field.get("required") is True and f"- {name}:" in requirements
        }
        if not required_here.issubset(response):
            raise_reply_failure()
        return response


class SemanticTransformOperator(Operator):
    """Transform records into described output fields through an LLM plan.

    Retained ``@1.0.0`` and ``@2.0.0`` use strict response validation.
    Malformed replies raise through ``apply()`` and ``invoke()``; ``run()``
    contains failures in ``exec_meta.errors``. Valid negative and empty replies remain valid.
    """

    name: ClassVar[str] = "semantic_transform"
    description: ClassVar[str] = (
        "Transforms data into target fields and values using LLM-based transformations"
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "input_meta": AttributeSpec(
            type="dict",
            description="Optional metadata about input fields",
            default={},
        ),
        "output_desc": AttributeSpec(
            type="dict",
            description="Required description of target fields to create",
            required=True,
        ),
        "strategy": AttributeSpec(
            type="str",
            description=(
                "Execution strategy: 'auto' (automatic cost-based selection), "
                "'per_record' (one LLM call per record), 'distinct_required_values' "
                "(deduplicate by distinct values), "
                "'distinct_required_values_with_merged_fields' (merged distinct "
                "optimization)."
            ),
            default="auto",
        ),
    }
    PLAN_RESOLUTION_PROMPT: ClassVar[str] = _PLAN_RESOLUTION_PROMPT
    TRANSFORM_PROMPT: ClassVar[str] = _TRANSFORM_PROMPT
    DEFAULT_PROPERTIES: ClassVar[dict[str, Any]] = {
        "openai.api": "ChatCompletion",
        "openai.model": "gpt-6-luna",
        "openai.stream": False,
        "openai.max_tokens": 1024,
        "openai.temperature": 0.0,
        "input_json": '[{"role": "user"}]',
        "input_context": "$[0]",
        "input_context_field": "content",
        "input_field": "messages",
        "input_template": _TRANSFORM_PROMPT,
        "output_path": "$.choices[0].message.content",
        "service_prefix": "openai",
        "output_transformations": [
            {
                "transformation": "sub",
                "from": r"(?is)\A```(?:json)?[ \t]*\r?\n(.*)\r?\n```\Z",
                "to": r"\1",
            },
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
        validate_llm_caller_controls(
            properties, service_prefix=str(self.DEFAULT_PROPERTIES.get("service_prefix", "openai"))
        )
        input_meta = cast(dict[str, dict[str, Any]], attributes.get("input_meta", {}))
        output_desc = cast(dict[str, dict[str, Any]], attributes.get("output_desc", {}))
        if not input_data or not input_data[0] or not output_desc:
            return FunctionResult([], {})

        merged = {**self.DEFAULT_PROPERTIES, **(properties or {})}
        merged = prepare_llm_operator_properties(merged, self.DEFAULT_PROPERTIES, properties)
        client = _StrictTransformClient(resolve_llm_client(merged), output_desc)
        results: DataBundle = []
        for data_group in input_data:
            if not data_group:
                results.append([])
                continue
            enhanced_output_desc = _generate_transformation_plan(
                data_group, input_meta, output_desc, client, merged
            )
            specified_strategy = cast(str, attributes.get("strategy", "auto"))
            strategy_info = (
                _select_execution_strategy(enhanced_output_desc, data_group)
                if specified_strategy == "auto"
                else _force_strategy(enhanced_output_desc, specified_strategy)
            )
            strategy = cast(str, strategy_info["strategy"])
            simple_fields = cast(list[str], strategy_info["simple_fields"])
            complex_fields = cast(list[str], strategy_info["complex_fields"])
            if strategy == "simple_rename":
                result = _execute_simple_rename(data_group, enhanced_output_desc, simple_fields)
            elif strategy == "per_record":
                result = _execute_per_record(
                    data_group,
                    enhanced_output_desc,
                    simple_fields,
                    complex_fields,
                    client,
                    merged,
                )
            elif strategy == "distinct_required_values":
                result = _execute_distinct_required_values(
                    data_group,
                    enhanced_output_desc,
                    simple_fields,
                    complex_fields,
                    client,
                    merged,
                )
            elif strategy == "distinct_required_values_with_merged_fields":
                result = _execute_distinct_required_values_with_merged_fields(
                    data_group,
                    enhanced_output_desc,
                    simple_fields,
                    complex_fields,
                    strategy_info,
                    client,
                    merged,
                )
            else:
                result = _execute_per_record(
                    data_group,
                    enhanced_output_desc,
                    simple_fields,
                    complex_fields,
                    client,
                    merged,
                )
            results.append(result)
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
        reason = "supply a valid semantic transform output description"
        if not super().validate(input_data, attributes, properties):
            return ValidationResult(False, reason)
        output_desc_value = attributes.get("output_desc", {})
        if not output_desc_value or not isinstance(output_desc_value, dict):
            return ValidationResult(False, reason)
        output_desc = cast(dict[Any, Any], output_desc_value)
        for field_name, field_info in output_desc.items():
            if not isinstance(field_name, str) or not isinstance(field_info, dict):
                return ValidationResult(False, reason)
            if "description" not in field_info or not isinstance(field_info["description"], str):
                return ValidationResult(False, reason)
        return ValidationResult(True, None)


DISCOVERY = DiscoverySpec(
    when_to_invoke=(
        "Use when records must be converted into requested target fields or values using "
        "natural-language transformations."
    ),
    tags=(
        "domain-semantic",
        "flow-transform",
        "accepts-data",
        "produces-data",
        "capability-transformation",
        "requires-llm",
    ),
)

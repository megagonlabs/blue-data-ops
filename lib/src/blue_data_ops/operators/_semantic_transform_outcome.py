from __future__ import annotations

import json
from typing import Any, cast

from blue_data_ops.llm import LLMClient, resolve_llm_client
from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.semantic_transform_operator import (
    _PLAN_RESOLUTION_PROMPT,  # pyright: ignore[reportPrivateUsage]
    SemanticTransformOperator,
    _execute_distinct_required_values,  # pyright: ignore[reportPrivateUsage]
    _execute_distinct_required_values_with_merged_fields,  # pyright: ignore[reportPrivateUsage]
    _execute_per_record,  # pyright: ignore[reportPrivateUsage]
    _execute_simple_rename,  # pyright: ignore[reportPrivateUsage]
    _force_strategy,  # pyright: ignore[reportPrivateUsage]
    _generate_transformation_plan,  # pyright: ignore[reportPrivateUsage]
    _select_execution_strategy,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.types import (
    Attributes,
    DataBundle,
    FunctionResult,
    Properties,
)

_TRANSFORMATION_TYPES = {
    "field_mapping_without_value_change",
    "field_mapping_with_value_change",
}


def _response_object(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError("semantic transform response is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("semantic transform response must be an object")
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
                raise ValueError("semantic transform plan does not cover every target")
            for plan_value in response.values():
                if not isinstance(plan_value, dict):
                    raise ValueError("semantic transform plan entries must be objects")
                plan = cast(dict[str, Any], plan_value)
                source_fields = plan.get("source_fields")
                if not isinstance(source_fields, list) or any(
                    not isinstance(field, str) for field in cast(list[Any], source_fields)
                ):
                    raise ValueError("semantic transform source_fields must be a string array")
                if plan.get("transformation_type") not in _TRANSFORMATION_TYPES:
                    raise ValueError("semantic transform plan has an invalid transformation type")
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
            raise ValueError("semantic transform response omits a required target")
        return response


class SemanticTransformOutcomeOperator(_OutcomeOperator, SemanticTransformOperator):
    """Process every group and reject malformed plans or generated records."""

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        input_meta = cast(dict[str, dict[str, Any]], attributes.get("input_meta", {}))
        output_desc = cast(dict[str, dict[str, Any]], attributes.get("output_desc", {}))
        if not input_data or not output_desc or all(not group for group in input_data):
            return FunctionResult([], {})

        merged = {**self.DEFAULT_PROPERTIES, **(properties or {})}
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

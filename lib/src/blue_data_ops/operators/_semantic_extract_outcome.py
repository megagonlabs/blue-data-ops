from __future__ import annotations

from typing import Any, cast

from blue_data_ops.llm import resolve_llm_client
from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.semantic_extract_operator import SemanticExtractOperator
from blue_data_ops.operators.types import (
    Attributes,
    DataBundle,
    FunctionResult,
    Properties,
)


class _StrictExtractClient:
    def __init__(self, delegate: Any, entity_names: set[Any], *, combined: bool) -> None:
        self._delegate = delegate
        self._entity_names = entity_names
        self._combined = combined

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
        if self._combined:
            if not isinstance(result, dict):
                raise ValueError("semantic extract response must be an object")
            response = cast(dict[Any, Any], result)
            if set(response) != self._entity_names or any(
                not isinstance(value, list) for value in response.values()
            ):
                raise ValueError("semantic extract response has invalid entity fields")
        elif not isinstance(result, list) or any(
            not isinstance(value, str) for value in cast(list[Any], result)
        ):
            raise ValueError("semantic extract response must be a string array")
        return cast(Any, result)


class SemanticExtractOutcomeOperator(_OutcomeOperator, SemanticExtractOperator):
    """Process every input group and reject malformed extraction responses."""

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        entities = cast(list[dict[str, Any]], attributes.get("entities", []))
        context = cast(str, attributes.get("context", ""))
        demonstrations = cast(str, attributes.get("demonstrations", ""))
        combined = cast(bool, attributes.get("extract_with_single_prompt", True))
        if not input_data or not entities or all(not group for group in input_data):
            return FunctionResult([], {})

        merged = {**self.DEFAULT_PROPERTIES, **(properties or {})}
        client = _StrictExtractClient(
            resolve_llm_client(merged),
            {entity["name"] for entity in entities},
            combined=combined,
        )
        results: DataBundle = []
        for data_group in input_data:
            if not data_group:
                results.append([])
            elif combined:
                results.append(
                    self._extract_all_entities_single_prompt(
                        data_group,
                        entities,
                        context,
                        demonstrations,
                        client,
                        merged,
                    )
                )
            else:
                results.append(
                    self._extract_entities_individual_prompts(
                        data_group,
                        entities,
                        context,
                        demonstrations,
                        client,
                        merged,
                    )
                )
        return FunctionResult(results, {})

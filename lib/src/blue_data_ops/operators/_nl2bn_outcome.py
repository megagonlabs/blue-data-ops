from __future__ import annotations

import json
import logging
from typing import Any, cast

from blue_data_ops.data import resolve_registry
from blue_data_ops.llm import resolve_llm_client
from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators._query_results import format_execution_result
from blue_data_ops.operators.nl2bn_operator import (
    _CORRECTION_PROMPT,  # pyright: ignore[reportPrivateUsage]
    NL2BNOperator,
    _MissingRegistryError,  # pyright: ignore[reportPrivateUsage]
    _resolve_schema_section,  # pyright: ignore[reportPrivateUsage]
    _validate_bn_query,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.types import (
    Attributes,
    DataBundle,
    FunctionResult,
    Properties,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class NL2BNOutcomeOperator(_OutcomeOperator, NL2BNOperator):
    """Distinguish empty Bayesian results from malformed or probability-free results."""

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        question = cast(str, attributes.get("question", ""))
        source = cast(str, attributes.get("source", ""))
        database = cast(str, attributes.get("database", "default"))
        collection = cast(str, attributes.get("collection", ""))
        protocol_variant = cast(str, attributes.get("protocol_variant", "pgmpy"))
        context = attributes.get("context", "")
        provided_schema = attributes.get("schema", "")
        explanation = attributes.get("explanation", True)
        structured_explanation = attributes.get("structured_explanation", False)
        max_corrections = cast(int, attributes.get("max_corrections", 2))
        max_num_paths = attributes.get("max_num_paths", 50)

        if not question or not question.strip():
            return FunctionResult([[]], {})
        if not source or not database or not collection or not protocol_variant:
            raise ValueError("Source, database, collection, and protocol_variant are required")
        if protocol_variant != "pgmpy":
            raise ValueError(
                f"Unsupported protocol_variant: {protocol_variant}. Supported variants: ['pgmpy']"
            )

        registry = resolve_registry(properties)
        if not registry:
            raise _MissingRegistryError

        schema_info, graph_structure = _resolve_schema_section(
            provided_schema, registry, source, database, collection
        )
        is_structured = graph_structure is not None
        merged = {**self.DEFAULT_PROPERTIES, **(properties or {})}
        client = resolve_llm_client(merged)
        additional_data = {
            "question": question,
            "context": context,
            "schema_section": schema_info,
        }

        bn_query_data: dict[str, Any] = {}
        validation_errors: list[str] = []
        try:
            bn_query_result = client.execute_api_call(
                {}, properties=merged, additional_data=additional_data
            )
        except Exception as error:
            validation_errors.append(f"Service error: {str(error)}")
        else:
            if isinstance(bn_query_result, str):
                try:
                    bn_query_data = json.loads(bn_query_result)
                except json.JSONDecodeError as error:
                    validation_errors.append(f"Invalid JSON response from LLM: {str(error)}")
            elif isinstance(bn_query_result, dict):
                bn_query_data = cast(dict[str, Any], bn_query_result)
            else:
                validation_errors.append(
                    f"Invalid response type from LLM: {type(bn_query_result).__name__}"
                )

        if not validation_errors:
            if "target_node" not in bn_query_data:
                validation_errors.append("No target_node found in LLM response")
            if "target_state" not in bn_query_data:
                validation_errors.append("No target_state found in LLM response")
            if "context" not in bn_query_data:
                bn_query_data["context"] = {}
        if is_structured and not validation_errors:
            assert graph_structure is not None
            validation_errors.extend(_validate_bn_query(bn_query_data, graph_structure))

        correction_attempts = 0
        while validation_errors and correction_attempts < max_corrections:
            logger.info(
                "Query validation found errors (attempt %s): %s",
                correction_attempts + 1,
                validation_errors,
            )
            correction_data = {
                "question": question,
                "original_query": json.dumps(bn_query_data, indent=2),
                "validation_errors": json.dumps(validation_errors, indent=2),
                "schema_section": schema_info,
            }
            correction_properties = {**merged, "input_template": _CORRECTION_PROMPT}
            correction_result = client.execute_api_call(
                {},
                properties=correction_properties,
                additional_data=correction_data,
            )
            if isinstance(correction_result, str):
                try:
                    bn_query_data = json.loads(correction_result)
                    validation_errors = []
                except json.JSONDecodeError as error:
                    validation_errors = [f"Invalid JSON in corrected query: {str(error)}"]
                    break
            elif isinstance(correction_result, dict):
                bn_query_data = cast(dict[str, Any], correction_result)
                validation_errors = []
            else:
                validation_errors = [
                    f"Invalid correction response type: {type(correction_result).__name__}"
                ]
                break
            if not validation_errors:
                if "target_node" not in bn_query_data:
                    validation_errors.append("No target_node found in corrected query")
                if "target_state" not in bn_query_data:
                    validation_errors.append("No target_state found in corrected query")
                if "context" not in bn_query_data:
                    bn_query_data["context"] = {}
            if is_structured and not validation_errors:
                assert graph_structure is not None
                validation_errors.extend(_validate_bn_query(bn_query_data, graph_structure))
            correction_attempts += 1

        if validation_errors:
            error_message = (
                f"Query validation failed after {max_corrections} correction attempts. "
                f"Errors: {', '.join(validation_errors)}"
            )
            logger.error(error_message)
            raise ValueError(error_message)

        query_json = json.dumps(bn_query_data)
        logger.info("Generated BN Query: %s", query_json)
        optional_properties: dict[str, Any] = {}
        if explanation:
            optional_properties["explanation"] = True
            optional_properties["structured_explanation"] = structured_explanation
            optional_properties["max_num_paths"] = max_num_paths
        result = registry.execute_query(
            query_json,
            source,
            database,
            collection,
            optional_properties=optional_properties,
        )
        logger.debug("Result: %s", result)

        formatted_result = format_execution_result(result)
        if formatted_result is None:
            raise ValueError("Bayesian query result could not be formatted")
        if not formatted_result or all(not group for group in formatted_result):
            return FunctionResult([[]], {})

        first_result = formatted_result[0][0]
        probability = first_result.get("probability", first_result.get("prob"))
        if probability is None:
            raise ValueError("Bayesian query result has no probability")
        output: dict[str, Any] = {"prob": probability, "query": bn_query_data}
        explanation_text = first_result.get("explanation", "")
        if explanation and explanation_text:
            output["explanation"] = explanation_text
        return FunctionResult([[output]], {})

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        validation = super()._validate_input(input_data, attributes, properties)
        if not validation.ok:
            return validation
        required = ("question", "source", "database", "collection")
        if any(
            not isinstance(attributes.get(name), str) or not attributes[name].strip()
            for name in required
        ):
            return ValidationResult(False, "Bayesian routing fields must be nonblank strings")
        if attributes.get("protocol_variant", "pgmpy") != "pgmpy":
            return ValidationResult(False, "protocol_variant must be pgmpy")
        return validation

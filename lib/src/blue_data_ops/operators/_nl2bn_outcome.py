from __future__ import annotations

import json
import logging
from typing import Any, cast

from blue_data_ops.data import resolve_registry
from blue_data_ops.data.registry_seam import (
    _diagnose_source,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.llm import prepare_llm_operator_properties, resolve_llm_client
from blue_data_ops.llm.client import validate_llm_caller_controls
from blue_data_ops.llm.errors import LLMError, is_reply_failure, raise_reply_failure
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

    def _execute_bn(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
        *,
        _diagnose_registry: bool = False,
    ) -> FunctionResult:
        validate_llm_caller_controls(
            properties, service_prefix=str(self.DEFAULT_PROPERTIES.get("service_prefix", "openai"))
        )
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
            raise _MissingRegistryError()

        if _diagnose_registry:
            _diagnose_source(registry, source)
        schema_info, graph_structure = _resolve_schema_section(
            provided_schema, registry, source, database, collection
        )
        is_structured = graph_structure is not None
        merged = {**self.DEFAULT_PROPERTIES, **(properties or {})}
        merged = prepare_llm_operator_properties(merged, self.DEFAULT_PROPERTIES, properties)
        client = resolve_llm_client(merged)
        additional_data = {
            "question": question,
            "context": context,
            "schema_section": schema_info,
        }

        bn_query_data: dict[str, Any] = {}
        validation_errors: list[str] = []
        service_error: LLMError | None = None
        service_failure = False
        try:
            bn_query_result = client.execute_api_call(
                {}, properties=merged, additional_data=additional_data
            )
        except Exception as error:
            service_error = error if isinstance(error, LLMError) else None
            service_failure = not is_reply_failure(error)
            feedback = (
                "model reply did not match the operator's output format"
                if is_reply_failure(error)
                else "model request failed"
            )
            validation_errors.append("Service error: " + feedback)
        else:
            if isinstance(bn_query_result, str):
                try:
                    bn_query_result = json.loads(bn_query_result)
                except json.JSONDecodeError:
                    validation_errors.append("Invalid JSON response from LLM")
            if not validation_errors:
                if isinstance(bn_query_result, dict):
                    bn_query_data = cast(dict[str, Any], bn_query_result)
                else:
                    validation_errors.append("LLM response must be a query object")

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
            logger.info("Query validation found errors (attempt %s)", correction_attempts + 1)
            correction_data = {
                "question": question,
                "original_query": json.dumps(bn_query_data, indent=2),
                "validation_errors": json.dumps(validation_errors, indent=2),
                "schema_section": schema_info,
            }
            correction_properties = merged.copy()
            correction_properties["input_template"] = _CORRECTION_PROMPT
            correction_result = client.execute_api_call(
                {}, properties=correction_properties, additional_data=correction_data
            )
            service_error = None
            service_failure = False
            validation_errors = []
            if isinstance(correction_result, str):
                try:
                    correction_result = json.loads(correction_result)
                except json.JSONDecodeError:
                    validation_errors = ["Invalid JSON in corrected query"]
                    break
            if isinstance(correction_result, dict):
                bn_query_data = cast(dict[str, Any], correction_result)
            else:
                validation_errors = ["Corrected response must be a query object"]
                break
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
            logger.error("BN query validation failed")
            if service_error is not None:
                raise service_error
            if service_failure:
                raise ValueError("BN model request failed")
            raise_reply_failure()

        query_json = json.dumps(bn_query_data)
        logger.info("Generated BN query")
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
        logger.debug("BN query execution completed")

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

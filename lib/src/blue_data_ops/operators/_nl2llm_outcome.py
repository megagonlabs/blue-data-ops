from __future__ import annotations

from typing import Any, Literal

from blue_data_ops.llm.client import (
    LLMClient,
    _copy_operator_properties,  # pyright: ignore[reportPrivateUsage]
    _InvocationCostObservation,  # pyright: ignore[reportPrivateUsage]
    validate_llm_caller_controls,
)
from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.nl2llm_operator import NL2LLMOperator
from blue_data_ops.operators.types import (
    Attributes,
    DataBundle,
    ExecMeta,
    Properties,
    ValidationResult,
)


class _ObservedLLMClient(LLMClient):
    def __init__(self, observation: _InvocationCostObservation) -> None:
        self._observation = observation

    def execute_api_call(
        self,
        input: Any,  # noqa: A002
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        call_properties = _copy_operator_properties(properties)
        if call_properties.get("llm_client") is self:
            del call_properties["llm_client"]
        delegate = LLMClient(name="llm_client", properties=call_properties)
        return delegate._execute_api_call_observed(  # pyright: ignore[reportPrivateUsage]
            input,
            call_properties,
            additional_data,
            self._observation,
        )


class NL2LLMOutcomeOperator(_OutcomeOperator, NL2LLMOperator):
    """Reject blank structured queries before resolving a provider."""

    def _invalid_output_shape_reason(self) -> Literal["generic", "model_records"]:
        return "model_records"

    def run(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> tuple[DataBundle, Attributes, ExecMeta]:
        try:
            if properties is not None and not isinstance(properties, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
                return super().run(input_data, attributes, properties)
            if properties is not None and "llm_client" in properties:
                return super().run(input_data, attributes, properties)
            validate_llm_caller_controls(
                properties,
                service_prefix=str(self.DEFAULT_PROPERTIES.get("service_prefix", "openai")),
            )
            observed_properties = dict(properties or {})
            observation = _InvocationCostObservation()
            observed_properties["llm_client"] = _ObservedLLMClient(observation)
        except Exception:
            return super().run(input_data, attributes, properties)

        result = super().run(input_data, attributes, observed_properties)
        try:
            if not result[2].errors:
                cost = observation.complete_cost()
                if cost is not None:
                    traces = dict(result[2].traces)
                    traces.update({"cost": cost, "cost_basis": "estimated"})
                    metadata = result[2]._replace(traces=traces)
                    return result[0], result[1], metadata
        except Exception:
            pass
        return result

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        validation = super()._validate_input(input_data, attributes, properties)
        if not validation.ok:
            return validation
        query = attributes.get("query")
        if not isinstance(query, str) or not query.strip():
            return ValidationResult(False, "query must be a nonblank string")
        return validation

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Sized
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextvars import ContextVar
from copy import deepcopy
from math import isfinite
from typing import Any, ClassVar, Literal, ParamSpec, TypeVar, cast

from blue_data_ops.data.errors import REGISTRY_DIAGNOSTICS, owned_reason
from blue_data_ops.llm.errors import LLMError, is_reply_failure, is_sql_schema_failure
from blue_data_ops.operators._metadata import (
    definitions_from_specs,
    enrich_attribute_signature,
    project_specs,
)
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    DataBundle,
    ErrorCategory,
    ErrorCode,
    ErrorRecord,
    ErrorStage,
    ExecMeta,
    FunctionResult,
    Properties,
    ValidationResult,
    execution_diagnostic,
)
from blue_data_ops.tools import Tool
from blue_data_ops.utils.type_utils import string_to_python_type, validate_parameter_type

# Type parsing and value-type validation share one implementation in
# blue_data_ops.utils.type_utils. These private aliases preserve the
# former local helper names for in-package and white-box-test references without
# a second copy: _check_type is exactly the value-type validator.
_string_to_python_type = string_to_python_type
_check_type = validate_parameter_type

_INVALID_TIMEOUT_SUGGESTION = "execution.timeout_seconds must be a finite number greater than zero"
_MISSING_LLM_SUGGESTION = "Install blue-data-ops[llm] on Python 3.11 or later."
_UNSUPPORTED_LLM_SETTING_SUGGESTION = (
    "For temperature, set llm.temperature=null; otherwise remove the unsupported "
    "setting or choose a compatible model."
)
_TRUNCATED_LLM_SUGGESTION = "Increase llm.max_tokens; reasoning tokens use the same limit."
_CONFLICTING_LLM_LIMITS_SUGGESTION = "Set only one of max_tokens and max_completion_tokens."
_LLM_EXTRA_MODULES = frozenset({"diskcache", "jinja2", "litellm"})
_OPERATOR_ID_OVERRIDE: ContextVar[tuple[int, str] | None] = ContextVar(
    "blue_data_ops_operator_id_override",
    default=None,
)
_P = ParamSpec("_P")
_R = TypeVar("_R")


class _InvalidTimeout(ValueError):
    pass


def _call_with_operator_id(
    operator: Operator,
    operator_id: str,
    hook: Callable[_P, _R],
    *args: _P.args,
    **kwargs: _P.kwargs,
) -> _R:
    reset_handle = _OPERATOR_ID_OVERRIDE.set((id(operator), operator_id))
    try:
        return hook(*args, **kwargs)
    finally:
        _OPERATOR_ID_OVERRIDE.reset(reset_handle)


def apply_defaults(attributes: Attributes, schema: dict[str, AttributeSpec]) -> Attributes:
    """Copy call attributes and materialize declared optional defaults."""
    result = deepcopy(attributes)
    for name, spec in schema.items():
        if (
            name not in result
            and not spec.required
            and spec.has_default
            and spec.materialize_default
        ):
            result[name] = deepcopy(spec.default)
    return result


def _is_data_bundle(value: object) -> bool:
    if not isinstance(value, list):
        return False
    for group_value in cast(list[object], value):
        if not isinstance(group_value, list):
            return False
        if not all(isinstance(record, dict) for record in cast(list[object], group_value)):
            return False
    return True


def _pair_fields(value: object) -> tuple[object, object]:
    return cast(tuple[object, object], value)


def _call_hook(
    hook: Callable[[DataBundle, Attributes, Properties | None], object],
    input_data: DataBundle,
    attributes: Attributes,
    properties: Properties | None,
) -> object:
    return hook(input_data, attributes, properties)


def _validation_result(value: object) -> ValidationResult | None:
    if type(value) is not ValidationResult:
        return None
    ok, reason = _pair_fields(value)
    if type(ok) is not bool or (reason is not None and type(reason) is not str):
        return None
    return ValidationResult(ok, reason)


def _function_result(value: object) -> FunctionResult | None:
    if type(value) is not FunctionResult:
        return None
    output_data, output_attributes = _pair_fields(value)
    if not isinstance(output_attributes, dict):
        return None
    return FunctionResult(
        cast(DataBundle, output_data),
        cast(Attributes, output_attributes),
    )


def _normalize_data(value: DataBundle) -> tuple[DataBundle, bool]:
    if not _is_data_bundle(value):
        raise ValueError("invalid output shape")
    if not value or all(not group for group in value):
        return [[]], True
    return value, False


def _meta(*, is_empty: bool = False, error: ErrorRecord | None = None) -> ExecMeta:
    return ExecMeta(
        is_empty=is_empty,
        errors=[] if error is None else [error],
        logs=[],
        traces={},
    )


def _error(
    operator_id: str,
    category: ErrorCategory,
    code: ErrorCode,
    stage: ErrorStage,
    message: str,
    *,
    suggestion: str | None = None,
    retryable: bool = False,
) -> ErrorRecord:
    return ErrorRecord(
        category=category,
        code=code,
        operator_id=operator_id,
        stage=stage,
        message=message,
        retryable=retryable,
        suggestion=suggestion,
    )


def _timeout_seconds(properties: Properties | None) -> float | None:
    try:
        if properties is None or "execution.timeout_seconds" not in properties:
            return None
        value = properties["execution.timeout_seconds"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _InvalidTimeout
        timeout = float(value)
        if not isfinite(timeout) or timeout <= 0:
            raise _InvalidTimeout
        return timeout
    except _InvalidTimeout:
        raise
    except Exception:
        raise _InvalidTimeout from None


def _invalid_timeout_error(operator_id: str) -> ErrorRecord:
    return _error(
        operator_id,
        ErrorCategory.RECOVERABLE,
        ErrorCode.INVALID_INPUT,
        ErrorStage.VALIDATE,
        "invalid execution timeout",
        suggestion=_INVALID_TIMEOUT_SUGGESTION,
    )


def _execution_error(operator_id: str, exception: BaseException) -> ErrorRecord:
    custom = execution_diagnostic(exception)
    if custom is not None:
        message, suggestion, retryable = custom
        return _error(
            operator_id,
            ErrorCategory.FAILED,
            ErrorCode.EXECUTION_FAILED,
            ErrorStage.EXECUTE,
            message,
            suggestion=suggestion,
            retryable=retryable,
        )
    if is_sql_schema_failure(exception):
        return _error(
            operator_id,
            ErrorCategory.FAILED,
            ErrorCode.EXECUTION_FAILED,
            ErrorStage.EXECUTE,
            "generated SQL failed against the approved schema",
            suggestion="Rephrase the question or check the declared target and schema.",
        )
    if is_reply_failure(exception):
        return _error(
            operator_id,
            ErrorCategory.FAILED,
            ErrorCode.EXECUTION_FAILED,
            ErrorStage.EXECUTE,
            "model reply did not match the operator's output format",
            suggestion=(
                "Simplify the request or choose a model that follows the required output format."
            ),
        )
    if isinstance(exception, LLMError) and exception.code == "unsupported_parameter":
        return _error(
            operator_id,
            ErrorCategory.FAILED,
            ErrorCode.EXECUTION_FAILED,
            ErrorStage.EXECUTE,
            "model rejected a requested generation setting",
            suggestion=_UNSUPPORTED_LLM_SETTING_SUGGESTION,
        )
    if isinstance(exception, LLMError) and exception.code == "truncated_response":
        return _error(
            operator_id,
            ErrorCategory.FAILED,
            ErrorCode.EXECUTION_FAILED,
            ErrorStage.EXECUTE,
            "model output was cut off by the completion-token limit",
            suggestion=_TRUNCATED_LLM_SUGGESTION,
        )
    if isinstance(exception, LLMError) and exception.code == "conflicting_token_limits":
        return _error(
            operator_id,
            ErrorCategory.FAILED,
            ErrorCode.EXECUTION_FAILED,
            ErrorStage.EXECUTE,
            "conflicting LLM token limits",
            suggestion=_CONFLICTING_LLM_LIMITS_SUGGESTION,
        )
    missing = exception
    if not isinstance(missing, ModuleNotFoundError):
        missing = exception.__cause__
    if (
        isinstance(missing, ModuleNotFoundError)
        and type(missing.name) is str
        and missing.name in _LLM_EXTRA_MODULES
    ):
        return _error(
            operator_id,
            ErrorCategory.RECOVERABLE,
            ErrorCode.EXECUTION_FAILED,
            ErrorStage.EXECUTE,
            "LLM dependency is unavailable",
            suggestion=_MISSING_LLM_SUGGESTION,
        )
    if isinstance(exception, LLMError) and exception.code != "cache_unavailable":
        # Provider exception text can contain request or deployment details. Publish
        # only messages we own, while retaining the stable operator error code.
        llm_messages: dict[str, tuple[str, str]] = {
            "reserved_field": (
                "operator template and transport controls are reserved",
                (
                    "Remove caller template, extraction and transport controls; use a "
                    "host-configured operator."
                ),
            ),
            "sql_policy_invalid": (
                "invalid SQL execution policy",
                (
                    "Use a boolean execute_query and omit validate_query_prefixes or use a "
                    "one-item SELECT list; remove caller execution capabilities and registry "
                    "selectors when requesting execution."
                ),
            ),
            "sql_execution_unavailable": (
                "read-only SQL execution is not configured",
                (
                    "Request generation only, or ask the deployment owner to configure a "
                    "supported read-only SQL executor."
                ),
            ),
            "sql_target_denied": (
                "SQL target is outside the configured execution scope",
                "Use a target approved by the deployment owner, or request generation only.",
            ),
            "sql_query_rejected": (
                "generated SQL does not satisfy the read-only query contract",
                (
                    "Request one SELECT statement as a nonempty string; execution also "
                    "requires the database read-only guard."
                ),
            ),
            "provider_context": (
                "model request exceeds the context window",
                "Reduce input or context, or choose a model with a larger context window.",
            ),
            "provider_content": (
                "model provider refused the request content",
                "Revise the request or use a deployment-approved model.",
            ),
            "provider_rate_limit": (
                "model provider rate limit reached",
                "Wait before making another call.",
            ),
            "provider_timeout": (
                "model provider timed out",
                "Check provider availability before another call.",
            ),
            "provider_connection": (
                "model provider connection failed",
                "Check provider availability before another call.",
            ),
            "provider_unavailable": (
                "model provider is temporarily unavailable",
                "Try another call after provider recovery.",
            ),
            "provider_credentials": (
                "model provider rejected its credentials",
                "Check the provider credential in the deployment environment.",
            ),
            "provider_model_missing": (
                "model provider could not find the requested model",
                "Check the configured model name and provider access.",
            ),
            "sql_execution_failed": (
                "read-only SQL execution failed",
                (
                    "Ask the deployment owner to check the approved target and read-only "
                    "database configuration."
                ),
            ),
            "model_not_allowed": (
                "model is not allowed by this deployment",
                "Choose a model served and allowed by this deployment.",
            ),
            "no_model": (
                "no LLM model is configured",
                "Set llm.model or the operator's provider model setting.",
            ),
            "bad_override": (
                "LLM setting is not supported",
                "Use a documented llm.* or provider generation setting.",
            ),
            "bad_provider": (
                "deployment LLM provider is not recognized",
                "Check BLUE_DATA_LLM_PROVIDER in the deployment environment.",
            ),
            "bad_response": (
                "model provider returned an invalid response",
                "Check provider availability and response format.",
            ),
        }
        if exception.code == "provider_error":
            message, suggestion = (
                "model provider request failed",
                "Check provider availability and deployment settings.",
            )
        else:
            message, suggestion = llm_messages.get(
                exception.code or "",
                ("LLM request failed", "Check the model and LLM settings."),
            )
        return _error(
            operator_id,
            ErrorCategory.FAILED,
            ErrorCode.EXECUTION_FAILED,
            ErrorStage.EXECUTE,
            message,
            suggestion=suggestion,
            retryable=exception.code
            in {
                "provider_rate_limit",
                "provider_timeout",
                "provider_connection",
                "provider_unavailable",
            },
        )
    message, suggestion = REGISTRY_DIAGNOSTICS[owned_reason(exception)]
    return _error(
        operator_id,
        ErrorCategory.FAILED,
        ErrorCode.EXECUTION_FAILED,
        ErrorStage.EXECUTE,
        message,
        suggestion=suggestion,
    )


def _shutdown_executor(executor: ThreadPoolExecutor | None) -> None:
    if executor is None:
        return
    try:
        executor.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass


def default_operator_function(
    input_data: DataBundle,
    attributes: Attributes,
    properties: Properties | None = None,
) -> DataBundle:
    """Return the raw default output for an operator without a body."""
    del input_data, attributes, properties
    return []


def default_attributes_validator(
    attributes: Attributes,
    properties: Properties | None = None,
) -> bool:
    """Validate values against Blue-shaped live attribute definitions."""
    active_properties = {} if properties is None else properties
    definitions = active_properties.get("attributes", {})
    error_handling = active_properties.get("validation_error_handling", "fail")
    for name, definition in definitions.items():
        required = definition.get("required", False)
        if required and name not in attributes:
            return False
        if name not in attributes:
            continue
        type_name = definition.get("type")
        if not type_name:
            continue
        try:
            if not validate_parameter_type(attributes[name], type_name):
                return False
        except Exception:
            if error_handling == "fail":
                raise
            if error_handling == "log":
                return False
            logging.debug("attribute validation failed")
    return True


def default_operator_validator(
    input_data: DataBundle,
    attributes: Attributes,
    properties: Properties | None = None,
) -> bool:
    """Run the default attribute validator and contain its exceptions."""
    del input_data
    try:
        return default_attributes_validator(attributes, properties)
    except Exception:
        return False


def default_operator_explainer(
    output: Any,
    input_data: DataBundle,
    attributes: Attributes,
) -> dict[str, Any]:
    """Return Blue's default operator statistics."""
    total_input_records = sum(len(data) for data in input_data)
    output_count = len(cast(list[object], output)) if isinstance(output, list) else 1
    return {
        "output": output,
        "num_input_data": len(input_data),
        "num_input_records": total_input_records,
        "num_input_records_per_data": [len(data) for data in input_data],
        "num_output_data": len(cast(Sized, output)),
        "num_output_records": output_count,
        "transformation_ratio": (
            output_count / total_input_records if total_input_records > 0 else 0
        ),
        "attributes": attributes,
    }


# This behavior-carrying base stays beside the operators it validates, invokes, and
# explains; it is not a data-only interface.
class Operator(Tool, ABC):
    """Abstract base for a flat, single-output, type-aware data operator."""

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    attributes: ClassVar[dict[str, AttributeSpec]] = {}
    PROPERTIES: ClassVar[dict[str, Any]] = {}

    def __init__(
        self,
        name: str | None = None,
        function: Callable[..., Any] | None = None,
        description: str | None = None,
        properties: Properties | None = None,
        validator: Callable[..., Any] | None = None,
        explainer: Callable[..., Any] | None = None,
    ) -> None:
        class_name = type(self).name
        class_description = type(self).description
        resolved_name = class_name if name is None else name
        resolved_description = (
            class_description if name is None and description is None else description
        )
        resolved_function = self.apply if function is None else function
        resolved_validator = self.validate if validator is None else validator
        resolved_explainer = self.explain if explainer is None else explainer
        super().__init__(
            resolved_name,
            resolved_function,
            description=resolved_description,
            properties=properties,
            validator=resolved_validator,
            explainer=resolved_explainer,
        )
        object.__setattr__(self, "attributes", {})
        self._refresh_attribute_projection()

    def _initialize_missing_metadata(self) -> None:
        if object.__getattribute__(self, "__dict__").get("_metadata_initializing", False):
            raise AttributeError("operator metadata initialization is already active")
        object.__setattr__(self, "_metadata_initializing", True)
        try:
            Operator.__init__(self)
        finally:
            object.__setattr__(self, "_metadata_initializing", False)

    def _initialize_properties(self) -> None:
        super()._initialize_properties()
        self.properties.update(
            {
                "tool_type": "operator",
                "validate_input": True,
                "validate_output": True,
                "validation_error_handling": "fail",
                "max_records": None,
                "error_handling": "skip",
                "log_processing_stats": True,
                "attributes": {},
                "hyperparameters": {},
            }
        )
        definitions, materialize_defaults = definitions_from_specs(type(self).attributes)
        self.properties["attributes"] = definitions
        self._metadata_materialize_defaults = materialize_defaults
        for name, value in type(self).PROPERTIES.items():
            self.properties[name] = deepcopy(value)

    def _extract_signature(self) -> None:
        super()._extract_signature()
        definitions = cast(dict[str, Any], self.properties["attributes"])
        enrich_attribute_signature(self.properties["signature"], definitions)

    def _project_attribute_specs(self) -> dict[str, AttributeSpec]:
        return project_specs(
            self.properties.get("attributes"),
            self._metadata_materialize_defaults,
        )

    def _refresh_attribute_projection(self) -> dict[str, AttributeSpec]:
        projected = self._project_attribute_specs()
        current = self.attributes
        current.clear()
        current.update(projected)
        return current

    @property
    def operator_id(self) -> str:
        """Return the registry-bound ID, or the direct-call v2 identity."""
        override = _OPERATOR_ID_OVERRIDE.get()
        if override is not None and override[0] == id(self):
            return override[1]
        registered = getattr(self, "_registered_operator_id", None)
        return cast(str, registered) if registered is not None else f"{self.name}@2.0.0"

    def _bind_operator_id(self, operator_id: str) -> None:
        """Bind an unbound instance to one pinned registry identity."""
        registered = getattr(self, "_registered_operator_id", None)
        if registered is not None and registered != operator_id:
            raise ValueError(f"operator is already bound as {registered}")
        self._registered_operator_id = operator_id

    @abstractmethod
    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        """Transform input_data under attributes and return the operator output."""

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        """Validate attributes against the declared spec; total (never raises)."""
        return self._validate_attributes(attributes)

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        """Adapt the v1 boolean validator to the structured v2 boundary."""
        valid = self.validate(input_data, attributes, properties)
        if type(valid) is not bool:
            return ValidationResult(cast(bool, valid), None)
        return ValidationResult(valid, None if valid else "supply valid input attributes")

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        """Adapt the v1 single-output body to the v2 internal result."""
        return FunctionResult(self.apply(input_data, attributes, properties), {})

    def invoke(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle | None:
        """Validate unconditionally, then apply; return None when invalid."""
        if not self.validate(input_data, attributes, properties):
            return None
        return self.apply(input_data, attributes, properties)

    def run(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> tuple[DataBundle, Attributes, ExecMeta]:
        """Run the canonical v2 validation, execution, and result boundary."""
        try:
            timeout = _timeout_seconds(properties)
        except _InvalidTimeout:
            return [[]], {}, _meta(error=_invalid_timeout_error(self.operator_id))
        if timeout is None:
            return self._run_once(input_data, attributes, properties)

        executor: ThreadPoolExecutor | None = None
        try:
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="blue-data-ops")
            future = executor.submit(
                self._run_once,
                input_data,
                attributes,
                properties,
            )
        except Exception:
            _shutdown_executor(executor)
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.EXECUTION_FAILED,
                ErrorStage.EXECUTE,
                "operator execution failed",
            )
            return [[]], {}, _meta(error=error)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            try:
                future.cancel()
            except Exception:
                pass
            error = _error(
                self.operator_id,
                ErrorCategory.TIMEOUT,
                ErrorCode.OPERATOR_TIMEOUT,
                ErrorStage.EXECUTE,
                "operator timed out",
            )
            return [[]], {}, _meta(error=error)
        except Exception as exception:
            error = _execution_error(self.operator_id, exception)
            return [[]], {}, _meta(error=error)
        finally:
            _shutdown_executor(executor)

    def _run_once(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None,
    ) -> tuple[DataBundle, Attributes, ExecMeta]:
        try:
            schema = self._project_attribute_specs()
        except Exception:
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.VALIDATION_FAILED,
                ErrorStage.VALIDATE,
                "validator failed",
            )
            return [[]], {}, _meta(error=error)

        try:
            call_attributes = apply_defaults(attributes, schema)
        except Exception:
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.DEFAULTS_FAILED,
                ErrorStage.DEFAULTS,
                "default materialization failed",
            )
            return [[]], {}, _meta(error=error)

        try:
            validator: Callable[[DataBundle, Attributes, Properties | None], object] = (
                self._validate_input
            )
            validation_value = _call_hook(validator, input_data, call_attributes, properties)
        except Exception:
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.VALIDATION_FAILED,
                ErrorStage.VALIDATE,
                "validator failed",
            )
            return [[]], {}, _meta(error=error)

        try:
            validation = _validation_result(validation_value)
        except Exception:
            validation = None
        if validation is None:
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.VALIDATION_RESULT_INVALID,
                ErrorStage.VALIDATE,
                "validator returned an invalid result",
            )
            return [[]], {}, _meta(error=error)
        if not validation.ok:
            if not isinstance(validation.reason, str) or not validation.reason:
                error = _error(
                    self.operator_id,
                    ErrorCategory.FAILED,
                    ErrorCode.VALIDATION_RESULT_INVALID,
                    ErrorStage.VALIDATE,
                    "validator returned an invalid result",
                )
            else:
                error = _error(
                    self.operator_id,
                    ErrorCategory.RECOVERABLE,
                    ErrorCode.INVALID_INPUT,
                    ErrorStage.VALIDATE,
                    "input validation failed",
                    suggestion=validation.reason,
                )
            return [[]], {}, _meta(error=error)

        try:
            execute: Callable[[DataBundle, Attributes, Properties | None], object] = self._execute
            result_value = _call_hook(execute, input_data, call_attributes, properties)
        except Exception as exception:
            error = _execution_error(self.operator_id, exception)
            return [[]], {}, _meta(error=error)

        if result_value is None:
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.EXECUTION_FAILED,
                ErrorStage.EXECUTE,
                "operator execution failed",
            )
            return [[]], {}, _meta(error=error)

        try:
            result = _function_result(result_value)
        except Exception:
            result = None
        if result is None:
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.EXECUTION_RESULT_INVALID,
                ErrorStage.NORMALIZE,
                "operator returned an invalid result",
            )
            return [[]], {}, _meta(error=error)
        try:
            output_data, is_empty = _normalize_data(result.output_data)
        except Exception:
            try:
                model_records = self._invalid_output_shape_reason() == "model_records"
            except Exception:
                model_records = False
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.EXECUTION_RESULT_INVALID,
                ErrorStage.NORMALIZE,
                "model reply is not an array of records"
                if model_records
                else "operator returned an invalid result",
                suggestion="Request a JSON array of objects in the model reply."
                if model_records
                else None,
            )
            return [[]], {}, _meta(error=error)
        try:
            output_attributes = deepcopy(dict(result.output_attributes))
        except Exception:
            error = _error(
                self.operator_id,
                ErrorCategory.FAILED,
                ErrorCode.EXECUTION_RESULT_INVALID,
                ErrorStage.NORMALIZE,
                "operator returned an invalid result",
            )
            return [[]], {}, _meta(error=error)
        return output_data, output_attributes, _meta(is_empty=is_empty)

    def _invalid_output_shape_reason(self) -> Literal["generic", "model_records"]:
        return "generic"

    def explain(
        self,
        output: DataBundle,
        input_data: DataBundle,
        attributes: Attributes,
    ) -> dict[str, Any]:
        """Describe the transformation with input/output statistics."""
        return default_operator_explainer(output, input_data, attributes)

    def get_attributes(self) -> dict[str, dict[str, Any]]:
        """Return the live attribute definitions."""
        return cast(dict[str, dict[str, Any]], self.properties["attributes"])

    def update_attributes(
        self,
        attributes: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Update live attribute definitions and regenerate the signature."""
        if attributes is None:
            return
        self.get_attributes().update(attributes)
        self._extract_signature()
        self._refresh_attribute_projection()

    def get_attribute(self, attribute: str) -> dict[str, Any] | None:
        """Return one live attribute definition, if present."""
        return self.get_attributes().get(attribute)

    def get_attribute_type(self, attribute: str) -> Any:
        """Return one attribute type, if present."""
        definition = self.get_attribute(attribute)
        return definition.get("type") if definition else None

    def get_attribute_description(self, attribute: str) -> Any:
        """Return one attribute description, if present."""
        definition = self.get_attribute(attribute)
        return definition.get("description") if definition else None

    def set_attribute_description(self, attribute: str, description: str) -> None:
        """Set one attribute description and regenerate the signature."""
        definition = self.get_attribute(attribute)
        if definition:
            definition["description"] = description
            self._extract_signature()
            self._refresh_attribute_projection()

    def set_attribute_required(self, attribute: str, required: bool) -> None:
        """Set one attribute's required flag and regenerate the signature."""
        definition = self.get_attribute(attribute)
        if definition:
            definition["required"] = required
            self._extract_signature()
            self._refresh_attribute_projection()

    def set_attribute_hidden(self, attribute: str, hidden: bool) -> None:
        """Set one attribute's hidden flag and regenerate the signature."""
        definition = self.get_attribute(attribute)
        if definition:
            definition["hidden"] = hidden
            self._extract_signature()
            self._refresh_attribute_projection()

    def is_attribute_required(self, attribute: str) -> Any:
        """Return one attribute's required flag, if present."""
        definition = self.get_attribute(attribute)
        return definition.get("required") if definition else None

    def is_attribute_hidden(self, attribute: str) -> Any:
        """Return one attribute's hidden flag, if present."""
        definition = self.get_attribute(attribute)
        return definition.get("hidden") if definition else None

    def get_hyperparameters(self) -> dict[str, Any]:
        """Return the live hyperparameter definitions."""
        return cast(dict[str, Any], self.properties["hyperparameters"])

    def update_hyperparameters(self, hyperparameters: dict[str, Any] | None = None) -> None:
        """Update live hyperparameter definitions."""
        if hyperparameters is not None:
            self.get_hyperparameters().update(hyperparameters)

    @classmethod
    def is_operator(cls, value: object) -> bool:
        """Return whether a value carries Blue operator metadata."""
        return (
            hasattr(value, "properties")
            and getattr(value, "properties").get("tool_type") == "operator"
        )

    @classmethod
    def get_tool_type(cls, value: object) -> str:
        """Return operator for operator metadata and function otherwise."""
        return "operator" if cls.is_operator(value) else "function"

    def is_required(self, attribute: str) -> bool | None:
        """Report whether attribute is declared required (None if unknown)."""
        try:
            spec = self._project_attribute_specs().get(attribute)
        except Exception:
            return None
        return spec.required if spec is not None else None

    def default_of(self, attribute: str) -> Any:
        """Return the declared default for attribute (None if unknown or unset)."""
        try:
            spec = self._project_attribute_specs().get(attribute)
        except Exception:
            return None
        return spec.default if spec is not None else None

    def _validate_attributes(self, attributes: Attributes) -> bool:
        return default_operator_validator([[]], attributes, self.properties)


class _VersionBindingMixin:
    """Delegate one implementation through a separate pinned registry identity."""

    def __init__(self, target: Operator, operator_id: str) -> None:
        self._target = target
        self._registered_operator_id = operator_id
        object.__setattr__(self, "_properties", target.properties)
        object.__setattr__(
            self,
            "_metadata_materialize_defaults",
            target._metadata_materialize_defaults,  # pyright: ignore[reportPrivateUsage]
        )
        object.__setattr__(self, "name", target.name)
        object.__setattr__(self, "description", target.description)
        object.__setattr__(self, "attributes", target.attributes)

    @property
    def operator_id(self) -> str:
        override = _OPERATOR_ID_OVERRIDE.get()
        if override is not None and override[0] == id(self):
            return override[1]
        return self._registered_operator_id

    def __getattr__(self, name: str) -> Any:
        target = object.__getattribute__(self, "_target")
        return getattr(target, name)

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        return _call_with_operator_id(
            self._target,
            self.operator_id,
            self._target.apply,
            input_data,
            attributes,
            properties,
        )

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        return _call_with_operator_id(
            self._target,
            self.operator_id,
            self._target.validate,
            input_data,
            attributes,
            properties,
        )

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        return _call_with_operator_id(
            self._target,
            self.operator_id,
            self._target._validate_input,  # pyright: ignore[reportPrivateUsage]
            input_data,
            attributes,
            properties,
        )

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        return _call_with_operator_id(
            self._target,
            self.operator_id,
            self._target._execute,  # pyright: ignore[reportPrivateUsage]
            input_data,
            attributes,
            properties,
        )

    def invoke(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle | None:
        return _call_with_operator_id(
            self._target,
            self.operator_id,
            self._target.invoke,
            input_data,
            attributes,
            properties,
        )

    def explain(
        self,
        output: DataBundle,
        input_data: DataBundle,
        attributes: Attributes,
    ) -> dict[str, Any]:
        return _call_with_operator_id(
            self._target,
            self.operator_id,
            self._target.explain,
            output,
            input_data,
            attributes,
        )


class _VersionBoundOperator(  # pyright: ignore[reportUnusedClass]
    _VersionBindingMixin,
    Operator,
):
    """An operator registration bound to one ID without copying its implementation."""

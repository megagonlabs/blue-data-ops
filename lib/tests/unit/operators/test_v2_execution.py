from __future__ import annotations

import builtins
import time
from collections.abc import Callable
from dataclasses import asdict
from threading import Event
from typing import Any, cast

import litellm
import pytest

import blue_data_ops.operators.operator as operator_module
from blue_data_ops import (
    ABSENT,
    ErrorCategory,
    ErrorCode,
    ErrorStage,
    ExecMeta,
    FunctionResult,
    ValidationResult,
)
from blue_data_ops.llm.errors import LLMError
from blue_data_ops.operators import (
    Attributes,
    AttributeSpec,
    CreateDatabaseOperator,
    CreateTableOperator,
    DataBundle,
    DataDiscoverOperator,
    NL2LLMOperator,
    NormalizeTextOperator,
    Operator,
    OperatorRegistry,
    Properties,
    active_registry,
)
from blue_data_ops.operators.operator import apply_defaults


class CopyBomb:
    def __deepcopy__(self, memo: dict[int, object]) -> object:
        del memo
        raise RuntimeError("private copy payload")


class ProbeOperator(Operator):
    name = "probe"
    attributes = {
        "required": AttributeSpec(type="str", required=True, default="ignored"),
        "items": AttributeSpec(type="list", default=[]),
        "explicit_none": AttributeSpec(type="str", default=None),
    }

    def __init__(self, case: str = "success") -> None:
        self.case = case
        self.body_calls = 0

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        del attributes, properties
        return input_data

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        del input_data, properties
        if self.case == "invalid":
            return ValidationResult(False, "supply required")
        if self.case == "malformed_validation":
            return ValidationResult(cast(bool, 1), None)
        if self.case == "invalid_without_reason":
            return ValidationResult(False, None)
        if self.case == "validator_raises":
            raise RuntimeError("private validator payload")
        return ValidationResult("required" in attributes, "supply required")

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        del properties
        self.body_calls += 1
        if self.case == "raises":
            raise RuntimeError("private provider payload")
        if self.case == "missing_litellm":
            raise ModuleNotFoundError("private import payload", name="litellm")
        if self.case == "missing_other":
            raise ModuleNotFoundError("private import payload", name="other_package")
        if self.case == "none":
            return cast(FunctionResult, None)
        if self.case == "malformed":
            return FunctionResult(cast(DataBundle, "bad"), {})
        if self.case == "empty":
            return FunctionResult([], {"items": attributes["items"]})
        if self.case == "output_copy_fails":
            return FunctionResult(input_data, {"bad": CopyBomb()})
        return FunctionResult(input_data, {"items": attributes["items"]})


def test_public_v2_types_and_absent_default_are_exported() -> None:
    assert ABSENT is not None
    assert AttributeSpec(type="str").default is None
    assert AttributeSpec(type="str").has_default is False
    assert AttributeSpec(type="str").materialize_default is True
    assert AttributeSpec(type="str", default=None).has_default is True
    assert FunctionResult([[]], {}) == ([[]], {})
    assert ValidationResult(True, None) == (True, None)
    assert ExecMeta(False, [], [], {}) == (False, [], [], {})


def test_materialization_policy_preserves_attribute_spec_equality_and_repr() -> None:
    legacy = AttributeSpec(type="str", description="value", default=None)
    deferred = AttributeSpec(
        type="str",
        description="value",
        default=None,
        materialize_default=False,
    )

    assert deferred == legacy
    assert repr(deferred) == repr(legacy)
    assert "materialize_default" not in repr(deferred)
    assert asdict(deferred)["materialize_default"] is False


def test_default_materialization_can_preserve_omission_but_not_explicit_values() -> None:
    schema = {
        "legacy": AttributeSpec(type="list", default=[]),
        "deferred": AttributeSpec(type="list", default=[], materialize_default=False),
        "required": AttributeSpec(
            type="str",
            required=True,
            default="ignored",
            materialize_default=False,
        ),
    }

    first = apply_defaults({}, schema)
    second = apply_defaults({}, schema)
    explicit: list[str] = []
    supplied = apply_defaults({"deferred": explicit}, schema)

    assert first == {"legacy": []}
    assert second == first
    assert first["legacy"] is not second["legacy"]
    assert supplied == {"legacy": [], "deferred": []}
    assert supplied["deferred"] is not explicit
    assert "required" not in first


def test_only_incompatible_defaults_defer_materialization() -> None:
    deferred = {
        CreateDatabaseOperator.name: {
            name
            for name, spec in CreateDatabaseOperator.attributes.items()
            if not spec.materialize_default
        },
        CreateTableOperator.name: {
            name
            for name, spec in CreateTableOperator.attributes.items()
            if not spec.materialize_default
        },
        DataDiscoverOperator.name: {
            name
            for name, spec in DataDiscoverOperator.attributes.items()
            if not spec.materialize_default
        },
    }

    assert deferred == {
        "create_database": {"properties"},
        "create_table": {"properties"},
        "data_discover": {"scope", "source", "database", "collection"},
    }


@pytest.mark.parametrize(
    ("operator", "attributes"),
    [
        (
            CreateDatabaseOperator(),
            {"source": "src", "database": "db", "properties": {}},
        ),
        (
            CreateTableOperator(),
            {
                "source": "src",
                "database": "db",
                "table": "t",
                "columns": [{"name": "a"}],
                "properties": {},
            },
        ),
        (
            DataDiscoverOperator(),
            {"search_query": "orders", "approximate": False, "scope": None},
        ),
        (
            DataDiscoverOperator(),
            {"search_query": "orders", "approximate": False, "source": None},
        ),
        (
            DataDiscoverOperator(),
            {"search_query": "orders", "approximate": False, "database": None},
        ),
        (
            DataDiscoverOperator(),
            {"search_query": "orders", "approximate": False, "collection": None},
        ),
    ],
)
def test_explicit_incompatible_defaults_remain_subject_to_validation(
    operator: Operator,
    attributes: Attributes,
) -> None:
    output_data, output_attributes, meta = operator.run([[]], attributes)

    assert output_data == [[]]
    assert output_attributes == {}
    assert len(meta.errors) == 1
    assert meta.errors[0].category is ErrorCategory.RECOVERABLE
    assert meta.errors[0].code is ErrorCode.INVALID_INPUT
    assert meta.errors[0].stage is ErrorStage.VALIDATE


def test_optional_defaults_are_fresh_and_required_defaults_do_not_apply() -> None:
    first = apply_defaults({"required": "given"}, ProbeOperator.attributes)
    second = apply_defaults({"required": "given", "explicit_none": None}, ProbeOperator.attributes)

    assert first == {"required": "given", "items": [], "explicit_none": None}
    assert second == first
    assert first["items"] is not second["items"]
    assert "required" not in apply_defaults({}, ProbeOperator.attributes)


def test_normalize_text_proves_pure_operator_compatibility() -> None:
    operator = NormalizeTextOperator()
    source = [[{"text": " A\u00a0 B "}]]
    attributes = {"text_field": ["text"]}
    raw = operator.apply(source, attributes)
    output_data, output_attributes, meta = operator.run(source, attributes)

    assert output_data == raw
    assert output_attributes == {}
    assert meta == ExecMeta(False, [], [], {})
    assert attributes == {"text_field": ["text"]}
    assert operator.invoke(source, attributes) == raw
    assert operator.validate(source, attributes) is True


def test_v1_validator_adapts_to_recoverable_v2_error() -> None:
    operator = NormalizeTextOperator()
    output_data, output_attributes, meta = operator.run([[{"text": "x"}]], {"keys": ["text"]})

    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert len(meta.errors) == 1
    assert meta.errors[0] == (
        ErrorCategory.RECOVERABLE,
        ErrorCode.INVALID_INPUT,
        "normalize_text@2.0.0",
        ErrorStage.VALIDATE,
        "input validation failed",
        False,
        "supply valid input attributes",
    )


def test_registry_binding_supplies_the_pinned_error_identity() -> None:
    operator = NormalizeTextOperator()
    registry = OperatorRegistry()
    registry.register(operator, "1.0.0")
    _, _, meta = operator.run([[]], {})
    assert meta.errors[0].operator_id == "normalize_text@1.0.0"


def test_one_instance_can_back_two_version_bound_registry_entries() -> None:
    operator = NormalizeTextOperator()
    registry = OperatorRegistry()
    registry.register(operator, "1.0.0")
    registry.register(operator, "2.0.0")

    v1 = registry.resolve("normalize_text@1.0.0")
    v2 = registry.resolve("normalize_text@2.0.0")
    assert v1 is operator
    assert v2 is not operator
    assert v1.operator_id == "normalize_text@1.0.0"
    assert v2.operator_id == "normalize_text@2.0.0"
    assert v1.run([[]], {})[2].errors[0].operator_id == "normalize_text@1.0.0"
    assert v2.run([[]], {})[2].errors[0].operator_id == "normalize_text@2.0.0"

    registry.register(v2, "3.0.0")
    v3 = registry.resolve("normalize_text@3.0.0")
    assert v3.operator_id == "normalize_text@3.0.0"
    assert v3.run([[]], {})[2].errors[0].operator_id == "normalize_text@3.0.0"


class IdentityAwareOperator(ProbeOperator):
    name = "identity_aware"

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        del attributes, properties
        return FunctionResult(input_data, {"seen_operator_id": self.operator_id})


def test_version_bound_hook_sees_exact_identity_inside_timeout_worker() -> None:
    source = IdentityAwareOperator()
    registry = OperatorRegistry()
    registry.register(source, "1.0.0")
    registry.register(source, "2.0.0")
    registry.register(registry.resolve("identity_aware@2.0.0"), "3.0.0")

    for version in ("1.0.0", "2.0.0", "3.0.0"):
        operator = registry.resolve(f"identity_aware@{version}")
        _, output_attributes, meta = operator.run(
            [[]],
            {"required": "given"},
            {"execution.timeout_seconds": 1},
        )
        assert output_attributes == {"seen_operator_id": f"identity_aware@{version}"}
        assert meta.errors == []


@pytest.mark.parametrize(
    "case,code,stage,body_calls",
    [
        ("invalid", ErrorCode.INVALID_INPUT, ErrorStage.VALIDATE, 0),
        ("malformed_validation", ErrorCode.VALIDATION_RESULT_INVALID, ErrorStage.VALIDATE, 0),
        ("invalid_without_reason", ErrorCode.VALIDATION_RESULT_INVALID, ErrorStage.VALIDATE, 0),
        ("validator_raises", ErrorCode.VALIDATION_FAILED, ErrorStage.VALIDATE, 0),
        ("raises", ErrorCode.EXECUTION_FAILED, ErrorStage.EXECUTE, 1),
        ("none", ErrorCode.EXECUTION_FAILED, ErrorStage.EXECUTE, 1),
        ("malformed", ErrorCode.EXECUTION_RESULT_INVALID, ErrorStage.NORMALIZE, 1),
        ("output_copy_fails", ErrorCode.EXECUTION_RESULT_INVALID, ErrorStage.NORMALIZE, 1),
    ],
)
def test_failure_rows_are_total(
    case: str,
    code: ErrorCode,
    stage: ErrorStage,
    body_calls: int,
) -> None:
    operator = ProbeOperator(case)
    output_data, output_attributes, meta = operator.run([[]], {"required": "given"})
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert meta.errors[0].code is code
    assert meta.errors[0].stage is stage
    assert "private" not in meta.errors[0].message
    assert operator.body_calls == body_calls


def test_missing_litellm_uses_the_existing_code_with_actionable_fields() -> None:
    _, _, meta = ProbeOperator("missing_litellm").run([[]], {"required": "given"})
    [error] = meta.errors
    assert error.category is ErrorCategory.RECOVERABLE
    assert error.code is ErrorCode.EXECUTION_FAILED
    assert error.stage is ErrorStage.EXECUTE
    assert error.message == "LLM dependency is unavailable"
    assert error.retryable is False
    assert error.suggestion == "Install blue-data-ops[llm] on Python 3.11 or later."


def test_missing_llm_extras_keep_recoverable_errors_when_wrapped() -> None:
    for missing in ("litellm", "jinja2", "diskcache"):
        for code in (None, "provider_error", "cache_unavailable"):
            for wrapped in (False, True):

                class MissingExtraOperator(ProbeOperator):
                    def _execute(
                        self,
                        input_data: DataBundle,
                        attributes: Attributes,
                        properties: Properties | None = None,
                    ) -> FunctionResult:
                        del input_data, attributes, properties
                        dependency = ModuleNotFoundError("private import payload", name=missing)
                        if wrapped:
                            raise LLMError("private LLM payload", code=code) from dependency
                        raise dependency

                output, attributes, meta = MissingExtraOperator().run([[]], {"required": "given"})
                [error] = meta.errors
                assert output == [[]]
                assert attributes == {}
                assert error.category is ErrorCategory.RECOVERABLE
                assert error.code is ErrorCode.EXECUTION_FAILED
                assert error.stage is ErrorStage.EXECUTE
                assert error.message == "LLM dependency is unavailable"
                assert error.retryable is False
                assert error.suggestion == "Install blue-data-ops[llm] on Python 3.11 or later."
                assert "private" not in str(error)


@pytest.mark.parametrize(
    "missing,properties",
    [
        ("jinja2", None),
        ("litellm", None),
        ("diskcache", {"llm.cache": True}),
    ],
)
def test_real_llm_path_names_the_missing_extra_dependency(
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
    properties: dict[str, Any] | None,
) -> None:
    original_import = builtins.__import__

    def blocked_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.split(".", 1)[0] == missing:
            raise ModuleNotFoundError(f"blocked optional dependency {missing!r}", name=missing)
        return original_import(name, *args, **kwargs)

    if missing == "jinja2":
        from tests.unit.operators import test_nl2llm as nl2llm_tests

        _json_provider = cast(
            Callable[[str, pytest.MonkeyPatch], None], vars(nl2llm_tests)["_json_provider"]
        )

        _json_provider("[]", monkeypatch)
    monkeypatch.setattr(builtins, "__import__", blocked_import)
    _, _, meta = NL2LLMOperator().run(
        [[]],
        {"query": "Return an empty JSON array."},
        properties,
    )
    if missing == "jinja2":
        assert meta.errors == []
        return
    [error] = meta.errors
    assert error.category is ErrorCategory.RECOVERABLE
    assert error.code is ErrorCode.EXECUTION_FAILED
    assert error.stage is ErrorStage.EXECUTE
    assert error.message == "LLM dependency is unavailable"
    assert error.suggestion == "Install blue-data-ops[llm] on Python 3.11 or later."


def test_an_unrelated_missing_module_keeps_the_generic_contained_failure() -> None:
    _, _, meta = ProbeOperator("missing_other").run([[]], {"required": "given"})
    [error] = meta.errors
    assert error.category is ErrorCategory.FAILED
    assert error.code is ErrorCode.EXECUTION_FAILED
    assert error.message == "operator execution failed"
    assert error.suggestion == "Check the declared inputs and backend configuration."


def test_an_unsupported_llm_setting_is_actionable_without_provider_detail() -> None:
    private_detail = "provider-private-unsupported-detail"
    litellm.calls.clear()
    litellm.fail_next.clear()
    litellm.fail_next.append(
        litellm.BadRequestError(
            private_detail,
            body={
                "error": {
                    "message": private_detail,
                    "param": "reasoning_effort",
                    "code": "unsupported_parameter",
                }
            },
        )
    )
    try:
        _, _, meta = (
            active_registry()
            .resolve("nl2llm@3.0.0")
            .run(
                [[]],
                {"query": "Return an empty JSON array."},
                {"llm.reasoning_effort": "high"},
            )
        )
    finally:
        litellm.fail_next.clear()

    [error] = meta.errors
    assert error.category is ErrorCategory.FAILED
    assert error.code is ErrorCode.EXECUTION_FAILED
    assert error.stage is ErrorStage.EXECUTE
    assert error.message == "model rejected a requested generation setting"
    assert error.retryable is False
    assert error.suggestion == (
        "For temperature, set llm.temperature=null; otherwise remove the unsupported "
        "setting or choose a compatible model."
    )
    assert private_detail not in str(error)
    assert len(litellm.calls) == 1
    assert "cost" not in meta.traces
    assert "cost_basis" not in meta.traces


def test_llm_execution_errors_are_actionable_without_provider_text() -> None:
    cases = (
        ("reserved_field", None, "operator template and transport controls are reserved"),
        ("model_not_allowed", None, "model is not allowed"),
        ("bad_override", None, "setting is not supported"),
        ("provider_error", 401, "provider request failed"),
        ("provider_error", 404, "provider request failed"),
        ("provider_error", None, "provider request failed"),
    )
    for code, status, expected in cases:

        class ProviderFailure(Exception):
            status_code = status

        error = operator_module._execution_error(  # pyright: ignore[reportPrivateUsage]
            "nl2llm@3.0.0",
            LLMError(
                "private provider detail",
                code=code,
                provider_error=ProviderFailure("private provider detail"),
            ),
        )
        assert error.code is ErrorCode.EXECUTION_FAILED
        assert expected in error.message
        assert error.suggestion
        assert "private provider detail" not in str(error)


def test_mock_response_refusal_has_a_safe_actionable_operator_message() -> None:
    import litellm

    litellm.calls.clear()
    _, _, meta = NL2LLMOperator().run(
        [[]],
        {"query": "Return an empty JSON array."},
        {"openai.mock_response": "private substituted response"},
    )
    [error] = meta.errors
    assert error.code is ErrorCode.EXECUTION_FAILED
    assert error.message == "operator template and transport controls are reserved"
    assert error.suggestion == (
        "Remove caller template, extraction and transport controls; use a host-configured operator."
    )
    assert error.retryable is False
    assert "private substituted response" not in str(error)
    assert litellm.calls == []


def test_successful_empty_preserves_fresh_output_attributes() -> None:
    operator = ProbeOperator("empty")
    first = operator.run([[]], {"required": "given"})
    second = operator.run([[]], {"required": "given"})
    assert first[0] == [[]]
    assert first[1] == {"items": []}
    assert first[2].is_empty is True
    assert first[1] is not second[1]
    assert first[1]["items"] is not second[1]["items"]
    assert first[2].errors is not second[2].errors
    assert first[2].logs is not second[2].logs
    assert first[2].traces is not second[2].traces


class WrongTypeDeepcopyAttributes(dict[str, Any]):
    def __deepcopy__(self, memo: dict[int, object]) -> object:
        del memo
        return []


class SelfDeepcopyAttributes(dict[str, Any]):
    def __deepcopy__(self, memo: dict[int, object]) -> object:
        del memo
        return self


@pytest.mark.parametrize(
    "attribute_type",
    [WrongTypeDeepcopyAttributes, SelfDeepcopyAttributes],
)
def test_output_attributes_normalize_to_a_fresh_plain_dict(
    attribute_type: type[dict[str, Any]],
) -> None:
    source_attributes = attribute_type({"items": []})

    class AttributeProbe(ProbeOperator):
        def _execute(
            self,
            input_data: DataBundle,
            attributes: Attributes,
            properties: Properties | None = None,
        ) -> FunctionResult:
            del attributes, properties
            return FunctionResult(input_data, source_attributes)

    first = AttributeProbe().run([[]], {"required": "given"})
    second = AttributeProbe().run([[]], {"required": "given"})
    assert type(first[1]) is dict
    assert first[1] == {"items": []}
    assert first[1] is not source_attributes
    assert first[1] is not second[1]
    assert first[1]["items"] is not second[1]["items"]
    assert first[2].errors == []


class BrokenDefaultOperator(ProbeOperator):
    attributes = {"bad": AttributeSpec(type="str", default=CopyBomb())}


def test_default_copy_failure_is_canonical() -> None:
    operator = BrokenDefaultOperator()
    output_data, output_attributes, meta = operator.run([[]], {})
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.errors[0].code is ErrorCode.DEFAULTS_FAILED
    assert meta.errors[0].stage is ErrorStage.DEFAULTS
    assert operator.body_calls == 0


class FloatBomb(float):
    def __float__(self) -> float:
        raise RuntimeError("private timeout payload")


@pytest.mark.parametrize(
    "value",
    ["0.001", -1, 0, True, float("nan"), float("inf"), FloatBomb(1.0), 10**400],
    ids=["string", "negative", "zero", "bool", "nan", "inf", "float-bomb", "huge-int"],
)
def test_invalid_timeout_is_recoverable_and_suppresses_body(value: object) -> None:
    operator = ProbeOperator()
    output_data, output_attributes, meta = operator.run(
        [[]],
        {"required": "given"},
        {"execution.timeout_seconds": value},
    )
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.errors[0] == (
        ErrorCategory.RECOVERABLE,
        ErrorCode.INVALID_INPUT,
        "probe@2.0.0",
        ErrorStage.VALIDATE,
        "invalid execution timeout",
        False,
        "execution.timeout_seconds must be a finite number greater than zero",
    )
    assert operator.body_calls == 0


class SlowOperator(ProbeOperator):
    def __init__(self, finished: Event) -> None:
        super().__init__()
        self.finished = finished

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        del attributes, properties
        self.body_calls += 1
        time.sleep(0.04)
        self.finished.set()
        return FunctionResult(input_data, {"late": True})


def test_positive_timeout_discards_late_result_without_retry() -> None:
    finished = Event()
    operator = SlowOperator(finished)
    output_data, output_attributes, meta = operator.run(
        [[{"x": 1}]],
        {"required": "given"},
        {"execution.timeout_seconds": 0.005},
    )
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.errors[0].code is ErrorCode.OPERATOR_TIMEOUT
    assert meta.errors[0].stage is ErrorStage.EXECUTE
    assert operator.body_calls == 1
    assert finished.wait(timeout=0.2)


def test_legacy_timeout_property_is_inert() -> None:
    operator = ProbeOperator()
    output_data, _, meta = operator.run(
        [[{"x": 1}]],
        {"required": "given"},
        {"timeout": 0},
    )
    assert output_data == [[{"x": 1}]]
    assert meta.errors == []


class ConstructorBomb:
    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("private executor payload")


class FutureBomb:
    def result(self, timeout: float | None = None) -> object:
        del timeout
        raise RuntimeError("private future payload")

    def cancel(self) -> bool:
        return False


class FutureBombExecutor:
    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def submit(self, *args: object, **kwargs: object) -> FutureBomb:
        del args, kwargs
        return FutureBomb()

    def shutdown(self, *args: object, **kwargs: object) -> None:
        del args, kwargs


def test_executor_construction_failure_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(operator_module, "ThreadPoolExecutor", ConstructorBomb)
    operator = ProbeOperator()
    _, _, meta = operator.run(
        [[]],
        {"required": "given"},
        {"execution.timeout_seconds": 1},
    )
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert meta.errors[0].message == "operator execution failed"
    assert operator.body_calls == 0


def test_future_failure_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(operator_module, "ThreadPoolExecutor", FutureBombExecutor)
    operator = ProbeOperator()
    _, _, meta = operator.run(
        [[]],
        {"required": "given"},
        {"execution.timeout_seconds": 1},
    )
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert meta.errors[0].message == "operator execution failed"
    assert operator.body_calls == 0


class IterationBomb(list[object]):
    def __iter__(self) -> Any:
        raise RuntimeError("private output payload")


class HostileResultOperator(ProbeOperator):
    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        del input_data, attributes, properties
        self.body_calls += 1
        return FunctionResult(cast(DataBundle, IterationBomb([{}])), {})


def test_hostile_result_container_is_redacted() -> None:
    _, _, meta = HostileResultOperator().run([[]], {"required": "given"})
    assert meta.errors[0].code is ErrorCode.EXECUTION_RESULT_INVALID
    assert meta.errors[0].message == "operator returned an invalid result"

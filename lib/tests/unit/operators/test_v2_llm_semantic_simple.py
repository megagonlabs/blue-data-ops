from __future__ import annotations

import time
from collections.abc import Sequence
from threading import Event
from typing import Any
from unittest.mock import patch

import pytest

from blue_data_ops import (
    ErrorCategory,
    ErrorCode,
    ErrorStage,
    FunctionResult,
    ValidationResult,
)
from blue_data_ops.llm import LLMClient
from blue_data_ops.operators import (
    Attributes,
    DataBundle,
    Operator,
    OperatorRegistry,
    Properties,
    SemanticExtractOperator,
    SemanticFilterOperator,
    SemanticProjectOperator,
)

EXTRACT_INPUT: DataBundle = [[{"id": 1, "name": "Ada", "bio": "Ada uses Python"}]]
EXTRACT_ATTRIBUTES: Attributes = {"entities": [{"name": "skill"}]}
FILTER_INPUT: DataBundle = [[{"id": 1, "score": 8}]]
FILTER_ATTRIBUTES: Attributes = {"filter_conditions": {"score": "is high"}}
PROJECT_INPUT: DataBundle = [[{"id": 1, "name": "Ada"}]]
PROJECT_ATTRIBUTES: Attributes = {"projection_instructions": "keep and rename name"}


class ScriptedClient(LLMClient):
    def __init__(self, responses: Sequence[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[Any, dict[str, Any] | None, dict[str, Any] | None]] = []

    def execute_api_call(
        self,
        input: Any,  # noqa: A002
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append((input, properties, additional_data))
        if not self.responses:
            raise AssertionError("provider response queue exhausted")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


@pytest.mark.parametrize(
    ("operator", "input_data", "valid_attributes", "invalid_attributes"),
    [
        (
            SemanticExtractOperator(),
            EXTRACT_INPUT,
            EXTRACT_ATTRIBUTES,
            {"entities": []},
        ),
        (
            SemanticFilterOperator(),
            FILTER_INPUT,
            FILTER_ATTRIBUTES,
            {"filter_conditions": {}},
        ),
        (
            SemanticProjectOperator(),
            PROJECT_INPUT,
            PROJECT_ATTRIBUTES,
            {"projection_instructions": " "},
        ),
    ],
)
def test_native_validation_keeps_exact_boolean_adapter(
    operator: Operator,
    input_data: DataBundle,
    valid_attributes: Attributes,
    invalid_attributes: Attributes,
) -> None:
    assert "_execute" in type(operator).__dict__
    assert "_validate_input" in type(operator).__dict__

    valid = operator._validate_input(  # pyright: ignore[reportPrivateUsage]
        input_data,
        valid_attributes,
    )
    invalid = operator._validate_input(  # pyright: ignore[reportPrivateUsage]
        input_data,
        invalid_attributes,
    )

    assert type(valid) is ValidationResult
    assert valid == ValidationResult(True, None)
    assert type(invalid) is ValidationResult
    assert invalid.ok is False
    assert invalid.reason
    assert operator.validate(input_data, valid_attributes) is True
    assert operator.validate(input_data, invalid_attributes) is False


@pytest.mark.parametrize(
    ("operator", "input_data", "attributes", "response", "expected"),
    [
        (
            SemanticExtractOperator(),
            EXTRACT_INPUT,
            EXTRACT_ATTRIBUTES,
            {"skill": ["Python"]},
            [[{"skill": ["Python"]}]],
        ),
        (
            SemanticFilterOperator(),
            FILTER_INPUT,
            FILTER_ATTRIBUTES,
            "yes",
            FILTER_INPUT,
        ),
        (
            SemanticProjectOperator(),
            PROJECT_INPUT,
            PROJECT_ATTRIBUTES,
            {"name": "person"},
            [[{"person": "Ada"}]],
        ),
    ],
)
def test_native_execution_matches_raw_apply(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
    response: Any,
    expected: DataBundle,
) -> None:
    client = ScriptedClient([response, response])
    properties: Properties = {"llm_client": client}

    native = operator._execute(  # pyright: ignore[reportPrivateUsage]
        input_data,
        attributes,
        properties,
    )
    raw = operator.apply(input_data, attributes, properties)

    assert type(native) is FunctionResult
    assert native.output_data == raw == expected
    assert native.output_attributes == {}
    assert len(client.calls) == 2


@pytest.mark.parametrize(
    ("operator", "input_data", "attributes", "response", "expected"),
    [
        (
            SemanticExtractOperator(),
            EXTRACT_INPUT,
            EXTRACT_ATTRIBUTES,
            {"skill": ["Python"]},
            [[{"skill": ["Python"]}]],
        ),
        (
            SemanticFilterOperator(),
            FILTER_INPUT,
            FILTER_ATTRIBUTES,
            True,
            FILTER_INPUT,
        ),
        (
            SemanticProjectOperator(),
            PROJECT_INPUT,
            PROJECT_ATTRIBUTES,
            {"name": "person"},
            [[{"person": "Ada"}]],
        ),
    ],
)
def test_run_calls_native_body_and_provider_once(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
    response: Any,
    expected: DataBundle,
) -> None:
    client = ScriptedClient([response])
    with patch.object(
        operator,
        "_execute",
        wraps=operator._execute,  # pyright: ignore[reportPrivateUsage]
    ) as execute:
        output_data, output_attributes, meta = operator.run(
            input_data,
            attributes,
            {"llm_client": client},
        )

    assert execute.call_count == 1
    assert len(client.calls) == 1
    assert output_data == expected
    assert output_attributes == {}
    assert meta.is_empty is False
    assert meta.errors == []


@pytest.mark.parametrize(
    ("operator", "attributes"),
    [
        (SemanticExtractOperator(), EXTRACT_ATTRIBUTES),
        (SemanticFilterOperator(), FILTER_ATTRIBUTES),
        (SemanticProjectOperator(), PROJECT_ATTRIBUTES),
    ],
)
def test_empty_input_is_successful_without_provider(
    operator: Operator,
    attributes: Attributes,
) -> None:
    client = ScriptedClient([])
    output_data, output_attributes, meta = operator.run(
        [[]],
        attributes,
        {"llm_client": client},
    )

    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is True
    assert meta.errors == []
    assert client.calls == []


@pytest.mark.parametrize(  # pyright: ignore[reportUnknownArgumentType]
    ("operator", "input_data", "attributes", "response", "expected", "is_empty"),
    [  # pyright: ignore[reportUnknownArgumentType]
        (
            SemanticExtractOperator(),
            EXTRACT_INPUT,
            EXTRACT_ATTRIBUTES,
            ["not a mapping"],
            [[{"skill": []}]],
            False,
        ),
        (
            SemanticFilterOperator(),
            FILTER_INPUT,
            FILTER_ATTRIBUTES,
            "false",
            [[]],
            True,
        ),
        (
            SemanticProjectOperator(),
            PROJECT_INPUT,
            PROJECT_ATTRIBUTES,
            ["not a mapping"],
            [[]],
            True,
        ),
    ],
)
def test_tolerated_provider_results_remain_successful(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
    response: Any,
    expected: DataBundle,
    is_empty: bool,
) -> None:
    client = ScriptedClient([response, response])
    properties: Properties = {"llm_client": client}

    assert operator.apply(input_data, attributes, properties) == expected
    output_data, output_attributes, meta = operator.run(input_data, attributes, properties)

    assert output_data == expected
    assert output_attributes == {}
    assert meta.is_empty is is_empty
    assert meta.errors == []
    assert len(client.calls) == 2


@pytest.mark.parametrize(
    ("operator", "input_data", "invalid_attributes"),
    [
        (SemanticExtractOperator(), EXTRACT_INPUT, {"entities": []}),
        (SemanticFilterOperator(), FILTER_INPUT, {"filter_conditions": {}}),
        (SemanticProjectOperator(), PROJECT_INPUT, {"projection_instructions": ""}),
    ],
)
def test_invalid_input_is_recoverable_and_suppresses_execution(
    operator: Operator,
    input_data: DataBundle,
    invalid_attributes: Attributes,
) -> None:
    client = ScriptedClient([])
    with patch.object(
        operator,
        "_execute",
        side_effect=AssertionError("execution must be suppressed"),
    ) as execute:
        output_data, output_attributes, meta = operator.run(
            input_data,
            invalid_attributes,
            {"llm_client": client},
        )

    assert execute.call_count == 0
    assert client.calls == []
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert len(meta.errors) == 1
    error = meta.errors[0]
    assert error.category is ErrorCategory.RECOVERABLE
    assert error.code is ErrorCode.INVALID_INPUT
    assert error.stage is ErrorStage.VALIDATE
    assert error.operator_id == f"{operator.name}@2.0.0"
    assert error.suggestion


@pytest.mark.parametrize(
    ("operator", "input_data", "attributes"),
    [
        (SemanticExtractOperator(), EXTRACT_INPUT, EXTRACT_ATTRIBUTES),
        (SemanticFilterOperator(), FILTER_INPUT, FILTER_ATTRIBUTES),
        (SemanticProjectOperator(), PROJECT_INPUT, PROJECT_ATTRIBUTES),
    ],
)
def test_provider_failure_stays_raw_and_run_contains_it(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
) -> None:
    detail = "private provider payload"
    client = ScriptedClient([RuntimeError(detail), RuntimeError(detail)])
    properties: Properties = {"llm_client": client}

    with pytest.raises(RuntimeError, match=detail):
        operator.apply(input_data, attributes, properties)
    output_data, output_attributes, meta = operator.run(input_data, attributes, properties)

    assert len(client.calls) == 2
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert len(meta.errors) == 1
    error = meta.errors[0]
    assert error.category is ErrorCategory.FAILED
    assert error.code is ErrorCode.EXECUTION_FAILED
    assert error.stage is ErrorStage.EXECUTE
    assert error.operator_id == f"{operator.name}@2.0.0"
    assert detail not in str(error)


@pytest.mark.parametrize(
    ("operator", "input_data", "attributes"),
    [
        (SemanticExtractOperator(), EXTRACT_INPUT, EXTRACT_ATTRIBUTES),
        (SemanticFilterOperator(), FILTER_INPUT, FILTER_ATTRIBUTES),
        (SemanticProjectOperator(), PROJECT_INPUT, PROJECT_ATTRIBUTES),
    ],
)
def test_malformed_native_result_is_rejected_by_normalizer(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
) -> None:
    with patch.object(operator, "_execute", return_value=object()):
        output_data, output_attributes, meta = operator.run(input_data, attributes)

    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert len(meta.errors) == 1
    error = meta.errors[0]
    assert error.category is ErrorCategory.FAILED
    assert error.code is ErrorCode.EXECUTION_RESULT_INVALID
    assert error.stage is ErrorStage.NORMALIZE


@pytest.mark.parametrize(
    ("operator", "input_data", "attributes"),
    [
        (SemanticExtractOperator(), EXTRACT_INPUT, EXTRACT_ATTRIBUTES),
        (SemanticFilterOperator(), FILTER_INPUT, FILTER_ATTRIBUTES),
        (SemanticProjectOperator(), PROJECT_INPUT, PROJECT_ATTRIBUTES),
    ],
)
def test_timeout_calls_body_once_and_discards_late_result(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
) -> None:
    finished = Event()

    def slow_execute(
        call_input: DataBundle,
        call_attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        del call_attributes, properties
        time.sleep(0.04)
        finished.set()
        return FunctionResult(call_input, {"late": True})

    with patch.object(operator, "_execute", side_effect=slow_execute) as execute:
        output_data, output_attributes, meta = operator.run(
            input_data,
            attributes,
            {"execution.timeout_seconds": 0.005},
        )

    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert meta.errors[0].category is ErrorCategory.TIMEOUT
    assert meta.errors[0].code is ErrorCode.OPERATOR_TIMEOUT
    assert meta.errors[0].stage is ErrorStage.EXECUTE
    assert execute.call_count == 1
    assert finished.wait(timeout=0.2)


@pytest.mark.parametrize(
    ("operator", "attributes", "expected_call_attributes"),
    [
        (
            SemanticExtractOperator(),
            EXTRACT_ATTRIBUTES,
            {
                "entities": [{"name": "skill"}],
                "context": "",
                "demonstrations": "",
                "extract_with_single_prompt": True,
            },
        ),
        (
            SemanticFilterOperator(),
            FILTER_ATTRIBUTES,
            {
                "filter_conditions": {"score": "is high"},
                "context": "",
                "demonstrations": "",
                "return_idx": False,
            },
        ),
        (
            SemanticProjectOperator(),
            PROJECT_ATTRIBUTES,
            PROJECT_ATTRIBUTES,
        ),
    ],
)
def test_defaults_and_output_containers_are_fresh(
    operator: Operator,
    attributes: Attributes,
    expected_call_attributes: Attributes,
) -> None:
    original = dict(attributes)
    with patch.object(
        operator,
        "_execute",
        wraps=operator._execute,  # pyright: ignore[reportPrivateUsage]
    ) as execute:
        first = operator.run([[]], attributes)
        second = operator.run([[]], attributes)

    assert execute.call_count == 2
    first_call_attributes = execute.call_args_list[0].args[1]
    second_call_attributes = execute.call_args_list[1].args[1]
    assert first_call_attributes == expected_call_attributes
    assert first_call_attributes is not attributes
    assert first_call_attributes is not second_call_attributes
    assert attributes == original
    assert first[1] == second[1] == {}
    assert first[1] is not second[1]
    assert first[2].errors is not second[2].errors
    assert first[2].logs is not second[2].logs
    assert first[2].traces is not second[2].traces


@pytest.mark.parametrize(
    ("operator", "input_data", "invalid_attributes"),
    [
        (SemanticExtractOperator(), EXTRACT_INPUT, {"entities": []}),
        (SemanticFilterOperator(), FILTER_INPUT, {"filter_conditions": {}}),
        (SemanticProjectOperator(), PROJECT_INPUT, {"projection_instructions": ""}),
    ],
)
def test_selected_registry_version_owns_error_identity(
    operator: Operator,
    input_data: DataBundle,
    invalid_attributes: Attributes,
) -> None:
    registry = OperatorRegistry()
    registry.register(operator, "1.0.0")
    registry.register(operator, "2.0.0")

    for version in ("1.0.0", "2.0.0"):
        operator_id = f"{operator.name}@{version}"
        resolved = registry.resolve(operator_id)
        output_data, output_attributes, meta = resolved.run(input_data, invalid_attributes)

        assert output_data == [[]]
        assert output_attributes == {}
        assert meta.errors[0].operator_id == operator_id


def test_extract_individual_mode_skips_empty_fields_without_extra_calls() -> None:
    operator = SemanticExtractOperator()
    client = ScriptedClient([["Python"], "Ada"])
    input_data: DataBundle = [[{"name": "Ada", "bio": "Uses Python"}]]
    attributes: Attributes = {
        "entities": [
            {"name": "skill", "extract_on_fields": ["bio"]},
            {"name": "person", "extract_on_fields": ["name"]},
            {"name": "missing", "extract_on_fields": ["absent"]},
        ],
        "extract_with_single_prompt": False,
    }

    output_data, _, meta = operator.run(
        input_data,
        attributes,
        {"llm_client": client},
    )

    assert output_data == [[{"skill": ["Python"], "person": ["Ada"], "missing": []}]]
    assert len(client.calls) == 2
    assert meta.errors == []


@pytest.mark.parametrize(
    ("operator", "attributes", "expected"),
    [
        (
            SemanticExtractOperator(),
            {"entities": [{"name": "skill"}], "extract_with_single_prompt": "false"},
            True,
        ),
        (
            SemanticFilterOperator(),
            {"filter_conditions": {"score": "high"}, "return_idx": "yes"},
            True,
        ),
        (
            SemanticFilterOperator(),
            {"filter_conditions": {"score": "high"}, "context": b"ctx"},
            True,
        ),
        (
            SemanticProjectOperator(),
            {"projection_instructions": b"keep"},
            False,
        ),
    ],
)
def test_characterized_validation_quirks_remain_visible(
    operator: Operator,
    attributes: Attributes,
    expected: bool,
) -> None:
    result = operator._validate_input(  # pyright: ignore[reportPrivateUsage]
        [[{"score": 8}]],
        attributes,
    )

    assert type(result) is ValidationResult
    assert result.ok is expected
    assert operator.validate([[{"score": 8}]], attributes) is expected

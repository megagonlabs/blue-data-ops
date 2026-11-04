from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from typing import Any
from unittest.mock import patch

import pytest

from blue_data_ops import (
    ErrorCategory,
    ErrorCode,
    ErrorStage,
    ExecMeta,
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
    SemanticJoinOperator,
    SemanticTransformOperator,
    default_registry,
)
from blue_data_ops.operators import semantic_join_operator as join_module
from blue_data_ops.operators import semantic_transform_operator as transform_module
from tests.unit.operators._timeout_sync import blocked_worker

TRANSFORM_INPUT: DataBundle = [[{"city": "NY", "score": 1}]]
TRANSFORM_ATTRIBUTES: Attributes = {"output_desc": {"label": {"description": "Score label"}}}
JOIN_INPUT: DataBundle = [[{"id": 1, "name": "Ada"}], [{"id": "a", "name": "ADA"}]]
JOIN_ATTRIBUTES: Attributes = {
    "left_fields": ["name"],
    "right_fields": ["name"],
    "join_predicate": "names refer to the same person",
    "estimate_cost": False,
}


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


def _assert_execution_failure(meta: ExecMeta, operator_id: str, secret: str) -> None:
    assert meta.is_empty is False
    assert len(meta.errors) == 1
    error = meta.errors[0]
    assert error.category is ErrorCategory.FAILED
    assert error.code is ErrorCode.EXECUTION_FAILED
    assert error.stage is ErrorStage.EXECUTE
    assert error.operator_id == operator_id
    assert error.message == "operator execution failed"
    assert error.retryable is False
    assert secret not in str(error)


@pytest.mark.parametrize(
    ("operator", "input_data", "valid_attributes", "invalid_attributes"),
    [
        (
            SemanticTransformOperator(),
            TRANSFORM_INPUT,
            TRANSFORM_ATTRIBUTES,
            {"output_desc": {}},
        ),
        (
            SemanticJoinOperator(),
            JOIN_INPUT,
            JOIN_ATTRIBUTES,
            {"left_fields": ["name"]},
        ),
    ],
)
def test_native_hooks_keep_exact_boolean_adapters(
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


@pytest.mark.parametrize(  # pyright: ignore[reportUnknownArgumentType]
    ("attributes", "responses", "expected", "calls_per_path"),
    [  # pyright: ignore[reportUnknownArgumentType]
        (
            {"output_desc": {"person": {"description": "Copied city"}}},
            [
                {
                    "person": {
                        "source_fields": ["city"],
                        "transformation_type": "field_mapping_without_value_change",
                    }
                }
            ],
            [[{"person": "NY"}]],
            1,
        ),
        (
            {
                "output_desc": {"label": {"description": "Score label"}},
                "strategy": "per_record",
            },
            [
                {
                    "label": {
                        "source_fields": ["score"],
                        "transformation_type": "field_mapping_with_value_change",
                    }
                },
                {"label": "low"},
            ],
            [[{"label": "low"}]],
            2,
        ),
        (
            {
                "output_desc": {
                    "city_label": {"description": "City label"},
                    "region": {"description": "Region"},
                },
                "strategy": "distinct_required_values",
            },
            [
                {
                    "city_label": {
                        "source_fields": ["city"],
                        "transformation_type": "field_mapping_with_value_change",
                    },
                    "region": {
                        "source_fields": ["city"],
                        "transformation_type": "field_mapping_with_value_change",
                    },
                },
                {"city_label": "east"},
                {"region": "NE"},
            ],
            [[{"city_label": "east", "region": "NE"}]],
            3,
        ),
        (
            {
                "output_desc": {
                    "city_label": {"description": "City label"},
                    "combo": {"description": "City-score pair"},
                },
                "strategy": "distinct_required_values_with_merged_fields",
            },
            [
                {
                    "city_label": {
                        "source_fields": ["city"],
                        "transformation_type": "field_mapping_with_value_change",
                    },
                    "combo": {
                        "source_fields": ["city", "score"],
                        "transformation_type": "field_mapping_with_value_change",
                    },
                },
                {"city_label": "east", "combo": "NY-1"},
            ],
            [[{"city_label": "east", "combo": "NY-1"}]],
            2,
        ),
    ],
)
def test_transform_native_execution_matches_raw_for_every_strategy(
    attributes: Attributes,
    responses: list[Any],
    expected: DataBundle,
    calls_per_path: int,
) -> None:
    operator = SemanticTransformOperator()
    client = ScriptedClient([*deepcopy(responses), *deepcopy(responses)])
    properties: Properties = {"llm_client": client}

    native = operator._execute(  # pyright: ignore[reportPrivateUsage]
        TRANSFORM_INPUT,
        deepcopy(attributes),
        properties,
    )
    raw = operator.apply(TRANSFORM_INPUT, deepcopy(attributes), properties)

    assert type(native) is FunctionResult
    assert native.output_data == raw == expected
    assert native.output_attributes == {}
    assert len(client.calls) == calls_per_path * 2


@pytest.mark.parametrize(  # pyright: ignore[reportUnknownArgumentType]
    ("join_type", "expected"),
    [  # pyright: ignore[reportUnknownArgumentType]
        ("inner", [[]]),
        ("left", [[{"left": 1}]]),
        ("right", [[{"right": 2}]]),
        ("outer", [[{"left": 1}, {"right": 2}]]),
    ],
)
def test_join_native_execution_matches_raw_for_every_join_mode(
    join_type: str,
    expected: DataBundle,
) -> None:
    operator = SemanticJoinOperator()
    client = ScriptedClient([{"pair_1": False}, {"pair_1": False}])
    input_data: DataBundle = [[{"left": 1}], [{"right": 2}]]
    attributes: Attributes = {
        "left_fields": ["left"],
        "right_fields": ["right"],
        "join_type": join_type,
        "keep_keys": "both",
        "estimate_cost": False,
    }
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


def test_transform_run_calls_body_once_and_preserves_provider_call_order() -> None:
    operator = SemanticTransformOperator()
    client = ScriptedClient(
        [
            {
                "label": {
                    "source_fields": ["score"],
                    "transformation_type": "field_mapping_with_value_change",
                }
            },
            {"label": "low"},
        ]
    )
    with patch.object(
        operator,
        "_execute",
        wraps=operator._execute,  # pyright: ignore[reportPrivateUsage]
    ) as execute:
        output_data, output_attributes, meta = operator.run(
            TRANSFORM_INPUT,
            {**TRANSFORM_ATTRIBUTES, "strategy": "per_record"},
            {"llm_client": client},
        )

    assert execute.call_count == 1
    assert output_data == [[{"label": "low"}]]
    assert output_attributes == {}
    assert meta.errors == []
    assert len(client.calls) == 2
    assert client.calls[0][2] is not None
    assert "sample_data" in client.calls[0][2]
    assert client.calls[1][2] is not None
    assert client.calls[1][2]["input_data"] == {"city": "NY", "score": 1}


def test_join_run_calls_body_once_and_batches_left_major_right_minor() -> None:
    operator = SemanticJoinOperator()
    client = ScriptedClient(
        [
            {"pair_1": True, "pair_2": False, "pair_3": False},
            {"pair_1": True},
        ]
    )
    input_data: DataBundle = [
        [{"name": "Ada"}, {"name": "Bob"}],
        [{"name": "ADA"}, {"name": "BOB"}],
    ]
    with patch.object(
        operator,
        "_execute",
        wraps=operator._execute,  # pyright: ignore[reportPrivateUsage]
    ) as execute:
        output_data, _, meta = operator.run(
            input_data,
            {**JOIN_ATTRIBUTES, "batch_size": 3},
            {"llm_client": client},
        )

    assert execute.call_count == 1
    assert len(client.calls) == 2
    first_batch = client.calls[0][2]
    second_batch = client.calls[1][2]
    assert first_batch is not None and second_batch is not None
    assert 'index 0): {"name": "ADA"}' in first_batch["pairs"]
    assert first_batch["pairs"].index("Left Record (index 0)") < first_batch["pairs"].index(
        "Left Record (index 1)"
    )
    assert "Right Record (index 1)" in second_batch["pairs"]
    assert output_data == [[{"name": "Ada"}, {"name": "Bob"}]]
    assert meta.errors == []


def test_transform_empty_input_is_successful_without_provider() -> None:
    operator = SemanticTransformOperator()
    client = ScriptedClient([])

    output_data, output_attributes, meta = operator.run(
        [[]],
        TRANSFORM_ATTRIBUTES,
        {"llm_client": client},
    )

    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is True
    assert meta.errors == []
    assert client.calls == []


def test_join_no_match_is_successful_empty_output() -> None:
    operator = SemanticJoinOperator()
    client = ScriptedClient([{"pair_1": False}])

    output_data, output_attributes, meta = operator.run(
        JOIN_INPUT,
        JOIN_ATTRIBUTES,
        {"llm_client": client},
    )

    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is True
    assert meta.errors == []
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    ("operator", "input_data", "invalid_attributes"),
    [
        (SemanticTransformOperator(), TRANSFORM_INPUT, {"output_desc": {}}),
        (SemanticJoinOperator(), JOIN_INPUT, {"left_fields": ["name"]}),
    ],
)
def test_invalid_input_is_recoverable_and_suppresses_body_and_provider(
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
    ("operator", "input_data", "attributes", "failure_name"),
    [
        (
            SemanticTransformOperator(),
            TRANSFORM_INPUT,
            TRANSFORM_ATTRIBUTES,
            "provider",
        ),
        (SemanticJoinOperator(), JOIN_INPUT, JOIN_ATTRIBUTES, "provider"),
        (
            SemanticTransformOperator(),
            TRANSFORM_INPUT,
            TRANSFORM_ATTRIBUTES,
            "parser",
        ),
        (SemanticJoinOperator(), JOIN_INPUT, JOIN_ATTRIBUTES, "parser"),
    ],
)
def test_provider_and_parser_failures_stay_raw_and_run_contains_them(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
    failure_name: str,
) -> None:
    secret = f"private {failure_name} payload"
    exception_type = RuntimeError if failure_name == "provider" else ValueError
    client = ScriptedClient([exception_type(secret), exception_type(secret)])
    properties: Properties = {"llm_client": client}

    with pytest.raises(exception_type, match=secret):
        operator.apply(input_data, attributes, properties)
    output_data, output_attributes, meta = operator.run(input_data, attributes, properties)

    assert len(client.calls) == 2
    assert output_data == [[]]
    assert output_attributes == {}
    _assert_execution_failure(meta, f"{operator.name}@2.0.0", secret)


@pytest.mark.parametrize(
    ("operator", "module", "input_data", "attributes"),
    [
        (
            SemanticTransformOperator(),
            transform_module,
            TRANSFORM_INPUT,
            TRANSFORM_ATTRIBUTES,
        ),
        (SemanticJoinOperator(), join_module, JOIN_INPUT, JOIN_ATTRIBUTES),
    ],
)
def test_missing_llm_dependency_stays_raw_and_run_contains_it(
    operator: Operator,
    module: Any,
    input_data: DataBundle,
    attributes: Attributes,
) -> None:
    secret = "private optional dependency detail"
    with patch.object(module, "resolve_llm_client", side_effect=ImportError(secret)):
        with pytest.raises(ImportError, match=secret):
            operator.apply(input_data, attributes)
        output_data, output_attributes, meta = operator.run(input_data, attributes)

    assert output_data == [[]]
    assert output_attributes == {}
    _assert_execution_failure(meta, f"{operator.name}@2.0.0", secret)


@pytest.mark.parametrize(
    ("operator", "input_data", "attributes"),
    [
        (SemanticTransformOperator(), TRANSFORM_INPUT, TRANSFORM_ATTRIBUTES),
        (SemanticJoinOperator(), JOIN_INPUT, JOIN_ATTRIBUTES),
    ],
)
def test_malformed_native_result_reaches_shared_normalizer(
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
        (SemanticTransformOperator(), TRANSFORM_INPUT, TRANSFORM_ATTRIBUTES),
        (SemanticJoinOperator(), JOIN_INPUT, JOIN_ATTRIBUTES),
    ],
)
def test_timeout_calls_body_once_and_discards_late_result(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with blocked_worker(monkeypatch) as block:

        def slow_execute(
            call_input: DataBundle,
            call_attributes: Attributes,
            properties: Properties | None = None,
        ) -> FunctionResult:
            del call_attributes, properties
            block()
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
            assert len(meta.errors) == 1
            assert meta.errors[0].category is ErrorCategory.TIMEOUT
            assert meta.errors[0].code is ErrorCode.OPERATOR_TIMEOUT
            assert meta.errors[0].stage is ErrorStage.EXECUTE
            assert execute.call_count == 1
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.errors[0].code is ErrorCode.OPERATOR_TIMEOUT


def test_transform_raw_mutation_and_canonical_isolation() -> None:
    operator = SemanticTransformOperator()
    plan = {
        "label": {
            "source_fields": ["score"],
            "transformation_type": "field_mapping_without_value_change",
        }
    }
    client = ScriptedClient([deepcopy(plan), deepcopy(plan), deepcopy(plan)])
    raw_leaf: dict[str, Any] = {"description": "Score label"}
    raw_attributes: Attributes = {"output_desc": {"label": raw_leaf}}

    assert operator.apply(
        TRANSFORM_INPUT,
        raw_attributes,
        {"llm_client": client},
    ) == [[{"label": 1}]]
    assert raw_attributes["output_desc"]["label"] is raw_leaf
    assert raw_leaf["source_fields"] == ["score"]

    caller_leaf: dict[str, Any] = {"description": "Score label"}
    caller_attributes: Attributes = {"output_desc": {"label": caller_leaf}}
    with patch.object(
        operator,
        "_execute",
        wraps=operator._execute,  # pyright: ignore[reportPrivateUsage]
    ) as execute:
        first = operator.run(TRANSFORM_INPUT, caller_attributes, {"llm_client": client})
        second = operator.run(TRANSFORM_INPUT, caller_attributes, {"llm_client": client})

    assert caller_attributes == {"output_desc": {"label": {"description": "Score label"}}}
    assert caller_attributes["output_desc"]["label"] is caller_leaf
    first_call_attributes = execute.call_args_list[0].args[1]
    second_call_attributes = execute.call_args_list[1].args[1]
    assert first_call_attributes["input_meta"] == {}
    assert first_call_attributes["strategy"] == "auto"
    assert first_call_attributes is not caller_attributes
    assert first_call_attributes is not second_call_attributes
    assert first_call_attributes["output_desc"]["label"] is not caller_leaf
    assert first[1] == second[1] == {}
    assert first[1] is not second[1]
    assert first[2].errors is not second[2].errors
    assert first[2].logs is not second[2].logs
    assert first[2].traces is not second[2].traces


def test_join_defaults_caller_and_outputs_are_isolated() -> None:
    operator = SemanticJoinOperator()
    client = ScriptedClient([{"pair_1": False}, {"pair_1": False}])
    caller_attributes: Attributes = {"left_fields": ["name"], "right_fields": ["name"]}
    original = deepcopy(caller_attributes)
    with patch.object(
        operator,
        "_execute",
        wraps=operator._execute,  # pyright: ignore[reportPrivateUsage]
    ) as execute:
        first = operator.run(JOIN_INPUT, caller_attributes, {"llm_client": client})
        second = operator.run(JOIN_INPUT, caller_attributes, {"llm_client": client})

    assert caller_attributes == original
    first_call_attributes = execute.call_args_list[0].args[1]
    second_call_attributes = execute.call_args_list[1].args[1]
    assert first_call_attributes["join_type"] == "inner"
    assert first_call_attributes["batch_size"] == 10
    assert first_call_attributes["use_cache"] is True
    assert first_call_attributes is not caller_attributes
    assert first_call_attributes is not second_call_attributes
    assert first_call_attributes["left_fields"] is not caller_attributes["left_fields"]
    assert first[1] == second[1] == {}
    assert first[1] is not second[1]
    assert first[2].errors is not second[2].errors
    assert first[2].logs is not second[2].logs
    assert first[2].traces is not second[2].traces


@pytest.mark.parametrize(
    ("operator", "input_data", "invalid_attributes"),
    [
        (SemanticTransformOperator(), TRANSFORM_INPUT, {"output_desc": {}}),
        (SemanticJoinOperator(), JOIN_INPUT, {"left_fields": ["name"]}),
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


@pytest.mark.parametrize(  # pyright: ignore[reportUnknownArgumentType]
    ("strategy", "expected"),
    [  # pyright: ignore[reportUnknownArgumentType]
        ("auto", [[{}]]),
        ("per_record", [[{"optional": None}]]),
        ("bogus", [[{"optional": None}]]),
    ],
)
def test_transform_unclassified_fields_keep_auto_and_forced_behavior(
    strategy: str,
    expected: DataBundle,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = SemanticTransformOperator()
    client = ScriptedClient(
        [
            {
                "optional": {
                    "source_fields": [],
                    "transformation_type": "other",
                }
            }
        ]
    )

    output_data, _, meta = operator.run(
        [[{"x": 1}]],
        {"output_desc": {"optional": {"description": "Optional"}}, "strategy": strategy},
        {"llm_client": client},
    )
    assert output_data == [[]]
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert len(client.calls) == 1 and capsys.readouterr().out == ""


@pytest.mark.parametrize(  # pyright: ignore[reportUnknownArgumentType]
    ("response", "expected", "is_empty"),
    [  # pyright: ignore[reportUnknownArgumentType]
        (
            {"pair_1": "match"},
            [[{"id_left": 1, "name": "Ada", "id_right": "a"}]],
            False,
        ),
        ([1], [[{"id_left": 1, "name": "Ada", "id_right": "a"}]], False),
        (
            '```json\n{"pair_1": true}\n```',
            [[{"id_left": 1, "name": "Ada", "id_right": "a"}]],
            False,
        ),
        ("not-json", [[]], True),
    ],
)
def test_join_response_parsing_accepts_declared_legacy_forms(
    response: Any,
    expected: DataBundle,
    is_empty: bool,
) -> None:
    operator = SemanticJoinOperator()
    client = ScriptedClient([response])

    output_data, _, meta = operator.run(
        JOIN_INPUT,
        JOIN_ATTRIBUTES,
        {"llm_client": client},
    )

    if response == {"pair_1": "match"} or (
        isinstance(response, str) and response.startswith("```json")
    ):
        assert output_data == expected and meta.is_empty is is_empty and meta.errors == []
    else:
        assert output_data == [[]] and meta.is_empty is False
        assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert len(client.calls) == 1


def test_join_blank_predicate_uses_the_characterized_default() -> None:
    operator = SemanticJoinOperator()
    client = ScriptedClient([{"pair_1": False}])

    output_data, _, meta = operator.run(
        [[{"left": 1}], [{"right": 2}]],
        {"left_fields": [], "right_fields": [], "estimate_cost": False},
        {"llm_client": client},
    )

    call_data = client.calls[0][2]
    assert output_data == [[]]
    assert meta.errors == []
    assert call_data is not None
    assert call_data["join_predicate"] == (
        "Determine if the two records are semantically equivalent based on the provided fields."
    )


def test_transform_malformed_model_objects_are_rejected() -> None:
    operator = SemanticTransformOperator()
    client = ScriptedClient(["not-a-plan", "not-a-record"])

    output_data, output_attributes, meta = operator.run(
        TRANSFORM_INPUT,
        TRANSFORM_ATTRIBUTES,
        {"llm_client": client},
    )

    assert output_data == [[]] and output_attributes == {} and meta.is_empty is False
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert len(client.calls) == 1


def test_join_cache_reuses_identical_pair_across_batches() -> None:
    operator = SemanticJoinOperator()
    client = ScriptedClient([{"pair_1": True}])
    input_data: DataBundle = [[{"name": "same"}, {"name": "same"}], [{"name": "same"}]]

    output_data, _, meta = operator.run(
        input_data,
        {
            **JOIN_ATTRIBUTES,
            "batch_size": 1,
        },
        {"llm_client": client},
    )

    assert output_data == [[{"name": "same"}, {"name": "same"}]]
    assert meta.errors == []
    assert len(client.calls) == 1


def test_join_cost_limit_stays_raw_and_run_hides_details() -> None:
    operator = SemanticJoinOperator()
    input_data: DataBundle = [
        [{"name": "Ada"}, {"name": "Bob"}],
        [{"name": "ADA"}, {"name": "BOB"}],
    ]
    attributes: Attributes = {
        **JOIN_ATTRIBUTES,
        "estimate_cost": True,
        "batch_size": 1,
        "max_llm_calls": 3,
    }
    secret = "4 LLM calls exceeds limit of 3"

    with pytest.raises(ValueError, match=secret):
        operator.apply(input_data, attributes)
    output_data, output_attributes, meta = operator.run(input_data, attributes)

    assert output_data == [[]]
    assert output_attributes == {}
    _assert_execution_failure(meta, "semantic_join@2.0.0", secret)


def test_join_lax_numeric_string_reaches_body_and_is_contained() -> None:
    operator = SemanticJoinOperator()
    attributes: Attributes = {
        **JOIN_ATTRIBUTES,
        "estimate_cost": True,
        "batch_size": "1",
    }

    assert operator.validate(JOIN_INPUT, attributes) is True
    with pytest.raises(TypeError):
        operator.apply(JOIN_INPUT, attributes)
    output_data, output_attributes, meta = operator.run(JOIN_INPUT, attributes)

    assert output_data == [[]]
    assert output_attributes == {}
    _assert_execution_failure(meta, "semantic_join@2.0.0", "batch_size")


def test_join_embedding_filter_auto_matches_and_rejects_without_provider() -> None:
    np = pytest.importorskip("numpy")

    class EmbeddingModel:
        def __init__(self) -> None:
            self.responses = [
                np.array([[1.0, 0.0]]),
                np.array([[1.0, 0.0], [-1.0, 0.0]]),
            ]
            self.calls: list[tuple[tuple[str, ...], bool, int]] = []

        def encode(
            self,
            texts: list[str],
            *,
            show_progress_bar: bool,
            batch_size: int,
        ) -> Any:
            self.calls.append((tuple(texts), show_progress_bar, batch_size))
            return self.responses.pop(0)

    operator = SemanticJoinOperator()
    model = EmbeddingModel()
    client = ScriptedClient([])
    input_data: DataBundle = [
        [{"name": "Ada"}],
        [{"name": "ADA"}, {"name": "Cid"}],
    ]
    with patch.object(join_module, "_get_embedding_model", return_value=model):
        output_data, _, meta = operator.run(
            input_data,
            {
                **JOIN_ATTRIBUTES,
                "use_embedding_filter": True,
                "embedding_threshold": 0.0,
            },
            {"llm_client": client},
        )

    assert output_data == [[{"name": "Ada"}]]
    assert meta.errors == []
    assert client.calls == []
    assert model.calls == [
        (("name: Ada",), False, 32),
        (("name: ADA", "name: Cid"), False, 32),
    ]


def test_join_suffixes_and_keep_keys_remain_raw_compatible() -> None:
    operator = SemanticJoinOperator()
    client = ScriptedClient([{"pair_1": True}, {"pair_1": True}])
    input_data: DataBundle = [[{"id": 1, "name": "Ada"}], [{"id": "a", "name": "ADA"}]]
    attributes: Attributes = {
        **JOIN_ATTRIBUTES,
        "left_suffix": "__l",
        "right_suffix": "__r",
        "keep_keys": "both",
    }
    expected: DataBundle = [[{"id__l": 1, "name__l": "Ada", "id__r": "a", "name__r": "ADA"}]]

    native = operator._execute(  # pyright: ignore[reportPrivateUsage]
        input_data,
        attributes,
        {"llm_client": client},
    )
    raw = operator.apply(input_data, attributes, {"llm_client": client})

    assert native.output_data == raw == expected
    assert len(client.calls) == 2


def test_default_registry_contains_the_retained_v1_catalog() -> None:
    cards = default_registry().list_cards()

    assert len(cards) == 33
    assert len({card.operator_id for card in cards}) == 33
    assert all(card.version == "1.0.0" for card in cards)
    assert {card.operator_id for card in cards}.issuperset(
        {"semantic_transform@1.0.0", "semantic_join@1.0.0"}
    )

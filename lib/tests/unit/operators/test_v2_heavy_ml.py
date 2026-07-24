from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from blue_data_ops import ErrorCategory, ErrorCode, ErrorStage, FunctionResult, ValidationResult
from blue_data_ops.operators import (
    Attributes,
    ClassifyOperator,
    ClusterOperator,
    DataBundle,
    Operator,
    OperatorRegistry,
)

CLASSIFY_INPUT: DataBundle = [
    [
        {"id": "t1", "vector": [0.0, 0.0], "label": "low"},
        {"id": "t2", "vector": [0.2, 0.1], "label": "low"},
        {"id": "t3", "vector": [9.8, 10.0], "label": "high"},
        {"id": "t4", "vector": [10.2, 9.9], "label": "high"},
    ],
    [{"id": "q1", "vector": [0.1, 0.2]}, {"id": "q2", "vector": [10.0, 10.1]}],
]
CLASSIFY_ATTRIBUTES: Attributes = {
    "vector_key": "vector",
    "label_key": "label",
    "random_state": 42,
}
CLUSTER_INPUT: DataBundle = [
    [
        {"id": "a", "vector": [0.0, 0.1]},
        {"id": "b", "vector": [0.2, 0.0]},
        {"id": "c", "vector": [9.9, 10.1]},
        {"id": "d", "vector": [10.2, 9.8]},
    ]
]
CLUSTER_ATTRIBUTES: Attributes = {"vector_key": "vector", "n_cluster": 2}


@pytest.mark.parametrize(
    ("operator", "input_data", "attributes"),
    [
        (ClassifyOperator(), CLASSIFY_INPUT, CLASSIFY_ATTRIBUTES),
        (ClusterOperator(), CLUSTER_INPUT, CLUSTER_ATTRIBUTES),
    ],
)
def test_heavy_ml_owns_native_hooks_and_matches_public_apply(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
) -> None:
    assert "_execute" in type(operator).__dict__
    assert "_validate_input" in type(operator).__dict__

    result = operator._execute(input_data, attributes)  # pyright: ignore[reportPrivateUsage]

    assert type(result) is FunctionResult
    assert result.output_data == operator.apply(input_data, attributes)
    assert result.output_attributes == {}


@pytest.mark.parametrize(
    ("operator", "input_data", "valid_attributes", "invalid_attributes"),
    [
        (ClassifyOperator(), CLASSIFY_INPUT, CLASSIFY_ATTRIBUTES, {"vector_key": "vector"}),
        (ClusterOperator(), CLUSTER_INPUT, CLUSTER_ATTRIBUTES, {"vector_key": "vector"}),
    ],
)
def test_heavy_ml_structured_validation_preserves_exact_boolean_adapter(
    operator: Operator,
    input_data: DataBundle,
    valid_attributes: Attributes,
    invalid_attributes: Attributes,
) -> None:
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
    ("operator", "input_data", "attributes"),
    [
        (ClassifyOperator(), CLASSIFY_INPUT, CLASSIFY_ATTRIBUTES),
        (ClusterOperator(), CLUSTER_INPUT, CLUSTER_ATTRIBUTES),
    ],
)
def test_run_executes_native_body_once_and_returns_fresh_attributes(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
) -> None:
    with patch.object(
        operator,
        "_execute",
        wraps=operator._execute,  # pyright: ignore[reportPrivateUsage]
    ) as execute:
        output_data, output_attributes, meta = operator.run(input_data, attributes)
    second_attributes = operator.run(input_data, attributes)[1]

    assert execute.call_count == 1
    assert output_data == operator.apply(input_data, attributes)
    assert output_attributes == {}
    assert output_attributes is not second_attributes
    assert meta.errors == []


@pytest.mark.parametrize(
    ("operator", "input_data", "invalid_attributes"),
    [
        (ClassifyOperator(), CLASSIFY_INPUT, {"vector_key": "vector"}),
        (ClusterOperator(), CLUSTER_INPUT, {"vector_key": "vector"}),
    ],
)
def test_invalid_input_is_canonical_and_suppresses_body(
    operator: Operator,
    input_data: DataBundle,
    invalid_attributes: Attributes,
) -> None:
    with patch.object(
        operator,
        "_execute",
        side_effect=AssertionError("execution must be suppressed"),
    ) as execute:
        output_data, output_attributes, meta = operator.run(input_data, invalid_attributes)

    assert execute.call_count == 0
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


class _FailingClassifier:
    def __init__(self, **kwargs: Any) -> None:
        del kwargs

    def fit(self, vectors: object, labels: object) -> None:
        del vectors, labels
        raise RuntimeError("provider detail must stay private")


class _FailingClusterer:
    def __init__(self, **kwargs: Any) -> None:
        del kwargs

    def fit_predict(self, matrix: object) -> list[int]:
        del matrix
        raise RuntimeError("provider detail must stay private")


def _classify_import(name: str) -> object:
    if name == "sklearn.tree":
        return SimpleNamespace(DecisionTreeClassifier=_FailingClassifier)
    if name == "numpy":
        import numpy

        return numpy
    raise AssertionError(name)


def _cluster_import(name: str) -> object:
    if name == "sklearn.cluster":
        return SimpleNamespace(KMeans=_FailingClusterer)
    if name == "numpy":
        import numpy

        return numpy
    raise AssertionError(name)


@pytest.mark.parametrize(
    ("operator", "input_data", "attributes", "import_target", "importer"),
    [
        (
            ClassifyOperator(),
            CLASSIFY_INPUT,
            CLASSIFY_ATTRIBUTES,
            "blue_data_ops.operators.classify_operator.import_module",
            _classify_import,
        ),
        (
            ClusterOperator(),
            CLUSTER_INPUT,
            CLUSTER_ATTRIBUTES,
            "blue_data_ops.operators.cluster_operator.import_module",
            _cluster_import,
        ),
    ],
)
def test_model_failure_keeps_v1_fallback_but_run_reports_failure(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
    import_target: str,
    importer: Callable[[str], object],
) -> None:
    with patch(import_target, side_effect=importer):
        legacy_output = operator.apply(input_data, attributes)
        output_data, output_attributes, meta = operator.run(input_data, attributes)

    if isinstance(operator, ClassifyOperator):
        assert legacy_output is input_data
    else:
        assert legacy_output[0] is input_data[0]

    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert len(meta.errors) == 1
    error = meta.errors[0]
    assert error.category is ErrorCategory.FAILED
    assert error.code is ErrorCode.EXECUTION_FAILED
    assert error.stage is ErrorStage.EXECUTE
    assert error.operator_id == f"{operator.name}@2.0.0"
    assert "provider detail" not in error.message


@pytest.mark.parametrize(
    ("operator", "input_data", "attributes", "import_target"),
    [
        (
            ClassifyOperator(),
            CLASSIFY_INPUT,
            CLASSIFY_ATTRIBUTES,
            "blue_data_ops.operators.classify_operator.import_module",
        ),
        (
            ClusterOperator(),
            CLUSTER_INPUT,
            CLUSTER_ATTRIBUTES,
            "blue_data_ops.operators.cluster_operator.import_module",
        ),
    ],
)
def test_optional_dependency_failure_stays_raw_but_run_contains_it(
    operator: Operator,
    input_data: DataBundle,
    attributes: Attributes,
    import_target: str,
) -> None:
    with patch(import_target, side_effect=ImportError("optional dependency unavailable")):
        with pytest.raises(ImportError, match="optional dependency unavailable"):
            operator.apply(input_data, attributes)

        output_data, output_attributes, meta = operator.run(input_data, attributes)

    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert meta.errors[0].stage is ErrorStage.EXECUTE
    assert "optional dependency unavailable" not in meta.errors[0].message


def test_cluster_pre_model_exceptions_remain_raw_and_are_contained_by_run() -> None:
    operator = ClusterOperator()
    ragged = [[{"vector": [0.0]}, {"vector": [1.0, 2.0]}]]
    attributes: Attributes = {"vector_key": "vector", "n_cluster": 1}

    with pytest.raises(ValueError):
        operator.apply(ragged, attributes)

    output_data, output_attributes, meta = operator.run(ragged, attributes)

    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert meta.errors[0].stage is ErrorStage.EXECUTE


@pytest.mark.parametrize(
    ("operator", "input_data", "invalid_attributes"),
    [
        (ClassifyOperator(), CLASSIFY_INPUT, {"vector_key": "vector"}),
        (ClusterOperator(), CLUSTER_INPUT, {"vector_key": "vector"}),
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

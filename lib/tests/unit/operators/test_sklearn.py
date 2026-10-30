from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from blue_data_ops.operators import (
    Attributes,
    DataBundle,
    ErrorCode,
    ErrorStage,
    SklearnEstimator,
)

CLUSTER_INPUT: DataBundle = [
    [
        {"id": "a", "vector": [0.0, 0.1]},
        {"id": "b", "vector": [0.2, 0.0]},
        {"id": "c", "vector": [9.9, 10.1]},
        {"id": "d", "vector": [10.2, 9.8]},
    ]
]

CLASSIFY_TRAIN = [
    {"id": "t1", "vector": [0.0, 0.0], "label": "low"},
    {"id": "t2", "vector": [0.2, 0.1], "label": "low"},
    {"id": "t3", "vector": [9.8, 10.0], "label": "high"},
    {"id": "t4", "vector": [10.2, 9.9], "label": "high"},
]
CLASSIFY_TEST = [
    {"id": "q1", "vector": [0.1, 0.2]},
    {"id": "q2", "vector": [10.0, 10.1]},
    {"id": "q3"},  # Missing vector
]
CLASSIFY_INPUT: DataBundle = [CLASSIFY_TRAIN, CLASSIFY_TEST]


@pytest.fixture
def op() -> SklearnEstimator:
    return SklearnEstimator()


@pytest.mark.parametrize(
    "algorithm,attributes",
    [
        ("KMeans", {"vector_key": "vector", "n_clusters": 2, "random_state": 42}),
        ("DBSCAN", {"vector_key": "vector", "eps": 0.5, "min_samples": 2}),
    ],
    ids=["kmeans", "dbscan"],
)
def test_clustering_algorithms(
    op: SklearnEstimator, algorithm: str, attributes: Attributes
) -> None:
    output = op.apply(CLUSTER_INPUT, attributes, {"algorithm": algorithm})
    labels = [record["prediction"] for record in output[0]]

    assert labels[0] == labels[1]
    assert labels[2] == labels[3]
    assert labels[0] != labels[2]

    assert output[0][0] is not CLUSTER_INPUT[0][0]
    assert "prediction" not in CLUSTER_INPUT[0][0]


@pytest.mark.parametrize(
    "algorithm,extra_attrs",
    [
        ("DecisionTreeClassifier", {"random_state": 42}),
        ("KNeighborsClassifier", {"n_neighbors": 3}),
    ],
    ids=["decision_tree", "knn"],
)
def test_classification_algorithms(
    op: SklearnEstimator, algorithm: str, extra_attrs: Attributes
) -> None:
    attributes: Attributes = {
        "vector_key": "vector",
        "label_key": "label",
        "output_key": "pred_label",
        **extra_attrs,
    }
    output = op.apply(CLASSIFY_INPUT, attributes, {"algorithm": algorithm})

    predictions = [[record["pred_label"] for record in group] for group in output]
    assert predictions == [
        ["low", "low", "high", "high"],
        ["low", "high", None],
    ]


def test_regression_and_case_insensitive_lookup(op: SklearnEstimator) -> None:
    data: DataBundle = [
        [
            {"vector": [0.0], "target": 1.0},
            {"vector": [1.0], "target": 3.0},
            {"vector": [2.0], "target": 5.0},
        ],
        [{"vector": [3.0]}],
    ]
    output = op.apply(
        data,
        {"vector_key": "vector", "label_key": "target", "output_key": "score"},
        {"algorithm": "linearregression"},
    )

    assert [record["score"] for record in output[0]] == pytest.approx([1.0, 3.0, 5.0])
    assert output[1][0]["score"] == pytest.approx(7.0)


def test_transformer_returns_native_vectors(op: SklearnEstimator) -> None:
    original = deepcopy(CLUSTER_INPUT)
    output = op.apply(
        CLUSTER_INPUT,
        {"vector_key": "vector", "output_key": "component", "n_components": 1},
        {"algorithm": "PCA"},
    )

    assert all(
        isinstance(record["component"], list) and len(cast(list[object], record["component"])) == 1
        for record in output[0]
    )
    assert CLUSTER_INPUT == original


@pytest.mark.parametrize(
    "empty_input",
    [[], [[]], [[], CLASSIFY_TEST]],
    ids=["empty-bundle", "empty-first-group", "empty-first-with-later-data"],
)
def test_empty_guards_preserve_outer_identity(
    op: SklearnEstimator, empty_input: DataBundle
) -> None:
    attributes = {"vector_key": "vector", "label_key": "label"}
    assert op.apply(empty_input, attributes, {"algorithm": "DecisionTreeClassifier"}) is empty_input


def test_missing_vector_padding(op: SklearnEstimator) -> None:
    data: DataBundle = [
        [
            {"id": "1", "vector": [0.0, 0.0]},
            {"id": "2"},  # Missing vector
            {"id": "3", "vector": [10.0, 10.0]},
        ]
    ]
    output = op.apply(
        data,
        {"vector_key": "vector", "n_clusters": 2, "random_state": 42},
        {"algorithm": "KMeans"},
    )
    preds = [record["prediction"] for record in output[0]]
    assert preds in ([0, None, 1], [1, None, 0])


def test_unknown_algorithm_returns_original(op: SklearnEstimator) -> None:
    assert (
        op.apply(CLUSTER_INPUT, {"vector_key": "vector"}, {"algorithm": "UnknownEstimator"})
        is CLUSTER_INPUT
    )


def test_no_training_vectors_returns_original(op: SklearnEstimator) -> None:
    input_data = [[{"id": 1, "vector": "not-a-list", "label": "x"}]]
    attributes = {"vector_key": "vector", "label_key": "label"}
    assert op.apply(input_data, attributes, {"algorithm": "DecisionTreeClassifier"}) is input_data


def test_validation(op: SklearnEstimator) -> None:
    assert op.validate(CLUSTER_INPUT, {"vector_key": "vector"}, {"algorithm": "KMeans"}) is True

    assert op.validate(CLUSTER_INPUT, {}, {"algorithm": "KMeans"}) is False

    assert op.validate(CLUSTER_INPUT, {"vector_key": "vector"}, None) is False

    assert (
        op.validate(
            CLASSIFY_INPUT, {"vector_key": "vector"}, {"algorithm": "DecisionTreeClassifier"}
        )
        is False
    )

    assert (
        op.validate(
            CLASSIFY_INPUT,
            {"vector_key": "vector", "label_key": "label"},
            {"algorithm": "DecisionTreeClassifier"},
        )
        is True
    )


def test_unknown_algorithm_is_structured_invalid_input(op: SklearnEstimator) -> None:
    output, output_attributes, meta = op.run(
        CLUSTER_INPUT,
        {"vector_key": "vector"},
        {"algorithm": "UnknownEstimator"},
    )

    assert output == [[]]
    assert output_attributes == {}
    assert [(error.code, error.stage) for error in meta.errors] == [
        (ErrorCode.INVALID_INPUT, ErrorStage.VALIDATE)
    ]


def test_fit_predict_only_estimator_does_not_refit_later_groups(
    op: SklearnEstimator,
) -> None:
    data: DataBundle = [
        CLUSTER_INPUT[0],
        [{"id": "later", "vector": [0.1, 0.1]}],
    ]
    original = deepcopy(data)
    attributes = {"vector_key": "vector", "eps": 0.5, "min_samples": 2}
    properties = {"algorithm": "DBSCAN"}

    assert op.apply(data, attributes, properties) is data
    output, output_attributes, meta = op.run(data, attributes, properties)

    assert data == original
    assert output == [[]]
    assert output_attributes == {}
    assert [(error.code, error.stage) for error in meta.errors] == [
        (ErrorCode.EXECUTION_FAILED, ErrorStage.EXECUTE)
    ]


def test_non_clusterer_fit_predict_only_estimator_handles_training_group(
    op: SklearnEstimator,
) -> None:
    attributes = {"vector_key": "vector", "n_neighbors": 2}
    properties = {"algorithm": "LocalOutlierFactor"}

    output = op.apply(CLUSTER_INPUT, attributes, properties)

    assert all(record["prediction"] is not None for record in output[0])

    grouped_input: DataBundle = [
        CLUSTER_INPUT[0],
        [{"id": "later", "vector": [0.1, 0.1]}],
    ]
    assert op.apply(grouped_input, attributes, properties) is grouped_input
    _, _, meta = op.run(grouped_input, attributes, properties)
    assert [(error.code, error.stage) for error in meta.errors] == [
        (ErrorCode.EXECUTION_FAILED, ErrorStage.EXECUTE)
    ]


def test_invocation_contract(op: SklearnEstimator) -> None:
    attributes = {"vector_key": "vector", "n_clusters": 2, "random_state": 42}
    properties = {"algorithm": "KMeans"}
    assert op.invoke(CLUSTER_INPUT, attributes, properties) == op.apply(
        CLUSTER_INPUT, attributes, properties
    )
    assert op.invoke(CLUSTER_INPUT, {}, properties) is None


def test_interface_contract(op: SklearnEstimator) -> None:
    assert op.name == "sklearn_estimator"
    assert "vector_key" in op.attributes
    assert op.attributes["vector_key"].required is True
    assert "output_key" in op.attributes
    assert op.attributes["output_key"].default == "prediction"

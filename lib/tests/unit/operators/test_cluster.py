from __future__ import annotations

import pytest

from blue_data_ops.operators import Attributes, ClusterOperator, DataBundle, Properties

INPUT = [
    [
        {"id": "a", "vector": [0.0, 0.1]},
        {"id": "b", "vector": [0.2, 0.0]},
        {"id": "c", "vector": [9.9, 10.1]},
        {"id": "d", "vector": [10.2, 9.8]},
    ]
]


@pytest.fixture
def op() -> ClusterOperator:
    return ClusterOperator()


@pytest.mark.parametrize(
    "attributes,properties",
    [
        ({"vector_key": "vector", "n_cluster": 2}, None),
        (
            {
                "vector_key": "vector",
                "n_cluster": 2,
                "init": "specified",
                "init_centroids": [[0.0, 0.0], [10.0, 10.0]],
                "output_key": "group",
            },
            None,
        ),
        (
            {"vector_key": "vector", "eps": 0.5, "min_samples": 2},
            {"algorithm": "dbscan"},
        ),
        (
            {"vector_key": "vector", "n_cluster": 2, "covariance_type": "diag"},
            {"algorithm": "gaussian"},
        ),
    ],
    ids=["kmeans", "specified", "dbscan", "gaussian"],
)
def test_algorithm_outputs(
    op: ClusterOperator,
    attributes: Attributes,
    properties: Properties | None,
) -> None:
    output = op.apply(INPUT, attributes, properties)
    output_key = str(attributes.get("output_key", "cluster_index"))
    assert [record[output_key] for record in output[0]] == [0, 0, 1, 1]
    assert output[0][0] is not INPUT[0][0]


@pytest.mark.parametrize("input_data", [[], [[]]], ids=["empty-bundle", "empty-first-group"])
def test_empty_guards(op: ClusterOperator, input_data: DataBundle) -> None:
    assert op.apply(input_data, {"vector_key": "vector", "n_cluster": 2}) == [[]]


def test_too_few_vectors_returns_original_first_group(op: ClusterOperator) -> None:
    data = [{"vector": [0.0]}, {"id": "missing"}]
    output = op.apply([data], {"vector_key": "vector", "n_cluster": 2})
    assert output[0] is data


def test_missing_vector_gets_none_when_clustering_runs(op: ClusterOperator) -> None:
    data = [{"vector": [0.0]}, {"id": "missing"}, {"vector": [10.0]}]
    output = op.apply(
        [data],
        {
            "vector_key": "vector",
            "n_cluster": 2,
            "init": "specified",
            "init_centroids": [[0.0], [10.0]],
        },
    )
    assert [record["cluster_index"] for record in output[0]] == [0, None, 1]


def test_unknown_algorithm_returns_original_first_group(op: ClusterOperator) -> None:
    assert op.apply(INPUT, {"vector_key": "vector"}, {"algorithm": "other"})[0] is INPUT[0]


def test_missing_count_raises_before_model_try(op: ClusterOperator) -> None:
    with pytest.raises(TypeError):
        op.apply(INPUT, {"vector_key": "vector"})


def test_ragged_vectors_raise_before_model_try(op: ClusterOperator) -> None:
    with pytest.raises(ValueError):
        op.apply(
            [[{"vector": [0.0]}, {"vector": [1.0, 2.0]}]],
            {"vector_key": "vector", "n_cluster": 1},
        )


VALIDATOR_CASES: list[tuple[str, Attributes, Properties | None, bool]] = [
    ("KV1", {"vector_key": "vector", "n_cluster": 2}, None, True),
    ("KV2", {"n_cluster": 2}, None, False),
    ("KV3", {"vector_key": "vector"}, None, False),
    ("KV4", {"vector_key": "vector"}, {"algorithm": "dbscan"}, True),
    ("KV5", {"vector_key": "vector"}, {"algorithm": "gaussian"}, False),
    (
        "KV6",
        {
            "vector_key": "vector",
            "n_cluster": 2,
            "init": "specified",
            "init_centroids": [[0.0], [10.0]],
        },
        None,
        True,
    ),
    ("KV7", {"vector_key": "vector", "n_cluster": 2, "init": "specified"}, None, False),
    (
        "KV8",
        {
            "vector_key": "vector",
            "n_cluster": 2,
            "init": "specified",
            "init_centroids": [[0.0]],
        },
        None,
        False,
    ),
    ("KV9", {"vector_key": "vector", "n_cluster": "2"}, None, True),
    ("KV10", {"vector_key": b"vector", "n_cluster": 2}, None, True),
    (
        "KV11",
        {
            "vector_key": "vector",
            "n_cluster": 2,
            "init": "specified",
            "init_centroids": ([0.0], [10.0]),
        },
        None,
        True,
    ),
    ("KV12", {"vector_key": "vector", "n_cluster": 2, "max_iter": "x"}, None, False),
]


@pytest.mark.parametrize(
    "case_id,attributes,properties,expected",
    VALIDATOR_CASES,
    ids=[case[0] for case in VALIDATOR_CASES],
)
def test_validate(
    op: ClusterOperator,
    case_id: str,
    attributes: Attributes,
    properties: Properties | None,
    expected: bool,
) -> None:
    assert op.validate(INPUT, attributes, properties) is expected


def test_invocation_contract(op: ClusterOperator) -> None:
    attributes: Attributes = {"vector_key": "vector", "n_cluster": 2}
    assert op.invoke(INPUT, attributes) == op.apply(INPUT, attributes)
    assert op.invoke(INPUT, {"vector_key": "vector"}) is None


def test_interface_contract(op: ClusterOperator) -> None:
    assert (op.name, op.description) == (
        "cluster",
        "Given input data with numeric vectors, compute clusters and predict cluster "
        "index for each sample using KMeans, DBSCAN, or GaussianMixture.",
    )
    expected: dict[str, tuple[str, str, bool, object]] = {
        "vector_key": ("str", "The key to the numeric vector values", True, None),
        "n_cluster": ("int", "The number of clusters to form", False, None),
        "output_key": ("str", "The key name for the predicted labels", False, "cluster_index"),
        "eps": ("float", "Max distance between two samples for DBSCAN", False, 0.5),
        "min_samples": ("int", "Number of samples in a neighborhood for DBSCAN", False, 5),
        "covariance_type": ("str", "Covariance type for Gaussian Mixture", False, "full"),
        "init": ("str", "Method for initialization", False, None),
        "init_centroids": ("list", "Required when init='specified'", False, None),
        "max_iter": ("int", "Maximum number of iterations", False, 300),
    }
    assert set(op.attributes) == set(expected)
    for name, interface in expected.items():
        spec = op.attributes[name]
        assert (spec.type, spec.description, op.is_required(name), spec.default) == interface


def test_explain_delegates_to_default(op: ClusterOperator) -> None:
    attributes: Attributes = {"vector_key": "vector", "n_cluster": 2}
    output = op.apply(INPUT, attributes)
    explanation = op.explain(output, INPUT, attributes)
    assert explanation["output"] == output
    assert explanation["num_input_records"] == 4
    assert explanation["num_output_records"] == 1

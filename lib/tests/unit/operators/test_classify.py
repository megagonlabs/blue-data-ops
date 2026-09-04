from __future__ import annotations

import pytest

from blue_data_ops.operators import Attributes, ClassifyOperator, DataBundle, Properties

TRAINING = [
    {"id": "t1", "vector": [0.0, 0.0], "label": "low"},
    {"id": "t2", "vector": [0.2, 0.1], "label": "low"},
    {"id": "t3", "vector": [9.8, 10.0], "label": "high"},
    {"id": "t4", "vector": [10.2, 9.9], "label": "high"},
]
TEST = [
    {"id": "q1", "vector": [0.1, 0.2]},
    {"id": "q2", "vector": [10.0, 10.1]},
    {"id": "q3"},
]
INPUT = [TRAINING, TEST]
ATTRIBUTES: Attributes = {
    "vector_key": "vector",
    "label_key": "label",
    "random_state": 42,
}


@pytest.fixture
def op() -> ClassifyOperator:
    return ClassifyOperator()


@pytest.mark.parametrize(
    "attributes,properties,expected_preds",
    [
        (
            {"vector_key": "vector", "label_key": "label", "random_state": 42},
            None,
            [["low", "low", "high", "high"], ["low", "high", None]],
        ),
        (
            {
                "vector_key": "vector",
                "label_key": "label",
                "criterion": "entropy",
                "max_depth": 3,
                "random_state": 42,
            },
            {"algorithm": "decision_tree"},
            [["low", "low", "high", "high"], ["low", "high", None]],
        ),
        (
            {
                "vector_key": "vector",
                "label_key": "label",
                "n_neighbors": 3,
                "weights": "distance",
                "output_key": "knn_prediction",
            },
            {"algorithm": "knn"},
            [["low", "low", "high", "high"], ["low", "high", None]],
        ),
    ],
    ids=["decision_tree_default", "decision_tree_entropy", "knn"],
)
def test_algorithm_outputs(
    op: ClassifyOperator,
    attributes: Attributes,
    properties: Properties | None,
    expected_preds: list[list[str | None]],
) -> None:
    output = op.apply(INPUT, attributes, properties)
    output_key = str(attributes.get("output_key", "predicted_label"))
    assert [[record[output_key] for record in data] for data in output] == expected_preds
    assert output[0][0] is not INPUT[0][0]


def test_multinomial_nb_predictions(op: ClassifyOperator) -> None:
    data = [
        [
            {"id": "t1", "vector": [10.0, 1.0], "label": "engineering"},
            {"id": "t2", "vector": [8.0, 0.5], "label": "engineering"},
            {"id": "t3", "vector": [0.5, 9.0], "label": "sales"},
            {"id": "t4", "vector": [1.0, 11.0], "label": "sales"},
        ],
        [
            {"id": "q1", "vector": [9.0, 1.0]},
            {"id": "q2", "vector": [0.8, 10.0]},
            {"id": "q3"},
        ],
    ]
    attributes: Attributes = {
        "vector_key": "vector",
        "label_key": "label",
        "alpha": 0.5,
        "output_key": "mnb_label",
    }
    output = op.apply(data, attributes, {"algorithm": "multinomial_nb"})
    assert [[record["mnb_label"] for record in group] for group in output] == [
        ["engineering", "engineering", "sales", "sales"],
        ["engineering", "sales", None],
    ]


def test_output_key_and_string_hyperparameters(op: ClassifyOperator) -> None:
    attributes = {
        **ATTRIBUTES,
        "output_key": "prediction",
        "max_depth": "1",
        "min_samples_split": "0.5",
        "min_samples_leaf": "1",
    }
    output = op.apply(INPUT, attributes)
    assert [[record["prediction"] for record in data] for data in output] == [
        ["low", "low", "high", "high"],
        ["low", "high", None],
    ]
    assert all("predicted_label" not in record for data in output for record in data)


@pytest.mark.parametrize(
    "input_data",
    [[], [[]], [[], TEST]],
    ids=["empty-bundle", "empty-first-group", "empty-first-with-later-data"],
)
def test_empty_guards_preserve_outer_identity(op: ClassifyOperator, input_data: DataBundle) -> None:
    assert op.apply(input_data, ATTRIBUTES) is input_data


def test_no_training_vectors_returns_original(op: ClassifyOperator) -> None:
    input_data = [[{"id": 1, "vector": "not-a-list", "label": "x"}]]
    assert op.apply(input_data, ATTRIBUTES) is input_data


def test_unknown_algorithm_returns_original(op: ClassifyOperator) -> None:
    assert op.apply(INPUT, ATTRIBUTES, {"algorithm": "svm"}) is INPUT


def test_ragged_training_vectors_return_original(op: ClassifyOperator) -> None:
    input_data = [
        [
            {"vector": [0.0], "label": "a"},
            {"vector": [1.0, 2.0], "label": "b"},
        ]
    ]
    assert op.apply(input_data, ATTRIBUTES) is input_data


VALIDATOR_CASES: list[tuple[str, Attributes, bool]] = [
    ("CV1", {"vector_key": "vector", "label_key": "label"}, True),
    ("CV2", {"label_key": "label"}, False),
    ("CV3", {"vector_key": "vector"}, False),
    ("CV4", {"vector_key": "", "label_key": "label"}, False),
    ("CV5", {"vector_key": b"vector", "label_key": b"label"}, True),
    ("CV6", {"vector_key": "vector", "label_key": "label", "random_state": "42"}, True),
    ("CV7", {"vector_key": "vector", "label_key": "label", "random_state": "x"}, False),
    ("CV8", {"vector_key": "vector", "label_key": "label", "output_key": True}, False),
    ("CV9", {"vector_key": "vector", "label_key": "label", "max_depth": None}, False),
    (
        "CV10",
        {"vector_key": "vector", "label_key": "label", "min_samples_split": 0.5},
        True,
    ),
    (
        "CV11",
        {"vector_key": "vector", "label_key": "label", "n_neighbors": 3, "weights": "distance"},
        True,
    ),
    (
        "CV12",
        {"vector_key": "vector", "label_key": "label", "n_neighbors": "invalid"},
        False,
    ),
    (
        "CV13",
        {"vector_key": "vector", "label_key": "label", "alpha": 0.5, "fit_prior": True},
        True,
    ),
    (
        "CV14",
        {"vector_key": "vector", "label_key": "label", "alpha": "invalid"},
        False,
    ),
]


@pytest.mark.parametrize(
    "case_id,attributes,expected",
    VALIDATOR_CASES,
    ids=[case[0] for case in VALIDATOR_CASES],
)
def test_validate(
    op: ClassifyOperator, case_id: str, attributes: Attributes, expected: bool
) -> None:
    assert op.validate(INPUT, attributes) is expected


def test_invocation_contract(op: ClassifyOperator) -> None:
    assert op.invoke(INPUT, ATTRIBUTES) == op.apply(INPUT, ATTRIBUTES)
    assert op.invoke(INPUT, {"vector_key": "vector"}) is None
    ragged = [[{"vector": [0.0], "label": "a"}, {"vector": [1.0, 2.0], "label": "b"}]]
    assert op.invoke(ragged, ATTRIBUTES) is ragged


def test_interface_contract(op: ClassifyOperator) -> None:
    assert (op.name, op.description) == (
        "classify",
        "Given input data with numeric vectors and training labels, train a classifier "
        "and predict class labels for each sample using DecisionTreeClassifier, "
        "KNeighborsClassifier, or MultinomialNB.",
    )
    expected: dict[str, tuple[str, str, bool, object]] = {
        "vector_key": ("str", "The key to the numeric vector values (features)", True, None),
        "label_key": ("str", "The key to the target class labels", True, None),
        "output_key": ("str", "The key name for the predicted labels", False, "predicted_label"),
        "criterion": ("str", "Function to measure split quality for decision_tree", False, "gini"),
        "splitter": ("str", "Strategy to choose the split for decision_tree", False, "best"),
        "max_depth": ("int", "The maximum depth of the tree for decision_tree", False, None),
        "min_samples_split": (
            "float",
            "Minimum samples to split an internal node for decision_tree",
            False,
            2,
        ),
        "min_samples_leaf": (
            "float",
            "Minimum samples to be at a leaf node for decision_tree",
            False,
            1,
        ),
        "random_state": ("int", "Controls the randomness for decision_tree", False, None),
        "n_neighbors": (
            "int",
            "Number of neighbors to use for kneighbors queries for knn",
            False,
            5,
        ),
        "weights": ("str", "Weight function used in prediction for knn", False, "uniform"),
        "alpha": ("float", "Additive smoothing parameter for multinomial_nb", False, 1.0),
        "fit_prior": (
            "bool",
            "Whether to learn class prior probabilities for multinomial_nb",
            False,
            True,
        ),
    }
    assert set(op.attributes) == set(expected)
    for name, interface in expected.items():
        spec = op.attributes[name]
        assert (spec.type, spec.description, op.is_required(name), spec.default) == interface


def test_explain_delegates_to_default(op: ClassifyOperator) -> None:
    output = op.apply(INPUT, ATTRIBUTES)
    explanation = op.explain(output, INPUT, ATTRIBUTES)
    assert explanation["output"] == output
    assert explanation["num_input_records"] == 7
    assert explanation["num_output_records"] == 2
    assert explanation["transformation_ratio"] == pytest.approx(2 / 7)

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from blue_data_ops import ErrorCode, ErrorStage
from blue_data_ops.operators.registry import versioned_registry

CLASSIFY_ATTRIBUTES = {"vector_key": "vector", "label_key": "label"}
CLASSIFY_INPUT = [
    [
        {"id": "train-a", "vector": [0.0], "label": "left"},
        {"id": "train-b", "vector": [1.0], "label": "right"},
    ],
    [{"id": "predict", "vector": [0.25]}],
]


def _assert_invalid(result: tuple[Any, Any, Any]) -> None:
    output_data, output_attributes, meta = result
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert len(meta.errors) == 1
    assert meta.errors[0].code is ErrorCode.INVALID_INPUT
    assert meta.errors[0].stage is ErrorStage.VALIDATE


@pytest.mark.parametrize(
    ("input_data", "properties"),
    [
        (CLASSIFY_INPUT, {"algorithm": "unsupported"}),
        ([[], [{"id": "predict", "vector": [0.25]}]], None),
        ([[{"id": "bad", "vector": "not-a-vector", "label": "left"}]], None),
    ],
    ids=["unsupported-algorithm", "empty-training", "no-usable-training-row"],
)
def test_classify_rejects_calls_that_cannot_train(
    input_data: list[list[dict[str, Any]]], properties: dict[str, Any] | None
) -> None:
    operator = versioned_registry().resolve("classify@3.0.0")
    _assert_invalid(operator.run(deepcopy(input_data), CLASSIFY_ATTRIBUTES, properties))


def test_classify_prior_version_passes_through_an_unsupported_algorithm() -> None:
    old_operator = versioned_registry().resolve("classify@2.0.0")
    new_operator = versioned_registry().resolve("classify@3.0.0")

    old_data, _, old_meta = old_operator.run(
        deepcopy(CLASSIFY_INPUT),
        CLASSIFY_ATTRIBUTES,
        {"algorithm": "unsupported"},
    )
    assert old_data == CLASSIFY_INPUT
    assert old_meta.errors == []
    _assert_invalid(
        new_operator.run(
            deepcopy(CLASSIFY_INPUT),
            CLASSIFY_ATTRIBUTES,
            {"algorithm": "unsupported"},
        )
    )


@pytest.mark.parametrize(
    ("input_data", "attributes", "properties"),
    [
        (
            [[{"id": "sample", "vector": [0.0]}]],
            {"vector_key": "vector", "n_cluster": 1},
            {"algorithm": "unsupported"},
        ),
        (
            [[{"id": "sample", "vector": "not-a-vector"}]],
            {"vector_key": "vector", "n_cluster": 1},
            {"algorithm": "dbscan"},
        ),
        (
            [[{"id": "a", "vector": [0.0]}, {"id": "b", "vector": [1.0]}]],
            {"vector_key": "vector", "n_cluster": 3},
            {"algorithm": "kmeans"},
        ),
    ],
    ids=["unsupported-algorithm", "no-usable-vector", "insufficient-fit-count"],
)
def test_cluster_rejects_calls_that_cannot_fit(
    input_data: list[list[dict[str, Any]]],
    attributes: dict[str, Any],
    properties: dict[str, Any],
) -> None:
    operator = versioned_registry().resolve("cluster@3.0.0")
    _assert_invalid(operator.run(input_data, attributes, properties))


def test_cluster_accepts_the_existing_string_count_boundary() -> None:
    operator = versioned_registry().resolve("cluster@3.0.0")
    input_data = [
        [
            {"id": "near-a", "vector": [0.0, 0.0]},
            {"id": "near-b", "vector": [0.0, 0.1]},
            {"id": "far-a", "vector": [9.0, 9.0]},
            {"id": "far-b", "vector": [9.0, 9.1]},
        ]
    ]
    output_data, output_attributes, meta = operator.run(
        input_data,
        {"vector_key": "vector", "n_cluster": "2"},
        {"algorithm": "kmeans"},
    )

    labels = [record["cluster_index"] for record in output_data[0]]
    assert labels[0] == labels[1]
    assert labels[2] == labels[3]
    assert labels[0] != labels[2]
    assert output_attributes == {}
    assert meta.errors == []
    assert meta.is_empty is False

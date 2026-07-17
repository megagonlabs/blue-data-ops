from __future__ import annotations

from typing import cast

import pytest

from blue_data_ops.operators import Attributes, DataBundle, VectorSimilarityOperator
from tests.stubs.sentence_transformers import EncodeCall, SentenceTransformer

EXISTING = [
    [
        {"id": "l1", "embedding": [1.0, 0.0]},
        {"id": "l2", "embedding": [0.0, 1.0]},
    ],
    [
        {"id": "r1", "embedding": [1.0, 0.0]},
        {"id": "r2", "embedding": [1.0, 1.0]},
    ],
]
FIELDS = ["embedding", "embedding"]


@pytest.fixture(autouse=True)
def reset_model_stub() -> None:
    SentenceTransformer.reset()


@pytest.fixture
def op() -> VectorSimilarityOperator:
    return VectorSimilarityOperator()


def test_pairwise_cosine_existing_embeddings(op: VectorSimilarityOperator) -> None:
    output = op.apply(
        EXISTING,
        {
            "fields": FIELDS,
            "comparison_mode": "pairwise",
            "metric": "cosine",
            "add_meta_data": True,
        },
    )
    assert [record["id"] for record in output[0]] == ["l1_r1", "l2_r2"]
    assert [record["similarity.score"] for record in output[0]] == pytest.approx(
        [1.0, 0.7071067811865475]
    )
    assert all(record["similarity.metric"] == "cosine" for record in output[0])
    assert all(record["similarity.comparison_mode"] == "pairwise" for record in output[0])
    assert all("similarity.model" not in record for record in output[0])
    assert SentenceTransformer.model_names == []


def test_cartesian_l2_threshold_and_order(op: VectorSimilarityOperator) -> None:
    output = op.apply(
        EXISTING,
        {"fields": FIELDS, "metric": "l2", "threshold": -0.75},
    )[0]
    assert [record["id"] for record in output] == ["l1_r1", "l1_r2", "l2_r1", "l2_r2"]
    assert [record["similarity.score"] for record in output] == pytest.approx(
        [-0.0, -1.0, -1.4142135623730951, -1.0]
    )
    assert [record["similarity.passed"] for record in output] == [True, False, False, False]
    assert all(record["similarity.threshold"] == -0.75 for record in output)


def test_normalized_dot_existing_embeddings(op: VectorSimilarityOperator) -> None:
    output = op.apply(
        EXISTING,
        {"fields": FIELDS, "metric": "dot", "normalize": True},
    )[0]
    assert [record["similarity.score"] for record in output] == pytest.approx(
        [1.0, 0.7071067811865475, 0.0, 0.7071067811865475]
    )


def test_embed_missing_model_calls_and_dot_math(op: VectorSimilarityOperator) -> None:
    output = op.apply(
        [[{"id": "l", "text": "alpha"}], [{"id": "r", "text": "beta"}]],
        {
            "fields": ["text", "text"],
            "metric": "dot",
            "on_missing_embedding": "embed_missing",
            "add_meta_data": True,
        },
    )
    assert output == [
        [
            {
                "id": "l_r",
                "left_id": "l",
                "right_id": "r",
                "similarity.score": pytest.approx(1.7788389081122646),
                "similarity.metric": "dot",
                "similarity.comparison_mode": "cartesian",
                "similarity.model": "all-MiniLM-L6-v2",
            }
        ]
    ]
    assert SentenceTransformer.model_names == ["all-MiniLM-L6-v2"]
    assert SentenceTransformer.encode_calls == [
        EncodeCall("all-MiniLM-L6-v2", ("alpha",), 32, False),
        EncodeCall("all-MiniLM-L6-v2", ("beta",), 32, False),
    ]


def test_mixed_existing_and_missing_embeddings(op: VectorSimilarityOperator) -> None:
    output = op.apply(
        [
            [
                {"id": "l1", "embedding": [1.0, 0.0, 0.0, 0.0]},
                {"id": "l2", "text": "alpha"},
            ],
            [{"id": "r", "text": "beta"}],
        ],
        {
            "fields": ["text", "text"],
            "on_missing_embedding": "embed_missing",
            "add_meta_data": True,
        },
    )[0]
    assert [record["similarity.score"] for record in output] == pytest.approx(
        [0.6794022119341215, 0.8177230029735008]
    )
    assert all(record["similarity.model"] == "all-MiniLM-L6-v2" for record in output)
    assert [call.sentences for call in SentenceTransformer.encode_calls] == [
        ("alpha",),
        ("beta",),
    ]


def test_zero_vector_cosine_is_zero(op: VectorSimilarityOperator) -> None:
    output = op.apply(
        [[{"embedding": [0.0, 0.0]}], [{"embedding": [1.0, 0.0]}]],
        {"fields": FIELDS},
    )
    assert output[0][0] == {
        "id": "left_0_right_0",
        "left_id": "left_0",
        "right_id": "right_0",
        "similarity.score": 0.0,
    }


@pytest.mark.parametrize(
    "input_data,attributes,message",
    [
        (
            cast(DataBundle, [[]]),
            {},
            "vector_similarity requires exactly two input lists",
        ),
        (
            [[{"embedding": [1.0]}], []],
            {"comparison_mode": "pairwise", "fields": FIELDS},
            "pairwise comparison requires both input lists",
        ),
        (EXISTING, {"fields": ["embedding"]}, "fields must be a list of exactly two"),
        (
            [[{"text": "alpha"}], [{"text": "beta"}]],
            {"fields": ["text", "text"]},
            "Missing embedding in left records",
        ),
        (
            [[{"embedding": [1.0]}], [{"embedding": [1.0, 0.0]}]],
            {"fields": FIELDS},
            "Embedding dimension mismatch between lists: 1 vs 2",
        ),
        (
            cast(DataBundle, [[], []]),
            {"fields": FIELDS},
            "Inconsistent embedding dimensions within left list",
        ),
    ],
    ids=["group-count", "pairwise-length", "fields", "missing", "dimensions", "empty-groups"],
)
def test_error_surfaces(
    op: VectorSimilarityOperator,
    input_data: DataBundle,
    attributes: Attributes,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        op.apply(input_data, attributes)


def test_use_empty_missing_text_fields(op: VectorSimilarityOperator) -> None:
    output = op.apply(
        [[{"id": "l"}], [{"id": "r"}]],
        {
            "fields": ["text", "text"],
            "on_missing_embedding": "embed_missing",
            "on_missing_fields": "use_empty",
        },
    )
    assert output[0][0]["similarity.score"] == pytest.approx(0.9999999999999999)
    assert [call.sentences for call in SentenceTransformer.encode_calls] == [("",), ("",)]


def test_omitted_fields_are_supported_for_existing_embeddings(
    op: VectorSimilarityOperator,
) -> None:
    # Existing embeddings do not require field names or a text-embedding fallback.
    assert op.validate(EXISTING, {}) is True
    output = op.apply(EXISTING, {"comparison_mode": "pairwise"})
    assert [record["similarity.score"] for record in output[0]] == pytest.approx(
        [1.0, 0.7071067811865475]
    )


VALIDATOR_CASES: list[tuple[str, DataBundle, Attributes, bool]] = [
    ("VV1", EXISTING, {}, True),
    ("VV2", [[]], {}, False),
    ("VV3", EXISTING, {"fields": FIELDS}, True),
    ("VV4", EXISTING, {"fields": []}, False),
    ("VV5", EXISTING, {"fields": ("embedding", "embedding")}, False),
    ("VV6", EXISTING, {"fields": [b"embedding", b"embedding"]}, False),
    ("VV7", EXISTING, {"metric": "manhattan"}, False),
    ("VV8", EXISTING, {"comparison_mode": "zip"}, False),
    ("VV9", EXISTING, {"add_meta_data": "yes"}, False),
    ("VV10", EXISTING, {"threshold": "0.5"}, False),
    ("VV11", EXISTING, {"threshold": True}, True),
    ("VV12", EXISTING, {"normalize": "yes"}, False),
    ("VV13", [[{"text": "a"}], [{"text": "b"}]], {}, False),
    (
        "VV14",
        [[{"text": "a"}], [{"text": "b"}]],
        {"fields": ["text", "text"]},
        True,
    ),
    (
        "VV15",
        [[{"embedding": [1.0]}], [{"embedding": [1.0]}, {"embedding": [2.0]}]],
        {"comparison_mode": "pairwise"},
        False,
    ),
]


@pytest.mark.parametrize(
    "case_id,input_data,attributes,expected",
    VALIDATOR_CASES,
    ids=[case[0] for case in VALIDATOR_CASES],
)
def test_validate(
    op: VectorSimilarityOperator,
    case_id: str,
    input_data: DataBundle,
    attributes: Attributes,
    expected: bool,
) -> None:
    assert op.validate(input_data, attributes) is expected


def test_invocation_contract_with_omitted_fields(op: VectorSimilarityOperator) -> None:
    assert op.invoke(EXISTING, {"comparison_mode": "pairwise"}) == op.apply(
        EXISTING, {"comparison_mode": "pairwise"}
    )
    assert op.invoke(EXISTING, {"fields": []}) is None


def test_interface_contract(op: VectorSimilarityOperator) -> None:
    assert (op.name, op.description) == (
        "vector_similarity",
        "Compute similarity between two lists of records using embeddings.",
    )
    expected: dict[str, tuple[str, str, bool, object]] = {
        "model_ref": ("str", "Reference to the embedding model", False, "all-MiniLM-L6-v2"),
        "fields": ("list[str]", "Fields to use when text embedding is needed", False, None),
        "metric": ("str", "Similarity metric", False, "cosine"),
        "comparison_mode": ("str", "Comparison mode: cartesian or pairwise", False, "cartesian"),
        "on_missing_embedding": ("str", "How to handle missing embeddings", False, "raise"),
        "on_missing_fields": (
            "str",
            "How to handle missing fields: raise | use_empty",
            False,
            "raise",
        ),
        "add_meta_data": ("bool", "Add similarity metadata", False, False),
        "threshold": ("float", "Threshold for passed flag", False, None),
        "normalize": ("bool", "Normalize embeddings", False, False),
    }
    assert set(op.attributes) == set(expected)
    for name, interface in expected.items():
        spec = op.attributes[name]
        assert (spec.type, spec.description, op.is_required(name), spec.default) == interface


def test_explain_delegates_to_default(op: VectorSimilarityOperator) -> None:
    output = op.apply(EXISTING, {"comparison_mode": "pairwise"})
    explanation = op.explain(output, EXISTING, {"comparison_mode": "pairwise"})
    assert explanation["output"] == output
    assert explanation["num_input_records"] == 4
    assert explanation["num_output_records"] == 1

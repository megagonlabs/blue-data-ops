from __future__ import annotations

import pytest

from blue_data_ops.operators import Attributes, DataBundle, Properties, VectorSearchOperator
from tests.stubs.sentence_transformers import EncodeCall, SentenceTransformer

EXISTING = [
    {"id": "a", "embedding": [1.0, 0.0, 0.0, 0.0], "embed.model": "model-4d"},
    {"id": "b", "embedding": [0.5, 0.5, 0.0, 0.0], "embed.model": "model-4d"},
    {"id": "c", "embedding": [0.0, 1.0, 0.0, 0.0], "embed.model": "model-4d"},
]
QUERY: dict[str, object] = {"embedding": [1.0, 0.0, 0.0, 0.0], "model": "model-4d"}


@pytest.fixture(autouse=True)
def reset_model_stub() -> None:
    SentenceTransformer.reset()


@pytest.fixture
def op() -> VectorSearchOperator:
    return VectorSearchOperator()


def test_empty_bundle_does_not_load_heavy_model(op: VectorSearchOperator) -> None:
    assert op.apply([], {"query": "alpha"}) == []
    assert SentenceTransformer.model_names == []


def test_existing_cosine_normalize_metadata_and_top_k(op: VectorSearchOperator) -> None:
    output = op.apply(
        [EXISTING],
        {"query": QUERY, "add_meta_data": True},
        {"normalize": True, "top_k": 2},
    )
    assert [record["id"] for record in output[0]] == ["a", "b"]
    assert [record["search.score"] for record in output[0]] == pytest.approx(
        [1.0, 0.7071067811865475]
    )
    assert [record["search.rank"] for record in output[0]] == [1, 2]
    assert output[0][0]["search.metric"] == "cosine"
    assert output[0][0]["search.model"] == "model-4d"
    assert SentenceTransformer.model_names == []


def test_l2_threshold_uses_negative_distance(op: VectorSearchOperator) -> None:
    output = op.apply(
        [EXISTING],
        {"query": QUERY, "metric": "l2"},
        {"min_score": -0.8},
    )
    assert [record["id"] for record in output[0]] == ["a", "b"]
    assert [record["search.score"] for record in output[0]] == pytest.approx(
        [-0.0, -0.7071067811865476]
    )


def test_text_query_candidates_model_calls_and_ranking(op: VectorSearchOperator) -> None:
    output = op.apply(
        [[{"id": "a", "title": "alpha"}, {"id": "b", "title": "beta"}]],
        {"query": "alpha", "search_fields": ["title"], "add_meta_data": True},
        {"top_k": 1, "batch_size": 5},
    )
    assert output == [
        [
            {
                "id": "a",
                "title": "alpha",
                "search.score": 1.0,
                "search.metric": "cosine",
                "search.model": "all-MiniLM-L6-v2",
                "search.rank": 1,
            }
        ]
    ]
    assert SentenceTransformer.model_names == ["all-MiniLM-L6-v2"]
    assert SentenceTransformer.encode_calls == [
        EncodeCall("all-MiniLM-L6-v2", ("alpha",), 1, False),
        EncodeCall("all-MiniLM-L6-v2", ("alpha", "beta"), 5, False),
    ]


def test_mixed_candidates_embed_only_missing_records(op: VectorSearchOperator) -> None:
    output = op.apply(
        [
            [
                {"id": "missing", "title": "alpha"},
                {
                    "id": "existing",
                    "embedding": [1.0, 0.0, 0.0, 0.0],
                    "embed.model": "all-MiniLM-L6-v2",
                },
            ]
        ],
        {
            "query": {
                "embedding": [1.0, 0.0, 0.0, 0.0],
                "model": "all-MiniLM-L6-v2",
            },
            "search_fields": ["title"],
        },
    )
    assert [record["id"] for record in output[0]] == ["existing", "missing"]
    assert [record["search.score"] for record in output[0]] == pytest.approx(
        [1.0, 0.3605292027026634]
    )
    assert SentenceTransformer.encode_calls == [
        EncodeCall("all-MiniLM-L6-v2", ("alpha",), 32, False)
    ]


def test_empty_group_still_embeds_text_query_once(op: VectorSearchOperator) -> None:
    assert op.apply([[]], {"query": "alpha"}) == [[]]
    assert SentenceTransformer.encode_calls == [
        EncodeCall("all-MiniLM-L6-v2", ("alpha",), 1, False)
    ]


def test_missing_search_field_policies(op: VectorSearchOperator) -> None:
    with pytest.raises(ValueError, match=r"Missing search fields \['title'\]"):
        op.apply([[{"id": "x"}]], {"query": "alpha", "search_fields": ["title"]})

    SentenceTransformer.reset()
    output = op.apply(
        [[{"id": "x"}]],
        {
            "query": "alpha",
            "search_fields": ["title"],
            "on_missing_fields": "use_empty",
        },
    )
    assert output[0][0]["search.score"] == pytest.approx(0.9253789324040611)
    assert SentenceTransformer.encode_calls[1].sentences == ("",)


def test_missing_embedding_raise_policy(op: VectorSearchOperator) -> None:
    with pytest.raises(ValueError, match="Missing candidate embedding"):
        op.apply(
            [[{"id": "x", "title": "alpha"}]],
            {"query": "alpha", "on_missing_embedding": "raise"},
        )


@pytest.mark.parametrize(
    "input_data,attributes,message",
    [
        (
            [[{"id": "x", "embedding": [1.0, 0.0]}]],
            {"query": {"embedding": [1.0, 0.0], "model": "m"}},
            "Candidate embedding metadata is missing embed.model",
        ),
        (
            [
                [
                    {"embedding": [1.0, 0.0], "embed.model": "m1"},
                    {"embedding": [0.0, 1.0], "embed.model": "m2"},
                ]
            ],
            {"query": {"embedding": [1.0, 0.0], "model": "m1"}},
            "Inconsistent candidate embed.model values",
        ),
        (
            [[{"embedding": [1.0, 0.0], "embed.model": "model-4d"}]],
            {"query": {"embedding": [1.0, 0.0], "model": "other"}},
            "Embedding space mismatch",
        ),
        (
            [[{"embedding": [1.0, 0.0], "embed.model": "model-4d"}]],
            {"query": {"embedding": [1.0, 0.0]}},
            "Query embedding is missing model metadata",
        ),
        (
            [EXISTING],
            {"query": {"embedding": [[1.0, 0.0]], "model": "model-4d"}},
            "Query embedding must be 1-dimensional",
        ),
        (
            [[{"title": "alpha"}]],
            {"query": "alpha", "model_ref": "custom"},
            "Unsupported embedding model: custom",
        ),
    ],
    ids=["missing-model", "inconsistent", "mismatch", "query-no-model", "2d-query", "model"],
)
def test_error_surfaces(
    op: VectorSearchOperator,
    input_data: DataBundle,
    attributes: Attributes,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        op.apply(input_data, attributes)


def test_attribute_property_split_is_preserved(op: VectorSearchOperator) -> None:
    attributes: Attributes = {"query": QUERY, "top_k": 1}
    assert len(op.apply([EXISTING], attributes)[0]) == 3
    assert len(op.apply([EXISTING], {"query": QUERY}, {"top_k": 1})[0]) == 1


VALIDATOR_CASES: list[tuple[str, Attributes, Properties | None, bool]] = [
    ("SV1", {"query": "alpha"}, None, True),
    ("SV2", {"query": QUERY}, None, True),
    ("SV3", {}, None, False),
    ("SV4", {"query": 1}, None, False),
    ("SV5", {"query": "alpha", "search_fields": ["title"]}, None, True),
    ("SV6", {"query": "alpha", "search_fields": ("title",)}, None, False),
    ("SV7", {"query": "alpha", "search_fields": [b"title"]}, None, False),
    ("SV8", {"query": "alpha", "metric": "manhattan"}, None, False),
    ("SV9", {"query": "alpha", "top_k": "2"}, None, True),
    ("SV10", {"query": "alpha"}, {"top_k": "2"}, False),
    ("SV11", {"query": "alpha"}, {"top_k": 0}, False),
    ("SV12", {"query": "alpha"}, {"normalize": "yes"}, False),
    ("SV13", {"query": "alpha"}, {"batch_size": 0}, False),
    ("SV14", {"query": "alpha", "on_missing_fields": "skip"}, None, False),
    ("SV15", {"query": "alpha", "add_meta_data": "yes"}, None, True),
]


@pytest.mark.parametrize(
    "case_id,attributes,properties,expected",
    VALIDATOR_CASES,
    ids=[case[0] for case in VALIDATOR_CASES],
)
def test_validate(
    op: VectorSearchOperator,
    case_id: str,
    attributes: Attributes,
    properties: Properties | None,
    expected: bool,
) -> None:
    assert op.validate([EXISTING], attributes, properties) is expected


def test_invocation_contract(op: VectorSearchOperator) -> None:
    assert op.invoke([EXISTING], {"query": QUERY}) == op.apply([EXISTING], {"query": QUERY})
    assert op.invoke([EXISTING], {}) is None


def test_interface_contract(op: VectorSearchOperator) -> None:
    assert (op.name, op.description) == (
        "vector_search",
        "Perform semantic search within each dataset using text or vector queries.",
    )
    expected: dict[str, tuple[str, str, bool, object]] = {
        "query": ("str | dict", "Query text or query embedding object", True, None),
        "search_fields": ("list[str]", "Keys containing searchable text", False, None),
        "model_ref": ("str", "Reference to the embedding model", False, "all-MiniLM-L6-v2"),
        "metric": ("str", "Similarity metric: cosine | dot | l2", False, "cosine"),
        "add_meta_data": ("bool", "Add search.metric and search.model", False, False),
        "on_missing_embedding": (
            "str",
            "How to handle missing candidate embeddings: embed_missing | raise",
            False,
            "embed_missing",
        ),
        "on_missing_fields": (
            "str",
            "How to handle missing search fields: raise | use_empty",
            False,
            "raise",
        ),
        "top_k": ("int", "Maximum number of results per dataset", False, 10),
        "min_score": ("float", "Minimum score threshold", False, None),
        "normalize": ("bool", "L2-normalize embeddings before scoring", False, False),
    }
    assert set(op.attributes) == set(expected)
    for name, interface in expected.items():
        spec = op.attributes[name]
        assert (spec.type, spec.description, op.is_required(name), spec.default) == interface


def test_explain_delegates_to_default(op: VectorSearchOperator) -> None:
    attributes: Attributes = {"query": QUERY}
    output = op.apply([EXISTING], attributes)
    explanation = op.explain(output, [EXISTING], attributes)
    assert explanation["output"] == output
    assert explanation["num_input_records"] == 3
    assert explanation["num_output_records"] == 1

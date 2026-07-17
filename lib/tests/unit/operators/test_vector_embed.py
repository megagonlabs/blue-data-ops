from __future__ import annotations

import pytest

from blue_data_ops.operators import Attributes, DataBundle, Properties, VectorEmbedOperator
from tests.stubs.sentence_transformers import EncodeCall, SentenceTransformer

INPUT = [
    [
        {"id": "d1", "title": "alpha", "body": "one"},
        {"id": "d2", "title": "beta", "body": "two"},
    ]
]


@pytest.fixture(autouse=True)
def reset_model_stub() -> None:
    SentenceTransformer.reset()


@pytest.fixture
def op() -> VectorEmbedOperator:
    return VectorEmbedOperator()


@pytest.mark.parametrize(
    "input_data",
    [[], [[]], [[], INPUT[0]]],
    ids=["empty-bundle", "empty-first-group", "empty-first-drops-later-data"],
)
def test_empty_guards_do_not_load_model(op: VectorEmbedOperator, input_data: DataBundle) -> None:
    assert op.apply(input_data, {}) == [[]]
    assert SentenceTransformer.model_names == []
    assert SentenceTransformer.encode_calls == []


def test_selected_fields_append_metadata_and_normalization(op: VectorEmbedOperator) -> None:
    attributes: Attributes = {
        "text_field": ["title", "body"],
        "delimiter": "|",
        "append": True,
        "add_meta_data": True,
    }
    output = op.apply(INPUT, attributes, {"batch_size": 7, "normalize": True})
    assert SentenceTransformer.model_names == ["all-MiniLM-L6-v2"]
    assert SentenceTransformer.encode_calls == [
        EncodeCall("all-MiniLM-L6-v2", ("alpha|one", "beta|two"), 7, True)
    ]
    assert output[0][0] == {
        **INPUT[0][0],
        "embedding": pytest.approx(
            [
                0.5074419812808469,
                0.6483980871921933,
                0.5517424717101272,
                0.13290147128784088,
            ]
        ),
        "embed.model": "all-MiniLM-L6-v2",
        "embed.dim": 4,
        "embed.fields": "['title', 'body']",
    }
    assert output[0][1]["embedding"] == pytest.approx(
        [
            0.6166626010632974,
            0.3014794938531676,
            0.16101745694430541,
            0.7091619912227919,
        ]
    )
    assert output[0][0] is not INPUT[0][0]


def test_all_fields_are_sorted_and_embedding_only(op: VectorEmbedOperator) -> None:
    output = op.apply(INPUT, {"add_meta_data": True}, {"batch_size": 3})
    assert SentenceTransformer.encode_calls == [
        EncodeCall(
            "all-MiniLM-L6-v2",
            ("one\nd1\nalpha", "two\nd2\nbeta"),
            3,
            False,
        )
    ]
    assert output == [
        [
            {
                "id": "d1",
                "embedding": [
                    0.6509803921568628,
                    0.5333333333333333,
                    0.23137254901960785,
                    0.8156862745098039,
                ],
                "embed.model": "all-MiniLM-L6-v2",
                "embed.dim": 4,
                "embed.fields": "all_fields",
            },
            {
                "id": "d2",
                "embedding": [
                    0.011764705882352941,
                    0.10980392156862745,
                    0.5803921568627451,
                    0.3411764705882353,
                ],
                "embed.model": "all-MiniLM-L6-v2",
                "embed.dim": 4,
                "embed.fields": "all_fields",
            },
        ]
    ]


def test_use_empty_missing_fields_and_fallback_id(op: VectorEmbedOperator) -> None:
    output = op.apply(
        [[{"id": "a", "title": "alpha"}, {}]],
        {"text_field": ["title"], "on_missing_fields": "use_empty"},
    )
    assert SentenceTransformer.encode_calls == [
        EncodeCall("all-MiniLM-L6-v2", ("alpha", ""), 32, False)
    ]
    assert [record["id"] for record in output[0]] == ["a", "index_1"]


def test_missing_and_empty_selected_fields_raise_before_encode(
    op: VectorEmbedOperator,
) -> None:
    with pytest.raises(ValueError, match=r"Missing text fields \['title'\]"):
        op.apply([[{"id": "missing"}]], {"text_field": ["title"]})
    assert SentenceTransformer.model_names == ["all-MiniLM-L6-v2"]
    assert SentenceTransformer.encode_calls == []

    SentenceTransformer.reset()
    with pytest.raises(ValueError, match="All configured text_field values are empty"):
        op.apply([[{"title": ""}]], {"text_field": ["title"]})
    assert SentenceTransformer.encode_calls == []


def test_custom_model_name_is_forwarded(op: VectorEmbedOperator) -> None:
    op.apply(INPUT, {"model_ref": "custom-model", "text_field": ["title"]})
    assert SentenceTransformer.model_names == ["custom-model"]
    assert SentenceTransformer.encode_calls[0].sentences == ("alpha", "beta")


def test_invalid_policy_precedes_empty_guard(op: VectorEmbedOperator) -> None:
    with pytest.raises(ValueError, match="on_missing_fields must be one of"):
        op.apply([], {"on_missing_fields": "skip"})
    assert SentenceTransformer.model_names == []


def test_empty_later_group_does_not_add_encode_call(op: VectorEmbedOperator) -> None:
    output = op.apply(
        [INPUT[0], []],
        {"text_field": ["title"]},
    )
    assert len(SentenceTransformer.encode_calls) == 1
    assert output[1] == []


VALIDATOR_CASES: list[tuple[str, Attributes, Properties | None, bool]] = [
    ("EV1", {}, None, True),
    ("EV2", {"text_field": ["title"]}, None, True),
    ("EV3", {"text_field": ("title",)}, None, False),
    ("EV4", {"text_field": [b"title"]}, None, False),
    ("EV5", {"on_missing_fields": "skip"}, None, False),
    ("EV6", {}, {"batch_size": 1}, True),
    ("EV7", {}, {"batch_size": "1"}, False),
    ("EV8", {}, {"batch_size": 0}, False),
    ("EV9", {}, {"normalize": True}, True),
    ("EV10", {}, {"normalize": "yes"}, False),
    ("EV11", {"append": "yes"}, None, True),
    ("EV12", {"model_ref": b"model"}, None, True),
]


@pytest.mark.parametrize(
    "case_id,attributes,properties,expected",
    VALIDATOR_CASES,
    ids=[case[0] for case in VALIDATOR_CASES],
)
def test_validate(
    op: VectorEmbedOperator,
    case_id: str,
    attributes: Attributes,
    properties: Properties | None,
    expected: bool,
) -> None:
    assert op.validate(INPUT, attributes, properties) is expected


def test_invocation_contract(op: VectorEmbedOperator) -> None:
    assert op.invoke(INPUT, {"text_field": ["title"]}) == op.apply(INPUT, {"text_field": ["title"]})
    assert op.invoke(INPUT, {"text_field": ("title",)}) is None


def test_interface_contract(op: VectorEmbedOperator) -> None:
    assert (op.name, op.description) == (
        "vector_embed",
        "Convert text data into vector embeddings using a specified model.",
    )
    expected: dict[str, tuple[str, str, bool, object]] = {
        "model_ref": ("str", "Reference to the embedding model", False, "all-MiniLM-L6-v2"),
        "text_field": ("list[str]", "Keys containing the raw text", False, []),
        "delimiter": ("str", "Delimiter for concatenating text fields", False, "\n"),
        "append": (
            "bool",
            "Append embeddings to dataset or return only embeddings",
            False,
            False,
        ),
        "add_meta_data": ("bool", "Add embed.model and embed.dim to output", False, False),
        "on_missing_fields": (
            "str",
            "How to handle missing text fields: raise | use_empty",
            False,
            "raise",
        ),
    }
    assert set(op.attributes) == set(expected)
    for name, interface in expected.items():
        spec = op.attributes[name]
        assert (spec.type, spec.description, op.is_required(name), spec.default) == interface


def test_explain_delegates_to_default(op: VectorEmbedOperator) -> None:
    attributes: Attributes = {"text_field": ["title"]}
    output = op.apply(INPUT, attributes)
    explanation = op.explain(output, INPUT, attributes)
    assert explanation["output"] == output
    assert explanation["num_input_records"] == 2
    assert explanation["num_output_records"] == 1

from __future__ import annotations

import pytest

from blue_data_ops.operators import Attributes, DataBundle, SegmentTextOperator

INPUT = [[{"doc_id": "doc", "text": "Hello world."}]]


@pytest.fixture
def op() -> SegmentTextOperator:
    return SegmentTextOperator()


def _spans(output: DataBundle) -> list[tuple[str, int, int]]:
    return [
        (str(record["text"]), int(record["start_char"]), int(record["end_char"]))
        for record in output[0]
    ]


def test_empty_and_missing_text_shapes(op: SegmentTextOperator) -> None:
    attributes: Attributes = {"text_field": "text"}
    assert op.apply([], attributes) == []
    assert op.apply([[]], attributes) == [[]]
    assert op.apply([[{"id": 1}]], attributes) == [[]]
    assert op.apply([[{"text": "  \n "}]], attributes) == [[]]


def test_short_sentence_interface_record(op: SegmentTextOperator) -> None:
    assert op.apply(INPUT, {"text_field": "text"}) == [
        [
            {
                "segment_id": "doc::S0000",
                "doc_id": "doc",
                "text": "Hello world.",
                "start_char": 0,
                "end_char": 12,
                "segment.split_strategy": "sentence",
            }
        ]
    ]


def test_boundary_units_overlap_and_large_unit_chunking(op: SegmentTextOperator) -> None:
    text = (
        "Alpha launches the workflow. Beta checks intermediate state. "
        "Gamma records a detailed event trail. Delta publishes the final summary."
    )
    output = op.apply(
        [[{"doc_id": "doc", "text": text}]],
        {
            "text_field": "text",
            "split_strategy": "sentence",
            "max_tokens": 8,
            "word_overlap": 2,
            "min_chars": 10,
        },
    )
    assert _spans(output) == [
        ("Alpha launches the workflow.", 0, 28),
        ("Beta checks intermediate state.", 29, 60),
        ("Gamma records a detailed event trail.", 61, 98),
        ("Delta publishes the final summary.", 99, 133),
    ]

    large = (
        "one two three four five six seven eight nine ten eleven twelve thirteen "
        "fourteen fifteen sixteen."
    )
    large_output = op.apply(
        [[{"doc_id": "doc", "text": large}]],
        {
            "text_field": "text",
            "split_strategy": "sentence",
            "max_tokens": 5,
            "word_overlap": 2,
            "min_chars": 1,
        },
    )
    assert _spans(large_output) == [
        ("one two three four five", 0, 23),
        ("four five six seven eight", 14, 39),
        ("seven eight nine ten eleven", 28, 55),
        ("ten eleven twelve thirteen fourteen", 45, 80),
        ("thirteen fourteen fifteen sixteen.", 63, 97),
    ]


def test_word_token_remainder_and_overlap(op: SegmentTextOperator) -> None:
    word_output = op.apply(
        [[{"doc_id": "doc", "text": "one  two three four five"}]],
        {
            "text_field": "text",
            "split_strategy": "word",
            "max_tokens": 2,
            "word_overlap": 1,
            "min_chars": 1,
        },
    )
    assert _spans(word_output) == [
        ("one  two", 0, 8),
        ("two three", 5, 14),
        ("three four", 9, 19),
        ("four five", 15, 24),
        ("five", 20, 24),
    ]
    token_output = op.apply(
        [[{"doc_id": "doc", "text": "one two three"}]],
        {
            "text_field": "text",
            "split_strategy": "token",
            "max_tokens": 2,
            "min_chars": 1,
        },
    )
    assert _spans(token_output) == [("one two", 0, 7), ("three", 8, 13)]
    assert all(record["segment.split_strategy"] == "token" for record in token_output[0])


def test_paragraph_delimiters_heading_and_minimum(op: SegmentTextOperator) -> None:
    paragraph = op.apply(
        [[{"doc_id": "doc", "text": "Para one.\n\nPara two.\n\n\nPara three."}]],
        {"text_field": "text", "split_strategy": "paragraph", "min_chars": 1},
    )
    assert _spans(paragraph) == [
        ("Para one.", 0, 9),
        ("Para two.", 11, 20),
        ("Para three.", 23, 34),
    ]
    delimiters = op.apply(
        [[{"doc_id": "doc", "text": "One.  Two!\nThree?"}]],
        {
            "text_field": "text",
            "split_strategy": "sentence",
            "keep_delimiters": True,
            "min_chars": 1,
        },
    )
    assert _spans(delimiters) == [
        ("One.  ", 0, 6),
        ("Two!\n", 6, 11),
        ("Three?", 11, 17),
    ]
    heading_text = "Preamble text.\nINTRODUCTION\nBody text.\n\nNext Steps:\nDone."
    heading = op.apply(
        [[{"doc_id": "doc", "text": heading_text}]],
        {"text_field": "text", "split_strategy": "heading", "min_chars": 1},
    )
    assert _spans(heading) == [
        ("INTRODUCTION\nBody text.", 15, 38),
        ("Next Steps:\nDone.", 40, 57),
    ]
    merged = op.apply(
        [[{"doc_id": "doc", "text": "A. B. Longer sentence."}]],
        {"text_field": "text", "split_strategy": "sentence", "min_chars": 12},
    )
    assert _spans(merged) == [("A. B. Longer sentence.", 0, 22)]


def test_ids_metadata_groups_and_stringification(op: SegmentTextOperator) -> None:
    fallback = op.apply([[{"text": "Hello."}], [{"text": "World."}]], {"text_field": "text"})
    assert [group[0]["doc_id"] for group in fallback] == [
        "table1_row1_text",
        "table2_row1_text",
    ]
    custom = op.apply(
        [[{"doc_id": "d1", "text": "Hello.", "source": "s"}]],
        {
            "text_field": "text",
            "meta_fields": ["source", "missing"],
            "segment_id_format": ("{doc_id}|{field_name}|{group_index}|{record_index}|{index}"),
        },
    )
    assert custom[0][0]["segment_id"] == "d1|text|0|0|0"
    assert custom[0][0]["segment.source"] == "s"
    assert "segment.missing" not in custom[0][0]
    numeric = op.apply([[{"doc_id": "doc", "text": 12345}]], {"text_field": "text"})
    assert _spans(numeric) == [("12345", 0, 5)]


VALIDATOR_CASES: list[tuple[str, Attributes, bool]] = [
    ("SV1", {"text_field": "text"}, True),
    ("SV2", {}, False),
    ("SV3", {"text_field": " "}, False),
    ("SV4", {"text_field": b"text"}, False),
    ("SV5", {"text_field": "text", "split_strategy": "token"}, True),
    ("SV6", {"text_field": "text", "split_strategy": "line"}, False),
    ("SV7", {"text_field": "text", "word_overlap": -1}, False),
    ("SV8", {"text_field": "text", "max_tokens": 0}, False),
    ("SV9", {"text_field": "text", "min_chars": -1}, False),
    ("SV10", {"text_field": "text", "meta_fields": ("id",)}, False),
    ("SV11", {"text_field": "text", "meta_fields": [b"id"]}, False),
    ("SV12-total-port", {"text_field": "text", "max_tokens": "3"}, False),
    ("SV13", {"text_field": "text", "max_tokens": 3.0}, True),
    ("SV14-total-port", {"text_field": "text", "word_overlap": "1"}, False),
    ("SV15", {"text_field": "text", "keep_delimiters": "no"}, True),
    ("SV16", {"text_field": "text", "segment_id_format": b"{doc_id}"}, True),
]


@pytest.mark.parametrize(
    "case_id,attributes,expected",
    VALIDATOR_CASES,
    ids=[case[0] for case in VALIDATOR_CASES],
)
def test_validate(
    op: SegmentTextOperator, case_id: str, attributes: Attributes, expected: bool
) -> None:
    assert op.validate(INPUT, attributes) is expected


def test_invocation_and_documented_bug_surface(op: SegmentTextOperator) -> None:
    assert op.invoke(INPUT, {"text_field": "text", "max_tokens": "3"}) is None
    assert op.invoke(INPUT, {"text_field": "text", "word_overlap": "1"}) is None
    with pytest.raises(AttributeError):
        op.invoke(INPUT, {"text_field": "text", "segment_id_format": b"{doc_id}"})
    float_output = op.invoke(
        [[{"doc_id": "doc", "text": "one two three"}]],
        {"text_field": "text", "split_strategy": "word", "max_tokens": 3.0},
    )
    assert float_output is not None
    assert _spans(float_output) == [("one two three", 0, 13)]


def test_unknown_segment_id_placeholder_propagates_key_error(
    op: SegmentTextOperator,
) -> None:
    with pytest.raises(KeyError, match="bogus"):
        op.invoke(INPUT, {"text_field": "text", "segment_id_format": "{bogus}"})


def test_interface_contract(op: SegmentTextOperator) -> None:
    assert (op.name, op.description) == (
        "segment_text",
        "Split normalized text into stable segments with offsets and flat metadata.",
    )
    expected: dict[str, tuple[str, str, bool, object]] = {
        "text_field": ("str", "Field containing normalized text to segment", True, None),
        "split_strategy": (
            "str",
            "Segmentation strategy: sentence, paragraph, token, word, or heading",
            False,
            "sentence",
        ),
        "word_overlap": (
            "int",
            "Approximate number of words to overlap between segments",
            False,
            0,
        ),
        "max_tokens": ("int", "Approximate maximum token budget per segment", False, 650),
        "min_chars": ("int", "Minimum characters per segment when possible", False, 20),
        "keep_delimiters": ("bool", "Whether to retain delimiters in segment units", False, False),
        "meta_fields": (
            "list[str]",
            "Record fields to copy into flat segment metadata keys",
            False,
            [],
        ),
        "segment_id_format": (
            "str",
            "Segment identifier template using doc_id and index placeholders",
            False,
            "{doc_id}::S{index:04d}",
        ),
    }
    assert set(op.attributes) == set(expected)
    for name, interface in expected.items():
        spec = op.attributes[name]
        assert (spec.type, spec.description, op.is_required(name), spec.default) == interface


def test_explain_delegates_to_default(op: SegmentTextOperator) -> None:
    attributes: Attributes = {"text_field": "text"}
    output = op.apply(INPUT, attributes)
    explanation = op.explain(output, INPUT, attributes)
    assert explanation["output"] == output
    assert explanation["num_input_records"] == 1
    assert explanation["num_output_records"] == 1

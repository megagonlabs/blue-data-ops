from __future__ import annotations

import pytest

from blue_data_ops.operators import Attributes, NormalizeTextOperator

INPUT = [[{"text": "abcdef"}]]


@pytest.fixture
def op() -> NormalizeTextOperator:
    return NormalizeTextOperator()


def test_empty_shapes(op: NormalizeTextOperator) -> None:
    attributes: Attributes = {"text_field": ["text"]}
    assert op.apply([], attributes) == []
    assert op.apply([[]], attributes) == [[]]


def test_default_nfkc_whitespace_and_bullets(op: NormalizeTextOperator) -> None:
    source = "Foo\u00a0\u00a0Bar\n•  Item 1\n•\tItem 2"
    assert op.apply([[{"id": "doc1", "text": source}]], {"text_field": ["text"]}) == [
        [{"id": "doc1", "text": source, "text_norm": "Foo Bar\n- Item 1\n- Item 2"}]
    ]
    assert (
        op.apply([[{"text": source}]], {"text_field": ["text"], "strip_newline": True})[0][0][
            "text_norm"
        ]
        == "Foo Bar - Item 1 - Item 2"
    )


def test_whitespace_and_control_switches(op: NormalizeTextOperator) -> None:
    assert (
        op.apply(
            [[{"text": "  A   B\tC \n  D  "}]],
            {"text_field": ["text"], "normalize_whitespace": False},
        )[0][0]["text_norm"]
        == "A   B\tC\nD"
    )
    control = "A\x00B\u200bC\tD\nE"
    assert (
        op.apply([[{"text": control}]], {"text_field": ["text"]})[0][0]["text_norm"] == "ABC D\nE"
    )
    assert (
        op.apply(
            [[{"text": control}]],
            {"text_field": ["text"], "strip_control_chars": False},
        )[0][0]["text_norm"]
        == "A\x00B\u200bC D\nE"
    )


def test_date_normalization_is_selective(op: NormalizeTextOperator) -> None:
    input_data = [
        [
            {"text": "Jan 2, 2024; 3 February 2025; 2024/3/4"},
            {"text": "02/29/2026; 03/04/2025; 13/04/2026; 4.20.2026"},
        ]
    ]
    output = op.apply(input_data, {"text_field": ["text"], "normalize_dates": True})[0]
    assert [record["text_norm"] for record in output] == [
        "2024-01-02; 2025-02-03; 2024-03-04",
        "02/29/2026; 03/04/2025; 2026-04-13; 2026-04-20",
    ]


def test_sept_month_abbreviation(op: NormalizeTextOperator) -> None:
    output = op.apply(
        [[{"text": "Sept 5, 2024"}]],
        {"text_field": ["text"], "normalize_dates": True},
    )
    assert output[0][0]["text_norm"] == "Sept 5, 2024"


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("NFC", "é ① ﬁ Ａ"),
        ("NFD", "é ① ﬁ Ａ"),
        ("NFKC", "é 1 fi A"),
        ("NFKD", "é 1 fi A"),
    ],
)
def test_exact_unicode_forms(op: NormalizeTextOperator, mode: str, expected: str) -> None:
    output = op.apply(
        [[{"text": "é ① ﬁ Ａ"}]],
        {"text_field": ["text"], "normalize_unicode": mode},
    )
    assert output[0][0]["text_norm"] == expected


def test_fields_output_name_values_groups_and_limit(op: NormalizeTextOperator) -> None:
    nested: list[int] = [1]
    output = op.apply(
        [[{"title": " Hello ", "missing": None, "body": " World ", "nested": nested}]],
        {
            "text_field": ["title", "missing", "body"],
            "delimiter": " | ",
            "max_chars": 8,
        },
    )
    assert output == [
        [
            {
                "title": " Hello ",
                "missing": None,
                "body": " World ",
                "nested": [1],
                "title_norm": "Hello | ",
            }
        ]
    ]
    assert output[0][0]["nested"] is nested
    assert op.apply([[{"id": 1}]], {"text_field": ["text"]}) == [[{"id": 1, "text_norm": ""}]]
    assert op.apply([[{"text": 1234}]], {"text_field": ["text"]})[0][0]["text_norm"] == "1234"
    assert op.apply([[{"text": " A "}], [], [{"text": " B "}]], {"text_field": ["text"]}) == [
        [{"text": " A ", "text_norm": "A"}],
        [],
        [{"text": " B ", "text_norm": "B"}],
    ]
    assert op.apply(INPUT, {"text_field": ["text"], "max_chars": 3})[0][0]["text_norm"] == "abc"


VALIDATOR_CASES: list[tuple[str, Attributes, bool]] = [
    ("NV1", {"text_field": ["text"]}, True),
    ("NV2", {}, False),
    ("NV3", {"text_field": []}, False),
    ("NV4", {"text_field": ("text",)}, False),
    ("NV5", {"text_field": [b"text"]}, False),
    ("NV6", {"text_field": [" "]}, False),
    ("NV7", {"text_field": ["text"], "normalize_unicode": "NFD"}, True),
    ("NV8", {"text_field": ["text"], "normalize_unicode": "NFKX"}, False),
    ("NV9", {"text_field": ["text"], "normalize_unicode": b"NFKC"}, False),
    ("NV10", {"text_field": ["text"], "max_chars": 0}, True),
    ("NV11", {"text_field": ["text"], "max_chars": -1}, False),
    ("NV12", {"text_field": ["text"], "max_chars": 3.0}, True),
    ("NV13-total-port", {"text_field": ["text"], "max_chars": "3"}, False),
    ("NV14", {"text_field": ["text"], "max_chars": None}, False),
    ("NV15", {"text_field": ["text"], "delimiter": b"|"}, True),
    ("NV16", {"text_field": ["text"], "strip_newline": "no"}, True),
]


@pytest.mark.parametrize(
    "case_id,attributes,expected",
    VALIDATOR_CASES,
    ids=[case[0] for case in VALIDATOR_CASES],
)
def test_validate(
    op: NormalizeTextOperator, case_id: str, attributes: Attributes, expected: bool
) -> None:
    assert op.validate(INPUT, attributes) is expected


def test_invocation_and_documented_bug_surface(op: NormalizeTextOperator) -> None:
    assert op.invoke(INPUT, {"text_field": ["text"], "max_chars": "3"}) is None
    with pytest.raises(TypeError):
        op.invoke(INPUT, {"text_field": ["text"], "max_chars": 3.0})
    with pytest.raises(TypeError):
        op.invoke(INPUT, {"text_field": ["text"], "delimiter": b"|"})
    output = op.invoke(
        [[{"text": "a\nb"}]],
        {"text_field": ["text"], "strip_newline": "no"},
    )
    assert output is not None
    assert output[0][0]["text_norm"] == "a b"


def test_interface_contract(op: NormalizeTextOperator) -> None:
    assert (op.name, op.description) == (
        "normalize_text",
        "Normalize raw text into a stable canonical form for downstream extraction "
        "and segmentation.",
    )
    expected: dict[str, tuple[str, str, bool, object]] = {
        "text_field": ("list[str]", "List of input text fields to normalize", True, None),
        "delimiter": ("str", "Delimiter used to concatenate multiple text fields", False, "\n"),
        "strip_newline": ("bool", "Whether to collapse line breaks into spaces", False, False),
        "normalize_unicode": ("str", "Unicode normalization mode", False, "NFKC"),
        "normalize_whitespace": (
            "bool",
            "Whether to collapse repeated spaces and tabs",
            False,
            True,
        ),
        "normalize_bullets": (
            "bool",
            "Whether to normalize common bullet markers to a hyphen",
            False,
            True,
        ),
        "normalize_dates": (
            "bool",
            "Whether to normalize unambiguous date strings to YYYY-MM-DD",
            False,
            False,
        ),
        "strip_control_chars": ("bool", "Whether to strip control characters", False, True),
        "max_chars": (
            "int",
            "Maximum number of characters to keep after normalization",
            False,
            None,
        ),
    }
    assert set(op.attributes) == set(expected)
    for name, interface in expected.items():
        spec = op.attributes[name]
        assert (spec.type, spec.description, op.is_required(name), spec.default) == interface


def test_explain_delegates_to_default(op: NormalizeTextOperator) -> None:
    attributes: Attributes = {"text_field": ["text"]}
    output = op.apply(INPUT, attributes)
    explanation = op.explain(output, INPUT, attributes)
    assert explanation["output"] == output
    assert explanation["num_input_records"] == 1
    assert explanation["num_output_records"] == 1

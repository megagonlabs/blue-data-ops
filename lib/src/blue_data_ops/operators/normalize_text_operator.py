from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import ClassVar, Literal, cast

from blue_data_ops.operators._discovery import DiscoverySpec
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    Data,
    DataBundle,
    FunctionResult,
    Properties,
    Record,
    ValidationResult,
)

_BULLET_LINE_PATTERN = re.compile(
    r"(?m)^([ \t]*)[\-\*\u2022\u2023\u2043\u204c\u204d\u2219\u25e6\u25aa\u25cf]+[ \t]*"
)
_ISO_DATE_PATTERN = re.compile(r"\b(?P<year>\d{4})[-/.](?P<month>\d{1,2})[-/.](?P<day>\d{1,2})\b")
_NUMERIC_DATE_PATTERN = re.compile(
    r"\b(?P<first>\d{1,2})[-/.](?P<second>\d{1,2})[-/.](?P<year>\d{4})\b"
)
_MONTH_NAME = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?"
)
_MONTH_NAME_DATE_PATTERNS: tuple[tuple[re.Pattern[str], str, tuple[str, ...]], ...] = (
    (
        re.compile(
            rf"\b(?P<month_name>{_MONTH_NAME})\.?\s+(?P<day>\d{{1,2}})"
            rf"(?:st|nd|rd|th)?(?:,)?\s+(?P<year>\d{{4}})\b",
            re.IGNORECASE,
        ),
        "{month_name} {day} {year}",
        ("%b %d %Y", "%B %d %Y"),
    ),
    (
        re.compile(
            rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+"
            rf"(?P<month_name>{_MONTH_NAME})\.?[,]?\s+"
            rf"(?P<year>\d{{4}})\b",
            re.IGNORECASE,
        ),
        "{day} {month_name} {year}",
        ("%d %b %Y", "%d %B %Y"),
    ),
)
_UnicodeForm = Literal["NFC", "NFD", "NFKC", "NFKD"]


class NormalizeTextOperator(Operator):
    """Canonicalize text fields for downstream text processing."""

    name: ClassVar[str] = "normalize_text"
    description: ClassVar[str] = (
        "Normalize raw text into a stable canonical form for downstream extraction "
        "and segmentation."
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "text_field": AttributeSpec(
            type="list[str]",
            description="List of input text fields to normalize",
            required=True,
        ),
        "delimiter": AttributeSpec(
            type="str",
            description="Delimiter used to concatenate multiple text fields",
            default="\n",
        ),
        "strip_newline": AttributeSpec(
            type="bool",
            description="Whether to collapse line breaks into spaces",
            default=False,
        ),
        "normalize_unicode": AttributeSpec(
            type="str",
            description="Unicode normalization mode",
            default="NFKC",
        ),
        "normalize_whitespace": AttributeSpec(
            type="bool",
            description="Whether to collapse repeated spaces and tabs",
            default=True,
        ),
        "normalize_bullets": AttributeSpec(
            type="bool",
            description="Whether to normalize common bullet markers to a hyphen",
            default=True,
        ),
        "normalize_dates": AttributeSpec(
            type="bool",
            description="Whether to normalize unambiguous date strings to YYYY-MM-DD",
            default=False,
        ),
        "strip_control_chars": AttributeSpec(
            type="bool",
            description="Whether to strip control characters",
            default=True,
        ),
        "max_chars": AttributeSpec(
            type="int",
            description="Maximum number of characters to keep after normalization",
        ),
    }

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        return self._execute(input_data, attributes, properties).output_data

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        text_fields = cast(list[str], attributes.get("text_field", []))
        delimiter = cast(str, attributes.get("delimiter", "\n"))
        normalize_unicode_mode = cast(str, attributes.get("normalize_unicode", "NFKC"))
        normalize_whitespace = cast(bool, attributes.get("normalize_whitespace", True))
        strip_control_chars = cast(bool, attributes.get("strip_control_chars", True))
        normalize_bullets = cast(bool, attributes.get("normalize_bullets", True))
        normalize_dates = cast(bool, attributes.get("normalize_dates", False))
        strip_newline = cast(bool, attributes.get("strip_newline", False))
        max_chars = cast(int | None, attributes.get("max_chars"))

        results: DataBundle = []
        for data_group in input_data:
            normalized_group: Data = []
            for record in data_group:
                normalized_record: Record = dict(record)
                normalized_record[
                    f"{text_fields[0]}_norm" if text_fields and text_fields[0] else "text_norm"
                ] = _normalize_record_text(
                    record,
                    text_fields=text_fields,
                    delimiter=delimiter,
                    strip_newline=strip_newline,
                    normalize_unicode_mode=normalize_unicode_mode,
                    normalize_whitespace=normalize_whitespace,
                    normalize_bullets=normalize_bullets,
                    normalize_dates=normalize_dates,
                    strip_control_chars=strip_control_chars,
                    max_chars=max_chars,
                )
                normalized_group.append(normalized_record)
            results.append(normalized_group)
        return FunctionResult(results, {})

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        result = self._validate_input(input_data, attributes, properties)
        return type(result) is ValidationResult and result.ok is True

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        reason = "supply valid input attributes"
        if not super().validate(input_data, attributes, properties):
            return ValidationResult(False, reason)

        text_fields = attributes.get("text_field", [])
        unicode_mode = attributes.get("normalize_unicode", "NFKC")
        max_chars = attributes.get("max_chars")
        if not isinstance(text_fields, list) or not text_fields:
            return ValidationResult(False, reason)
        raw_text_fields = cast(list[object], text_fields)
        if any(not isinstance(field, str) or not field.strip() for field in raw_text_fields):
            return ValidationResult(False, reason)
        if unicode_mode not in {"NFC", "NFKC", "NFD", "NFKD"}:
            return ValidationResult(False, reason)
        try:
            valid = max_chars is None or max_chars >= 0
        except (TypeError, ValueError, AttributeError):
            # Lax attribute coercion can still produce values that cannot be compared
            # with an integer; validation reports them as invalid instead of raising.
            valid = False
        return ValidationResult(valid, None if valid else reason)


def _normalize_record_text(
    record: Record,
    text_fields: list[str],
    delimiter: str,
    strip_newline: bool,
    normalize_unicode_mode: str,
    normalize_whitespace: bool,
    normalize_bullets: bool,
    normalize_dates: bool,
    strip_control_chars: bool,
    max_chars: int | None,
) -> str:
    normalized_parts: list[str] = []
    for field in text_fields:
        field_value = record.get(field)
        if field_value is None:
            continue

        text = unicodedata.normalize(cast(_UnicodeForm, normalize_unicode_mode), str(field_value))
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if strip_control_chars:
            text = "".join(char for char in text if _keep_character(char, strip_newline))
        if normalize_bullets:
            text = _BULLET_LINE_PATTERN.sub(lambda match: f"{match.group(1)}- ", text)
        if normalize_dates:
            text = _normalize_dates(text)

        if strip_newline:
            text = text.replace("\n", " ")
            if normalize_whitespace:
                text = re.sub(r"\s+", " ", text)
            text = text.strip()
        else:
            lines = text.split("\n")
            if normalize_whitespace:
                lines = [re.sub(r"\s+", " ", line).strip() for line in lines]
            else:
                lines = [line.strip() for line in lines]
            text = "\n".join(lines)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
        normalized_parts.append(text)

    text = delimiter.join(normalized_parts)
    if max_chars is not None:
        text = text[:max_chars]
    return text


def _normalize_dates(text: str) -> str:
    normalized_parts: list[str] = []
    last_index = 0
    for match in _ISO_DATE_PATTERN.finditer(text):
        normalized_parts.append(text[last_index : match.start()])
        try:
            normalized_date = datetime(
                year=int(match.group("year")),
                month=int(match.group("month")),
                day=int(match.group("day")),
            )
            normalized_parts.append(normalized_date.strftime("%Y-%m-%d"))
        except ValueError:
            normalized_parts.append(match.group(0))
        last_index = match.end()
    normalized_parts.append(text[last_index:])
    text = "".join(normalized_parts)

    normalized_parts = []
    last_index = 0
    for match in _NUMERIC_DATE_PATTERN.finditer(text):
        normalized_parts.append(text[last_index : match.start()])
        first = int(match.group("first"))
        second = int(match.group("second"))
        replacement = match.group(0)
        day: int | None
        month: int | None
        if first > 12 and second <= 12:
            day, month = first, second
        elif second > 12 and first <= 12:
            month, day = first, second
        else:
            day, month = None, None

        if day is not None and month is not None:
            try:
                normalized_date = datetime(year=int(match.group("year")), month=month, day=day)
                replacement = normalized_date.strftime("%Y-%m-%d")
            except ValueError:
                replacement = match.group(0)
        normalized_parts.append(replacement)
        last_index = match.end()
    normalized_parts.append(text[last_index:])
    text = "".join(normalized_parts)

    for pattern, candidate_template, date_formats in _MONTH_NAME_DATE_PATTERNS:
        normalized_parts = []
        last_index = 0
        for match in pattern.finditer(text):
            normalized_parts.append(text[last_index : match.start()])
            month_name = match.group("month_name").rstrip(".")
            candidate = candidate_template.format(
                day=match.group("day"),
                month_name=month_name,
                year=match.group("year"),
            )
            replacement = match.group(0)
            for date_format in date_formats:
                try:
                    replacement = datetime.strptime(candidate, date_format).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue
            normalized_parts.append(replacement)
            last_index = match.end()
        normalized_parts.append(text[last_index:])
        text = "".join(normalized_parts)
    return text


def _keep_character(char: str, strip_newline: bool) -> bool:
    if char in {" ", "\t", "\n"}:
        return True
    return not unicodedata.category(char).startswith("C")


DISCOVERY = DiscoverySpec(
    when_to_invoke=(
        "Use when text needs canonical Unicode, whitespace, case, or recognized-date "
        "normalization before later text work."
    ),
    tags=(
        "domain-text",
        "flow-transform",
        "accepts-data",
        "produces-data",
        "capability-normalization",
    ),
)

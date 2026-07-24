from __future__ import annotations

import re
from typing import ClassVar, cast

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

_WORD_PATTERN = re.compile(r"\S+")


class SegmentTextOperator(Operator):
    """Split normalized text into stable segments with offsets."""

    name: ClassVar[str] = "segment_text"
    description: ClassVar[str] = (
        "Split normalized text into stable segments with offsets and flat metadata."
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "text_field": AttributeSpec(
            type="str",
            description="Field containing normalized text to segment",
            required=True,
        ),
        "split_strategy": AttributeSpec(
            type="str",
            description=("Segmentation strategy: sentence, paragraph, token, word, or heading"),
            default="sentence",
        ),
        "word_overlap": AttributeSpec(
            type="int",
            description="Approximate number of words to overlap between segments",
            default=0,
        ),
        "max_tokens": AttributeSpec(
            type="int",
            description="Approximate maximum token budget per segment",
            default=650,
        ),
        "min_chars": AttributeSpec(
            type="int",
            description="Minimum characters per segment when possible",
            default=20,
        ),
        "keep_delimiters": AttributeSpec(
            type="bool",
            description="Whether to retain delimiters in segment units",
            default=False,
        ),
        "meta_fields": AttributeSpec(
            type="list[str]",
            description="Record fields to copy into flat segment metadata keys",
            default=[],
        ),
        "segment_id_format": AttributeSpec(
            type="str",
            description=("Segment identifier template using doc_id and index placeholders"),
            default="{doc_id}::S{index:04d}",
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
        text_field = cast(str, attributes.get("text_field"))
        split_strategy = cast(str, attributes.get("split_strategy", "sentence"))
        word_overlap = cast(int, attributes.get("word_overlap", 0))
        max_tokens = cast(int, attributes.get("max_tokens", 650))
        min_chars = cast(int, attributes.get("min_chars", 20))
        keep_delimiters = cast(bool, attributes.get("keep_delimiters", False))
        meta_fields = cast(list[str], attributes.get("meta_fields", []))
        segment_id_format = cast(
            str,
            attributes.get("segment_id_format", "{doc_id}::S{index:04d}"),
        )

        results: DataBundle = []
        for group_index, data_group in enumerate(input_data):
            segmented_group: Data = []
            for record_index, record in enumerate(data_group):
                text = _stringify_text(record.get(text_field, ""))
                if not text.strip():
                    continue

                doc_id = _resolve_doc_id(
                    record,
                    text_field=text_field,
                    group_index=group_index,
                    record_index=record_index,
                )
                units = _split_units(text, split_strategy, keep_delimiters)
                spans = _assemble_segments(
                    text,
                    units,
                    split_strategy=split_strategy,
                    max_tokens=max_tokens,
                    min_chars=min_chars,
                    word_overlap=word_overlap,
                )
                for segment_index, (start_char, end_char) in enumerate(spans):
                    segment_record: Record = {
                        "segment_id": segment_id_format.format(
                            doc_id=doc_id,
                            index=segment_index,
                            field_name=text_field,
                            group_index=group_index,
                            record_index=record_index,
                        ),
                        "doc_id": doc_id,
                        "text": text[start_char:end_char],
                        "start_char": start_char,
                        "end_char": end_char,
                        "segment.split_strategy": split_strategy,
                    }
                    for meta_field in meta_fields:
                        if meta_field in record:
                            segment_record[f"segment.{meta_field}"] = record[meta_field]
                    segmented_group.append(segment_record)
            results.append(segmented_group)
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
        reason = "supply valid text segmentation options"
        if not super().validate(input_data, attributes, properties):
            return ValidationResult(False, reason)

        text_field = attributes.get("text_field")
        split_strategy = attributes.get("split_strategy", "sentence")
        word_overlap = attributes.get("word_overlap", 0)
        max_tokens = attributes.get("max_tokens", 650)
        min_chars = attributes.get("min_chars", 20)
        meta_fields = attributes.get("meta_fields", [])
        if not isinstance(text_field, str) or not text_field.strip():
            return ValidationResult(False, reason)
        if split_strategy not in {
            "sentence",
            "paragraph",
            "token",
            "word",
            "heading",
        }:
            return ValidationResult(False, reason)
        try:
            if word_overlap < 0 or max_tokens <= 0 or min_chars < 0:
                return ValidationResult(False, reason)
        except (TypeError, ValueError, AttributeError):
            # Lax attribute coercion can still produce values that cannot be compared
            # with an integer; validation reports them as invalid instead of raising.
            return ValidationResult(False, reason)
        if not isinstance(meta_fields, list):
            return ValidationResult(False, reason)
        raw_meta_fields = cast(list[object], meta_fields)
        valid = all(isinstance(field, str) and bool(field.strip()) for field in raw_meta_fields)
        return ValidationResult(valid, None if valid else reason)


def _split_units(text: str, split_strategy: str, keep_delimiters: bool) -> list[tuple[int, int]]:
    strategy = "word" if split_strategy == "token" else split_strategy
    if strategy == "paragraph":
        units = _paragraph_units(text)
    elif strategy == "word":
        units = [(match.start(), match.end()) for match in _WORD_PATTERN.finditer(text)]
    elif strategy == "heading":
        units = _heading_units(text)
    else:
        units = _sentence_units(text)

    if keep_delimiters and units:
        return [
            (start_char, units[index + 1][0]) if index + 1 < len(units) else (start_char, end_char)
            for index, (start_char, end_char) in enumerate(units)
        ]
    return units


def _paragraph_units(text: str) -> list[tuple[int, int]]:
    return [
        (match.start(), match.end())
        for match in re.finditer(r"\S(?:.*?\S)?(?=(?:\n\s*\n)|\Z)", text, flags=re.DOTALL)
    ]


def _sentence_units(text: str) -> list[tuple[int, int]]:
    units: list[tuple[int, int]] = []
    start_char: int | None = None
    for index, char in enumerate(text):
        if start_char is None and not char.isspace():
            start_char = index
        if start_char is None:
            continue

        next_char = text[index + 1] if index + 1 < len(text) else ""
        is_terminal = char in ".!?"
        paragraph_break = char == "\n" and next_char == "\n"
        end_of_text = index == len(text) - 1
        if (
            (is_terminal and (not next_char or next_char.isspace()))
            or paragraph_break
            or end_of_text
        ):
            end_char = index + 1
            candidate = text[start_char:end_char].strip()
            if candidate:
                selected = text[start_char:end_char]
                trimmed_start = start_char + (len(selected) - len(selected.lstrip()))
                trimmed_end = end_char - (len(selected) - len(selected.rstrip()))
                units.append((trimmed_start, trimmed_end))
            start_char = None
    return units or _paragraph_units(text)


def _heading_units(text: str) -> list[tuple[int, int]]:
    heading_starts = [
        match.start()
        for match in re.finditer(r".*(?:\n|$)", text)
        if _is_heading_line(match.group(0).rstrip("\n"))
    ]
    if not heading_starts:
        return _paragraph_units(text)

    heading_starts.append(len(text))
    units: list[tuple[int, int]] = []
    for index in range(len(heading_starts) - 1):
        start_char = heading_starts[index]
        end_char = heading_starts[index + 1]
        while end_char > start_char and text[end_char - 1].isspace():
            end_char -= 1
        if start_char < end_char:
            units.append((start_char, end_char))
    return units or _paragraph_units(text)


def _is_heading_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("#"):
        return True
    words = stripped.split()
    if len(words) > 8:
        return False
    if stripped.endswith(":"):
        return True
    if stripped.isupper():
        return True
    return stripped == stripped.title() and stripped[-1].isalnum()


def _assemble_segments(
    text: str,
    units: list[tuple[int, int]],
    split_strategy: str,
    max_tokens: int,
    min_chars: int,
    word_overlap: int,
) -> list[tuple[int, int]]:
    if not units:
        return []
    strategy = "word" if split_strategy == "token" else split_strategy
    if strategy in {"paragraph", "sentence", "heading"}:
        return _assemble_boundary_segments(
            text,
            units,
            max_tokens=max_tokens,
            min_chars=min_chars,
            word_overlap=word_overlap,
        )

    spans: list[tuple[int, int]] = []
    cursor = 0
    while cursor < len(units):
        start_index = cursor
        end_index = cursor
        while end_index < len(units):
            start_char = units[start_index][0]
            end_char = units[end_index][1]
            token_count = _count_words(text[start_char:end_char])
            if end_index > start_index and token_count > max_tokens:
                break
            if end_index == start_index and token_count > max_tokens:
                spans.extend(
                    _split_large_unit(
                        text,
                        units[end_index][0],
                        units[end_index][1],
                        max_tokens=max_tokens,
                        min_chars=min_chars,
                        word_overlap=word_overlap,
                    )
                )
                cursor = end_index + 1
                break
            end_index += 1
        else:
            end_index = len(units)

        if cursor != start_index:
            continue
        chosen_end_index = max(start_index, end_index - 1)
        segment_start = units[start_index][0]
        segment_end = units[chosen_end_index][1]
        while chosen_end_index + 1 < len(units) and segment_end - segment_start < min_chars:
            chosen_end_index += 1
            segment_end = units[chosen_end_index][1]
        spans.append((segment_start, segment_end))
        cursor = _next_cursor(
            text,
            units,
            start_index=start_index,
            end_index=chosen_end_index,
            word_overlap=word_overlap,
        )
    return _deduplicate_spans(spans)


def _assemble_boundary_segments(
    text: str,
    units: list[tuple[int, int]],
    max_tokens: int,
    min_chars: int,
    word_overlap: int,
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(units):
        start_char, end_char = units[index]
        if _count_words(text[start_char:end_char]) > max_tokens:
            spans.extend(
                _split_large_unit(
                    text,
                    start_char,
                    end_char,
                    max_tokens=max_tokens,
                    min_chars=min_chars,
                    word_overlap=word_overlap,
                )
            )
            index += 1
            continue

        current_start = start_char
        current_end = end_char
        while index + 1 < len(units) and current_end - current_start < min_chars:
            index += 1
            current_end = units[index][1]
        spans.append((current_start, current_end))
        index += 1
    return _deduplicate_spans(spans)


def _split_large_unit(
    text: str,
    start_char: int,
    end_char: int,
    max_tokens: int,
    min_chars: int,
    word_overlap: int,
) -> list[tuple[int, int]]:
    word_spans = [
        (match.start(), match.end()) for match in _WORD_PATTERN.finditer(text[start_char:end_char])
    ]
    if not word_spans:
        return [(start_char, min(end_char, start_char + max_tokens))]

    absolute_word_spans = [
        (start_char + word_start, start_char + word_end) for word_start, word_end in word_spans
    ]
    spans: list[tuple[int, int]] = []
    cursor = 0
    while cursor < len(absolute_word_spans):
        segment_start = absolute_word_spans[cursor][0]
        segment_end_index = min(cursor + max_tokens - 1, len(absolute_word_spans) - 1)
        segment_end = absolute_word_spans[segment_end_index][1]
        while (
            segment_end_index + 1 < len(absolute_word_spans)
            and segment_end - segment_start < min_chars
        ):
            segment_end_index += 1
            segment_end = absolute_word_spans[segment_end_index][1]
        spans.append((segment_start, segment_end))
        if segment_end_index == len(absolute_word_spans) - 1:
            break
        cursor = (
            max(cursor + 1, segment_end_index + 1 - word_overlap)
            if word_overlap > 0
            else segment_end_index + 1
        )
    return spans


def _next_cursor(
    text: str,
    units: list[tuple[int, int]],
    start_index: int,
    end_index: int,
    word_overlap: int,
) -> int:
    if word_overlap <= 0:
        return end_index + 1
    overlap_words = 0
    overlap_index = end_index + 1
    while overlap_index > start_index and overlap_words < word_overlap:
        overlap_index -= 1
        overlap_words += _count_words(text[units[overlap_index][0] : units[overlap_index][1]])
    return max(start_index + 1, overlap_index)


def _deduplicate_spans(
    spans: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    deduplicated: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for span in spans:
        if span[0] >= span[1] or span in seen:
            continue
        seen.add(span)
        deduplicated.append(span)
    return deduplicated


def _count_words(text: str) -> int:
    return len(_WORD_PATTERN.findall(text))


def _resolve_doc_id(
    record: Record,
    text_field: str,
    group_index: int,
    record_index: int,
) -> str:
    for field_name in ("doc_id", "id"):
        value = record.get(field_name)
        if value is not None and str(value).strip():
            return str(value)
    return f"table{group_index + 1}_row{record_index + 1}_{text_field}"


def _stringify_text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


DISCOVERY = DiscoverySpec(
    when_to_invoke=(
        "Use when normalized text must be split into stable segments with offsets and metadata."
    ),
    tags=(
        "domain-text",
        "flow-transform",
        "accepts-data",
        "produces-data",
        "capability-segmentation",
    ),
)

from __future__ import annotations

from typing import Any, ClassVar, cast

from blue_data_ops.operators._discovery import DiscoverySpec
from blue_data_ops.operators._record_matching import record_signature
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


class UnionOperator(Operator):
    """Combine data sources in order and remove signature-equal records."""

    name: ClassVar[str] = "union"
    description: ClassVar[str] = (
        "Given multiple input data sources, combine all records and remove exact duplicates"
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "match_option": AttributeSpec(
            type="str",
            description=(
                "Matching strategy for duplicate detection: 'key_match' (exact field names and "
                "values) or 'seq_match' (position-based comparison regardless of field names)"
            ),
            default="key_match",
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
        match_option = cast(str, attributes.get("match_option", "key_match"))
        if not input_data or len(input_data) < 1:
            return FunctionResult([], {})

        all_records: Data = []
        for data_source in input_data:
            if data_source:
                all_records.extend(data_source)
        return FunctionResult([_remove_duplicates(all_records, match_option)], {})

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
        valid = super().validate(input_data, attributes, properties) and attributes.get(
            "match_option", "key_match"
        ) in {"seq_match", "key_match"}
        return ValidationResult(
            valid,
            None if valid else "supply match_option as key_match or seq_match",
        )


def _remove_duplicates(records: Data, match_option: str) -> Data:
    if not records:
        return []

    seen_signatures: set[tuple[Any, ...]] = set()
    unique_records: list[Record] = []
    for record in records:
        signature = record_signature(record, match_option)
        if signature not in seen_signatures:
            seen_signatures.add(signature)
            unique_records.append(record)
    return unique_records


DISCOVERY = DiscoverySpec(
    when_to_invoke=(
        "Use when input groups must be combined and duplicate records removed under the "
        "configured match rule."
    ),
    tags=("domain-set", "flow-combine", "accepts-data", "produces-data", "capability-union"),
)

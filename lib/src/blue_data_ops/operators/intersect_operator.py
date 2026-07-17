from __future__ import annotations

from typing import Any, ClassVar, cast

from blue_data_ops.operators._record_matching import record_signature
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import Attributes, AttributeSpec, Data, DataBundle, Properties


class IntersectOperator(Operator):
    """Return first-source records whose signatures occur in every non-empty source."""

    name: ClassVar[str] = "intersect"
    description: ClassVar[str] = (
        "Given multiple input data sources, return only records that exist in all data sources"
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "match_option": AttributeSpec(
            type="str",
            description=(
                "Matching strategy for record comparison: 'key_match' (exact field names and "
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
        match_option = cast(str, attributes.get("match_option", "key_match"))
        if not input_data or len(input_data) < 2:
            return []

        non_empty_data = [data for data in input_data if data]
        if len(non_empty_data) < 2:
            return []
        return [_find_intersect_records(non_empty_data, match_option)]

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        if not super().validate(input_data, attributes, properties):
            return False
        return attributes.get("match_option", "key_match") in {"seq_match", "key_match"}


def _find_intersect_records(data_sources: DataBundle, match_option: str) -> Data:
    if not data_sources:
        return []

    base_data = data_sources[0]
    if len(data_sources) == 1:
        return base_data

    other_signature_sets: list[set[tuple[Any, ...]]] = []
    for data_source in data_sources[1:]:
        signature_set = {record_signature(record, match_option) for record in data_source}
        other_signature_sets.append(signature_set)

    intersect_records: Data = []
    for record in base_data:
        signature = record_signature(record, match_option)
        if all(signature in signature_set for signature_set in other_signature_sets):
            intersect_records.append(record)
    return intersect_records

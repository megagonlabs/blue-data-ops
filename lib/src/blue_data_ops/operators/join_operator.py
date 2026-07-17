from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, cast

from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    Data,
    DataBundle,
    Properties,
    Record,
)


@dataclass(frozen=True)
class _FieldMetadata:
    original_name: str
    data_source: int
    suffix: str
    is_join_key: bool
    join_key_index: int = -1
    is_original: bool = True


@dataclass
class _SchemaInfo:
    output_fields: dict[str, _FieldMetadata]
    field_provenance: dict[str, str]
    left_suffix: str
    right_suffix: str
    join_keys: list[str]
    suffixes: list[str]


_DataSource = Data | tuple[Data, _SchemaInfo]
_JoinKey = tuple[Any, ...]


class JoinOperator(Operator):
    """Join two or more data sources by corresponding key lists."""

    name: ClassVar[str] = "join"
    description: ClassVar[str] = (
        "Joins multiple JSON array data sources using N-way join operations"
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "join_on": AttributeSpec(
            type="list[list[str]]",
            description="List of join key lists for each data source",
            required=True,
        ),
        "join_type": AttributeSpec(
            type="str",
            description="Type of join: 'inner', 'left', 'right', 'outer'",
            default="inner",
        ),
        "join_suffix": AttributeSpec(
            type="list[str]",
            description="Suffixes for non-key fields",
            default=[],
        ),
        "keep_keys": AttributeSpec(
            type="str",
            description="'left' to keep left keys only, 'both' to keep both",
            default="left",
        ),
    }

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        join_on = cast(list[list[str]], attributes.get("join_on", []))
        join_type = cast(str, attributes.get("join_type", "inner"))
        join_suffix = cast(list[str], attributes.get("join_suffix", []))
        keep_keys = cast(str, attributes.get("keep_keys", "left"))

        if not input_data or len(input_data) < 2:
            return []
        if len(join_on) != len(input_data):
            return []
        if not join_suffix:
            join_suffix = [f"_ds{index}" for index in range(len(input_data))]
        if len(join_suffix) != len(input_data):
            return []
        if len(join_suffix) != len(set(join_suffix)):
            return []

        data_sources: list[_DataSource] = [data_source for data_source in input_data]
        result, _schema = _perform_n_way_join(
            data_sources, join_on, join_type, join_suffix, keep_keys
        )
        return [result]

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        if not super().validate(input_data, attributes, properties):
            return False

        join_on_value = attributes.get("join_on", [])
        join_suffix_value = attributes.get("join_suffix", [])
        if not isinstance(join_on_value, list):
            return False
        join_on = cast(list[Any], join_on_value)
        if len(join_on) < 2:
            return False
        for field_list_value in join_on:
            if not isinstance(field_list_value, list) or not field_list_value:
                return False
            field_list = cast(list[Any], field_list_value)
            if any(not isinstance(field_name, str) for field_name in field_list):
                return False

        if join_suffix_value:
            if not isinstance(join_suffix_value, list):
                return False
            join_suffix = cast(list[Any], join_suffix_value)
            if len(join_suffix) != len(join_on):
                return False
        if attributes.get("keep_keys", "left") not in {"left", "both"}:
            return False
        return attributes.get("join_type", "inner") in {"inner", "left", "right", "outer"}


def _perform_n_way_join(
    data_sources: list[_DataSource],
    join_fields: list[list[str]],
    join_type: str,
    suffixes: list[str],
    keep_keys: str,
) -> tuple[Data, _SchemaInfo]:
    if len(data_sources) < 2:
        return [], _SchemaInfo({}, {}, "", "", [], [])
    if len(data_sources) == 2:
        return _perform_two_way_join(
            data_sources[0],
            data_sources[1],
            join_fields[0],
            join_fields[1],
            join_type,
            suffixes[0],
            suffixes[1],
            keep_keys,
        )

    intermediate_result, intermediate_schema = _perform_two_way_join(
        data_sources[0],
        data_sources[1],
        join_fields[0],
        join_fields[1],
        join_type,
        suffixes[0],
        suffixes[1],
        keep_keys,
    )
    if not intermediate_result:
        return [], _SchemaInfo({}, {}, "", "", [], [])

    remaining_data_sources: list[_DataSource] = [
        (intermediate_result, intermediate_schema),
        *data_sources[2:],
    ]
    remaining_join_fields = [intermediate_schema.join_keys, *join_fields[2:]]
    # The intermediate schema supplies the real suffix, so this placeholder is never emitted.
    remaining_suffixes = ["_intermediate", *suffixes[2:]]
    return _perform_n_way_join(
        remaining_data_sources,
        remaining_join_fields,
        join_type,
        remaining_suffixes,
        keep_keys,
    )


def _perform_two_way_join(
    left_data: _DataSource,
    right_data: _DataSource,
    left_fields: list[str],
    right_fields: list[str],
    join_type: str,
    left_suffix: str,
    right_suffix: str,
    keep_keys: str,
) -> tuple[Data, _SchemaInfo]:
    left_records, left_suffix, left_provenance = _normalize_data_source(left_data, left_suffix)
    right_records, right_suffix, right_provenance = _normalize_data_source(right_data, right_suffix)
    schema_info = _determine_output_schema(
        left_records,
        right_records,
        left_fields,
        right_fields,
        left_suffix,
        right_suffix,
        keep_keys,
        left_provenance,
        right_provenance,
    )

    right_index: dict[_JoinKey, Data] = {}
    for record in right_records:
        key = _get_join_key(record, right_fields)
        right_index.setdefault(key, []).append(record)

    if join_type == "inner":
        result = _inner_join(left_records, left_fields, right_index, schema_info)
    elif join_type == "left":
        result = _left_join(left_records, left_fields, right_index, schema_info)
    elif join_type == "right":
        result = _right_join(
            left_records,
            right_records,
            left_fields,
            right_fields,
            right_index,
            schema_info,
        )
    elif join_type == "outer":
        result = _outer_join(
            left_records,
            right_records,
            left_fields,
            right_fields,
            right_index,
            schema_info,
        )
    else:
        result = []

    schema_info.join_keys = _determine_join_keys(schema_info, left_fields)
    schema_info.suffixes = [left_suffix, right_suffix]
    return result, schema_info


def _normalize_data_source(
    data_source: _DataSource, fallback_suffix: str
) -> tuple[Data, str, dict[str, str]]:
    if isinstance(data_source, tuple):
        records, schema = data_source
        suffix = schema.suffixes[0] if schema.suffixes else fallback_suffix
        return records, suffix, schema.field_provenance
    return data_source, fallback_suffix, {}


def _determine_output_schema(
    left_data: Data,
    right_data: Data,
    left_fields: list[str],
    right_fields: list[str],
    left_suffix: str,
    right_suffix: str,
    keep_keys: str,
    left_provenance: dict[str, str],
    right_provenance: dict[str, str],
) -> _SchemaInfo:
    left_all_fields = {field_name for record in left_data for field_name in record}
    right_all_fields = {field_name for record in right_data for field_name in record}
    if keep_keys == "both":
        field_conflicts = left_all_fields & right_all_fields
    else:
        field_conflicts = (left_all_fields & right_all_fields) - set(right_fields)

    output_fields: dict[str, _FieldMetadata] = {}
    field_provenance: dict[str, str] = {}
    join_key_map: list[str] = []

    for field_name in left_all_fields:
        is_join_key = field_name in left_fields
        output_name, is_original = _output_field_name(
            field_name, field_conflicts, left_suffix, left_provenance
        )
        output_fields[output_name] = _FieldMetadata(
            original_name=field_name,
            data_source=0,
            suffix=left_suffix,
            is_join_key=is_join_key,
            join_key_index=left_fields.index(field_name) if is_join_key else -1,
            is_original=is_original,
        )
        field_provenance[output_name] = left_provenance.get(field_name, left_suffix)
        if is_join_key:
            join_key_map.append(output_name)

    for field_name in right_all_fields:
        is_join_key = field_name in right_fields
        if is_join_key and keep_keys != "both":
            continue
        output_name, is_original = _output_field_name(
            field_name, field_conflicts, right_suffix, right_provenance
        )
        output_fields[output_name] = _FieldMetadata(
            original_name=field_name,
            data_source=1,
            suffix=right_suffix,
            is_join_key=is_join_key,
            join_key_index=right_fields.index(field_name) if is_join_key else -1,
            is_original=is_original,
        )
        field_provenance[output_name] = right_provenance.get(field_name, right_suffix)

    return _SchemaInfo(
        output_fields,
        field_provenance,
        left_suffix,
        right_suffix,
        join_key_map,
        [],
    )


def _output_field_name(
    field_name: str,
    conflicts: set[str],
    suffix: str,
    provenance: dict[str, str],
) -> tuple[str, bool]:
    if field_name not in conflicts:
        return field_name, True
    return f"{field_name}{provenance.get(field_name, suffix)}", False


def _get_join_key(record: Record, fields: list[str]) -> _JoinKey:
    return tuple(record.get(field_name) for field_name in fields)


def _merge_records(left: Record, right: Record, schema_info: _SchemaInfo) -> Record:
    merged: Record = {}
    for output_field, metadata in schema_info.output_fields.items():
        source = left if metadata.data_source == 0 else right
        merged[output_field] = source.get(metadata.original_name)
    return merged


def _inner_join(
    left_data: Data,
    left_on: list[str],
    right_index: dict[_JoinKey, Data],
    schema_info: _SchemaInfo,
) -> Data:
    result: Data = []
    for left_record in left_data:
        key = _get_join_key(left_record, left_on)
        for right_record in right_index.get(key, []):
            result.append(_merge_records(left_record, right_record, schema_info))
    return result


def _left_join(
    left_data: Data,
    left_on: list[str],
    right_index: dict[_JoinKey, Data],
    schema_info: _SchemaInfo,
) -> Data:
    result: Data = []
    for left_record in left_data:
        key = _get_join_key(left_record, left_on)
        matching_records = right_index.get(key)
        if matching_records is None:
            result.append(_merge_records(left_record, {}, schema_info))
        else:
            for right_record in matching_records:
                result.append(_merge_records(left_record, right_record, schema_info))
    return result


def _right_join(
    left_data: Data,
    right_data: Data,
    left_on: list[str],
    right_on: list[str],
    right_index: dict[_JoinKey, Data],
    schema_info: _SchemaInfo,
) -> Data:
    result: Data = []
    matched: set[_JoinKey] = set()
    for left_record in left_data:
        key = _get_join_key(left_record, left_on)
        if key in right_index:
            matched.add(key)
            for right_record in right_index[key]:
                result.append(_merge_records(left_record, right_record, schema_info))
    for right_record in right_data:
        if _get_join_key(right_record, right_on) not in matched:
            result.append(_merge_records({}, right_record, schema_info))
    return result


def _outer_join(
    left_data: Data,
    right_data: Data,
    left_on: list[str],
    right_on: list[str],
    right_index: dict[_JoinKey, Data],
    schema_info: _SchemaInfo,
) -> Data:
    result: Data = []
    matched_left: set[_JoinKey] = set()
    matched_right: set[_JoinKey] = set()
    for left_record in left_data:
        key = _get_join_key(left_record, left_on)
        if key in right_index:
            matched_left.add(key)
            matched_right.add(key)
            for right_record in right_index[key]:
                result.append(_merge_records(left_record, right_record, schema_info))
    for left_record in left_data:
        if _get_join_key(left_record, left_on) not in matched_left:
            result.append(_merge_records(left_record, {}, schema_info))
    for right_record in right_data:
        if _get_join_key(right_record, right_on) not in matched_right:
            result.append(_merge_records({}, right_record, schema_info))
    return result


def _determine_join_keys(schema_info: _SchemaInfo, left_fields: list[str]) -> list[str]:
    join_keys: list[str] = []
    for left_key in left_fields:
        for output_field, metadata in schema_info.output_fields.items():
            if metadata.original_name == left_key and metadata.is_join_key:
                join_keys.append(output_field)
                break
        else:
            join_keys.append(left_key)
    return join_keys

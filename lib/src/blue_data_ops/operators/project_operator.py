from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, ClassVar, cast

from pydantic import TypeAdapter, ValidationError

from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    Data,
    DataBundle,
    Properties,
    Record,
)

# Keep local adapters for the operator-specific nested-value checks even though the
# base currently recognizes the same composite type strings.
_KEPT_KEYS_ADAPTER: TypeAdapter[list[str]] = TypeAdapter(list[str])
_KEY_MAPPING_ADAPTER: TypeAdapter[dict[str, str]] = TypeAdapter(dict[str, str])


class ProjectOperator(Operator):
    """Keep selected record keys and optionally rename them."""

    name: ClassVar[str] = "project"
    description: ClassVar[str] = (
        "Given an input data, return only a set of attributes for each data element (key-wise)"
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "kept_keys": AttributeSpec(
            type="list[str]",
            description="List of keys to keep in each record",
            required=True,
        ),
        "key_mapping": AttributeSpec(
            type="dict[str, str]",
            description="Dictionary mapping old key names to new key names",
            default={},
        ),
    }

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        kept_keys = cast(Iterable[Any], attributes.get("kept_keys", []))
        key_mapping = cast(Mapping[Any, Any], attributes.get("key_mapping", {}))

        if not input_data or not input_data[0]:
            return []
        if not kept_keys:
            return []

        result: Data = []
        for record in input_data[0]:
            projected_record: Record = {}
            for key in kept_keys:
                if key in record:
                    output_key = key_mapping.get(key, key)
                    projected_record[output_key] = record[key]
            result.append(projected_record)
        return [result]

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        if not super().validate(input_data, attributes, properties):
            return False

        kept_keys = attributes.get("kept_keys")
        key_mapping = attributes.get("key_mapping", {})
        if not _is_string_sequence(kept_keys) or not _is_string_mapping(key_mapping):
            return False

        kept_keys_iterable = cast(Iterable[Any], kept_keys)
        key_mapping_values = cast(Mapping[Any, Any], key_mapping)
        for mapped_key in key_mapping_values:
            if mapped_key not in kept_keys_iterable:
                return False

        try:
            _validate_key_mapping_conflicts(kept_keys_iterable, key_mapping_values)
        except ValueError:
            return False
        return True


def _is_string_sequence(value: Any) -> bool:
    try:
        _KEPT_KEYS_ADAPTER.validate_python(value)
    except (ValidationError, TypeError, ValueError, AttributeError):
        return False
    return True


def _is_string_mapping(value: Any) -> bool:
    try:
        _KEY_MAPPING_ADAPTER.validate_python(value)
    except (ValidationError, TypeError, ValueError, AttributeError):
        return False
    return True


def _validate_key_mapping_conflicts(
    kept_keys: Iterable[Any], key_mapping: Mapping[Any, Any]
) -> None:
    if not key_mapping:
        return
    output_keys: set[Any] = set()
    for key in kept_keys:
        output_key = key_mapping.get(key, key)
        if output_key in output_keys:
            raise ValueError(
                f"Key mapping conflict: output key '{output_key}' appears multiple times"
            )
        output_keys.add(output_key)

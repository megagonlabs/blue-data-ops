from __future__ import annotations

from typing import Any, cast

from blue_data_ops.operators.types import Record


def record_signature(record: Record, match_option: str) -> tuple[Any, ...]:
    if match_option == "key_match":
        return tuple(sorted((key, _make_hashable(value)) for key, value in record.items()))
    if match_option == "seq_match":
        return tuple(_make_hashable(record[key]) for key in record)
    raise ValueError(f"Invalid match_option: {match_option}")


def _make_hashable(value: Any) -> Any:
    try:
        if isinstance(value, (int, float, bool)):
            normalized_value = float(value)
            if normalized_value != normalized_value:
                return ("__NaN__",)
            return normalized_value
        if isinstance(value, dict):
            mapping_value = cast(dict[Any, Any], value)
            return tuple(sorted((key, _make_hashable(item)) for key, item in mapping_value.items()))
        if isinstance(value, list):
            sequence_value = cast(list[Any], value)
            return tuple(_make_hashable(item) for item in sequence_value)
        if isinstance(value, set):
            set_value = cast(set[Any], value)
            return tuple(sorted(_make_hashable(item) for item in set_value))
        if hasattr(value, "__hash__") and value.__hash__ is not None:
            hash(value)
            return value
        return str(cast(object, value))
    except (TypeError, RecursionError):
        return str(cast(object, value))

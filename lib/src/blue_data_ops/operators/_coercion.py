from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter, ValidationError

_FLAG: TypeAdapter[bool] = TypeAdapter(bool)


def coerce_numeric(value: Any) -> int | float | None:
    """Coerce a value with integer-first, then floating-point conversion."""
    # Existing int/float values, including bool, pass through. Other values try int()
    # before float(), so bytes can coerce and Decimal values truncate through int().
    # Only conversion failures are suppressed; unrelated exceptions propagate.
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return int(value)
    except (ValueError, TypeError):
        try:
            return float(value)
        except (ValueError, TypeError):
            return None


def coerce_flag(value: Any, default: bool) -> bool | None:
    """Read a ``bool`` attribute as attribute validation reads it.

    None gives *default*; a value validation would refuse gives None.
    """
    # Validation accepts strings such as "false" and "0" but leaves them in the attributes,
    # and Python reads any non-empty string as true.
    if value is None:
        return default
    try:
        return _FLAG.validate_python(value)
    except ValidationError:
        return None

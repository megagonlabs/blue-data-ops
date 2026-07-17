from __future__ import annotations

from typing import Any


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

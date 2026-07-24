"""Blue-compatible UUID and canonical-id helpers.

The id separator is Blue's ``Separator.ID`` (``":"``), inlined to avoid importing
``blue.constant``.
"""

from __future__ import annotations

import uuid

__all__ = [
    "concat_ids",
    "create_uuid",
    "extract_name_id",
    "extract_prefix",
    "extract_sid",
    "split_ids",
]

# Blue's Separator.ID; inlined to avoid a blue.constant dependency.
_ID_SEPARATOR = ":"


def create_uuid() -> str:
    """Create a short lowercase-hex unique identifier (Blue)."""
    return str(hex(uuid.uuid4().fields[0]))[2:]


def split_ids(canonical_id: str) -> list[str]:
    """Split a canonical id into its components (Blue)."""
    return canonical_id.split(_ID_SEPARATOR)


def extract_sid(canonical_id: str) -> str:
    """Join the trailing name/id pair into a short id (Blue)."""
    return _ID_SEPARATOR.join(extract_name_id(canonical_id))


def extract_name_id(canonical_id: str) -> list[str]:
    """Return the trailing (name, id) components of a canonical id (Blue)."""
    return split_ids(canonical_id)[-2:]


def extract_prefix(canonical_id: str) -> str | None:
    """Return the prefix before the trailing name/id pair, or ``None`` (Blue)."""
    splits = split_ids(canonical_id)
    if len(splits) > 2:
        return _ID_SEPARATOR.join(splits[:-2])
    return None


def concat_ids(*ids: str) -> str:
    """Concatenate id components with the canonical separator (Blue)."""
    return _ID_SEPARATOR.join(ids)

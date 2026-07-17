from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# A record is a JSON-like object, data is a list of records, and every operator
# consumes and produces a list of data groups (`list[list[dict]]`).
Record = dict[str, Any]
Data = list[Record]
DataBundle = list[Data]

Attributes = dict[str, Any]
Properties = dict[str, Any]


@dataclass(frozen=True)
class AttributeSpec:
    """Declarative specification of a single operator attribute."""

    type: str
    description: str = ""
    required: bool = False
    default: Any = None


class OperatorError(Exception):
    """Base class for all blue-data-ops operator errors."""


class OperatorValidationError(OperatorError):
    """Raised when operator attribute validation fails as a system error."""

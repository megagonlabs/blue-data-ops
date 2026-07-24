from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, NamedTuple

# A record is a JSON-like object, data is a list of records, and every operator
# consumes and produces a list of data groups (`list[list[dict]]`).
Record = dict[str, Any]
Data = list[Record]
DataBundle = list[Data]

Attributes = dict[str, Any]
Properties = dict[str, Any]

ABSENT = object()


class ErrorCategory(str, Enum):
    RECOVERABLE = "RECOVERABLE"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class ErrorStage(str, Enum):
    DEFAULTS = "DEFAULTS"
    VALIDATE = "VALIDATE"
    EXECUTE = "EXECUTE"
    NORMALIZE = "NORMALIZE"
    REFINE = "REFINE"


class ErrorCode(str, Enum):
    DEFAULTS_FAILED = "DEFAULTS_FAILED"
    INVALID_INPUT = "INVALID_INPUT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    VALIDATION_RESULT_INVALID = "VALIDATION_RESULT_INVALID"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EXECUTION_RESULT_INVALID = "EXECUTION_RESULT_INVALID"
    REFINEMENT_FAILED = "REFINEMENT_FAILED"
    REFINEMENT_RESULT_INVALID = "REFINEMENT_RESULT_INVALID"
    OPERATOR_TIMEOUT = "OPERATOR_TIMEOUT"


class FunctionResult(NamedTuple):
    output_data: DataBundle
    output_attributes: Attributes


class ValidationResult(NamedTuple):
    ok: bool
    reason: str | None


class ErrorRecord(NamedTuple):
    category: ErrorCategory
    code: ErrorCode
    operator_id: str
    stage: ErrorStage
    message: str
    retryable: bool
    suggestion: str | None


class ExecMeta(NamedTuple):
    is_empty: bool
    errors: list[ErrorRecord]
    logs: list[str]
    traces: dict[str, Any]


@dataclass(frozen=True, init=False)
class AttributeSpec:
    """Declarative specification of a single operator attribute."""

    type: str
    description: str = ""
    required: bool = False
    default: Any = None
    has_default: bool = False
    materialize_default: bool = field(default=True, compare=False, repr=False)

    def __init__(
        self,
        type: str,
        description: str = "",
        required: bool = False,
        default: Any = ABSENT,
        materialize_default: bool = True,
    ) -> None:
        object.__setattr__(self, "type", type)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "required", required)
        object.__setattr__(self, "default", None if default is ABSENT else default)
        object.__setattr__(self, "has_default", default is not ABSENT)
        object.__setattr__(self, "materialize_default", materialize_default)


class OperatorError(Exception):
    """Base class for all blue-data-ops operator errors."""


class OperatorValidationError(OperatorError):
    """Raised when operator attribute validation fails as a system error."""

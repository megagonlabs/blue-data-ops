from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, NamedTuple, cast

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


def _public_text(value: object) -> bool:
    return type(value) is str and bool(value.strip()) and len(value) <= 512 and value.isprintable()


def _valid_execution_carrier(value: object) -> bool:
    if type(value) is not tuple:
        return False
    carrier = cast(tuple[object, ...], value)
    return (
        len(carrier) == 3
        and _public_text(carrier[0])
        and (carrier[1] is None or _public_text(carrier[1]))
        and type(carrier[2]) is bool
    )


class OperatorExecutionError(OperatorError):
    """Publish trusted author-selected diagnostic constants from a canonical body."""

    __slots__ = ("__carrier",)

    def __init__(
        self, message: str, *, suggestion: str | None = None, retryable: bool = False
    ) -> None:
        carrier = (message, suggestion, retryable)
        if not _valid_execution_carrier(carrier):
            raise ValueError("invalid public execution diagnostic")
        _EXECUTION_CARRIER.__set__(self, carrier)
        OperatorError.__init__(self, message)


_EXECUTION_CARRIER = OperatorExecutionError.__dict__["_OperatorExecutionError__carrier"]


def execution_diagnostic(error: BaseException) -> tuple[str, str | None, bool] | None:
    if not isinstance(error, OperatorExecutionError):
        return None
    try:
        carrier: object = _EXECUTION_CARRIER.__get__(error, OperatorExecutionError)
    except Exception:
        return None
    return (
        cast(tuple[str, str | None, bool], carrier) if _valid_execution_carrier(carrier) else None
    )

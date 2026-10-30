from __future__ import annotations

import json
from typing import Any, Literal, Never


class LLMError(Exception):
    """Raised for LLM transport failures and rejected adapter configuration."""

    # Wrapping boundary: transport/provider exceptions and malformed responses are
    # wrapped here by the client; templating errors (substitution TypeError, JSONPath
    # misses) remain raw because they occur before the provider boundary.

    def __init__(
        self,
        message: str,
        code: str | None = None,
        provider_error: Any | None = None,
        *,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.provider_error = provider_error
        self.retryable = retryable


_REPLY_MESSAGE = "model reply did not match the operator's output format"


class _ReplyJSONError(json.JSONDecodeError):
    def __init__(self) -> None:
        super().__init__(_REPLY_MESSAGE, "", 0)


class _ReplyValueError(ValueError):
    def __init__(self) -> None:
        super().__init__(_REPLY_MESSAGE)


class _ReplyTypeError(TypeError):
    def __init__(self) -> None:
        super().__init__(_REPLY_MESSAGE)


_REPLY_ERRORS = (_ReplyJSONError, _ReplyValueError, _ReplyTypeError)


def is_reply_failure(error: BaseException) -> bool:
    return isinstance(error, _REPLY_ERRORS)


def raise_reply_failure(kind: Literal["json", "value", "type"] = "value") -> Never:
    error = {"json": _ReplyJSONError, "value": _ReplyValueError, "type": _ReplyTypeError}[kind]()
    try:
        raise error
    except _REPLY_ERRORS:
        # Clear an ambient handler's chain too; `from None` only hides its display.
        error.__context__ = None
        error.__cause__ = None
        raise


class _SQLSchemaFailure(LLMError):
    def __init__(self) -> None:
        super().__init__(
            "generated SQL failed against the approved schema",
            code="sql_execution_failed",
            retryable=False,
        )


def is_sql_schema_failure(error: BaseException) -> bool:
    return isinstance(error, _SQLSchemaFailure)


def sql_schema_failure() -> LLMError:
    return _SQLSchemaFailure()

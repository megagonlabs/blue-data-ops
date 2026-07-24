"""Boundary doubles and assertions for whole-catalog outcome tests.

The doubles replace the LLM client, data registry, returned SQL source, and plan-id
generator. Operator bodies and refiners remain active.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from blue_data_ops import ErrorCategory, ErrorCode, ErrorRecord, ErrorStage, ExecMeta
from blue_data_ops.data import RegistrySeam
from blue_data_ops.llm import LLMClient
from blue_data_ops.operators.types import Attributes, DataBundle, Properties
from tests.doubles.data import RegistrySeamDouble, SQLSourceDouble

__all__ = [
    "ScriptedClient",
    "RecordingSeam",
    "SQLSourceDouble",
    "id_sequence",
    "data_registry_properties",
    "llm_properties",
    "first_error",
    "assert_success",
    "assert_successful_empty",
    "assert_recoverable_invalid",
    "assert_contained_failure",
    "assert_timeout",
]


class ScriptedClient(LLMClient):
    """Deterministic LLM double: pops queued responses; raises a queued exception; records calls.

    An exhausted queue raises ``AssertionError`` so a test that expects one provider call cannot
        silently make a second. This matches the other family suites' ``ScriptedClient``.
    """

    def __init__(self, responses: Sequence[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[Any, dict[str, Any] | None, dict[str, Any] | None]] = []

    def execute_api_call(
        self,
        input: Any,  # noqa: A002 — mirrors the LLMClient surface
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append((input, properties, additional_data))
        if not self.responses:
            raise AssertionError("provider response queue exhausted")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class RecordingSeam(RegistrySeamDouble, RegistrySeam):
    """Call-recording data-registry seam that also satisfies the ``RegistrySeam`` ABC."""


def id_sequence(prefix: str = "test_plan") -> Callable[[], str]:
    """Return a deterministic replacement for ``pipeline._new_id`` (patched per test)."""
    current = 0

    def next_id() -> str:
        nonlocal current
        current += 1
        return f"{prefix}-{current:04d}"

    return next_id


def data_registry_properties(seam: RegistrySeam, **extra: Any) -> Properties:
    """Inject the data-registry seam the way the operator body resolves it."""
    return {"data_registry": seam, **extra}


def llm_properties(client: LLMClient, seam: RegistrySeam | None = None, **extra: Any) -> Properties:
    """Inject the LLM client (and optional data-registry seam) via ``properties``."""
    result: Properties = {"llm_client": client, **extra}
    if seam is not None:
        result["data_registry"] = seam
    return result


def first_error(meta: ExecMeta) -> ErrorRecord:
    """Return the single error on a contained outcome (asserts exactly one)."""
    assert len(meta.errors) == 1, f"expected exactly one error, got {meta.errors}"
    return meta.errors[0]


def assert_success(
    result: tuple[DataBundle, Attributes, ExecMeta],
    operator_id: str,
) -> tuple[DataBundle, Attributes, ExecMeta]:
    """A successful ``run()``: no error and not empty; a fresh output_attributes dict."""
    output_data, output_attributes, meta = result
    assert meta.errors == [], f"unexpected errors: {meta.errors}"
    assert meta.is_empty is False
    assert isinstance(output_attributes, dict)
    return output_data, output_attributes, meta


def assert_successful_empty(result: tuple[DataBundle, Attributes, ExecMeta]) -> None:
    """A successful-empty ``run()``: canonical ``[[]]``, ``is_empty=True``, no error."""
    output_data, _, meta = result
    assert output_data == [[]]
    assert meta.is_empty is True
    assert meta.errors == []


def _assert_no_private_leak(error: ErrorRecord) -> None:
    assert "private" not in error.message, f"private payload leaked: {error.message!r}"


def assert_recoverable_invalid(meta: ExecMeta, operator_id: str) -> ErrorRecord:
    """Recoverable invalid input: ``RECOVERABLE / INVALID_INPUT / VALIDATE`` with a suggestion."""
    error = first_error(meta)
    assert error.category is ErrorCategory.RECOVERABLE
    assert error.code is ErrorCode.INVALID_INPUT
    assert error.stage is ErrorStage.VALIDATE
    assert error.operator_id == operator_id
    assert error.retryable is False
    assert isinstance(error.suggestion, str) and error.suggestion
    _assert_no_private_leak(error)
    return error


def assert_contained_failure(
    meta: ExecMeta,
    operator_id: str,
    code: ErrorCode,
    stage: ErrorStage,
) -> ErrorRecord:
    """A contained failure: category ``FAILED``, exact code/stage, no leak, not retryable."""
    error = first_error(meta)
    assert error.category is ErrorCategory.FAILED
    assert error.code is code
    assert error.stage is stage
    assert error.operator_id == operator_id
    assert error.retryable is False
    _assert_no_private_leak(error)
    return error


def assert_timeout(meta: ExecMeta, operator_id: str, stage: ErrorStage) -> ErrorRecord:
    """A timeout: ``TIMEOUT / OPERATOR_TIMEOUT`` at the given stage, not retryable."""
    error = first_error(meta)
    assert error.category is ErrorCategory.TIMEOUT
    assert error.code is ErrorCode.OPERATOR_TIMEOUT
    assert error.stage is stage
    assert error.operator_id == operator_id
    assert error.retryable is False
    return error

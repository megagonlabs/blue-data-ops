from __future__ import annotations

from typing import Any, cast

from blue_data_ops.operators.types import (
    Attributes,
    DataBundle,
    ErrorCategory,
    ErrorCode,
    ErrorRecord,
    ErrorStage,
    ExecMeta,
    Properties,
)


def execution_failed(operator_id: str) -> ExecMeta:
    return ExecMeta(
        is_empty=False,
        errors=[
            ErrorRecord(
                category=ErrorCategory.FAILED,
                code=ErrorCode.EXECUTION_FAILED,
                operator_id=operator_id,
                stage=ErrorStage.EXECUTE,
                message="operator execution failed",
                retryable=False,
                suggestion=None,
            )
        ],
        logs=[],
        traces={},
    )


def run_body(
    operator: Any,
    input_data: DataBundle,
    attributes: Attributes,
    properties: Properties | None,
) -> tuple[DataBundle, Attributes, ExecMeta]:
    operator_id: str = operator.operator_id
    try:
        return cast(
            tuple[DataBundle, Attributes, ExecMeta],
            operator.run(input_data, attributes, properties),
        )
    except Exception:
        return [[]], {}, execution_failed(operator_id)

from __future__ import annotations

from math import isfinite
from time import monotonic

from blue_data_ops.operators.operator import (
    Operator,
    _is_data_bundle,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.types import (
    Attributes,
    DataBundle,
    ExecMeta,
    Properties,
    ValidationResult,
)


def _bundle_shape(value: DataBundle) -> dict[str, int | list[int]] | None:
    try:
        if not _is_data_bundle(value):
            return None
        return {
            "groups": len(value),
            "rows_per_group": [len(group) for group in value],
        }
    except Exception:
        return None


class _OutcomeOperator(Operator):  # pyright: ignore[reportUnusedClass]
    def run(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> tuple[DataBundle, Attributes, ExecMeta]:
        try:
            started = monotonic()
        except Exception:
            started = None
        try:
            input_shape = _bundle_shape(input_data)
        except Exception:
            input_shape = None
        result = super().run(input_data, attributes, properties)
        try:
            if started is not None:
                elapsed_ms = (monotonic() - started) * 1000
                if isfinite(elapsed_ms) and elapsed_ms >= 0:
                    # Attach after run() returns, outside any timed-out worker.
                    result[2].traces["elapsed_ms"] = elapsed_ms
        except Exception:
            pass
        try:
            if input_shape is not None:
                result[2].traces["input_shape"] = input_shape
        except Exception:
            pass
        try:
            if not result[2].errors:
                output_shape = _bundle_shape(result[0])
                if output_shape is not None:
                    result[2].traces["output_shape"] = output_shape
        except Exception:
            pass
        return result

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        if not _is_data_bundle(input_data):
            return ValidationResult(False, "supply a list of record groups")
        return super()._validate_input(input_data, attributes, properties)

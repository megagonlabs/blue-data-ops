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
        result = super().run(input_data, attributes, properties)
        try:
            if started is not None:
                elapsed_ms = (monotonic() - started) * 1000
                if isfinite(elapsed_ms) and elapsed_ms >= 0:
                    # Attach after run() returns, outside any timed-out worker.
                    result[2].traces["elapsed_ms"] = elapsed_ms
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

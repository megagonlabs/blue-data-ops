from __future__ import annotations

from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.join_operator import JoinOperator
from blue_data_ops.operators.types import Attributes, DataBundle, Properties, ValidationResult


class JoinOutcomeOperator(_OutcomeOperator, JoinOperator):
    """Reject inconsistent group, key, or suffix settings before joining."""

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        validation = super()._validate_input(input_data, attributes, properties)
        if not validation.ok:
            return validation
        if len(input_data) < 2 or len(attributes["join_on"]) != len(input_data):
            return ValidationResult(False, "supply at least two groups and one key list per group")
        suffixes = attributes.get("join_suffix", [])
        if suffixes and (
            any(not suffix for suffix in suffixes) or len(set(suffixes)) != len(suffixes)
        ):
            return ValidationResult(False, "supply distinct nonempty suffixes or use an empty list")
        return ValidationResult(True, None)

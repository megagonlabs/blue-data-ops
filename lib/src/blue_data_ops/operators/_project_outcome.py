from __future__ import annotations

from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.project_operator import ProjectOperator
from blue_data_ops.operators.types import Attributes, DataBundle, Properties, ValidationResult


class ProjectOutcomeOperator(_OutcomeOperator, ProjectOperator):
    """Reject an empty key list while preserving projection behavior."""

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        validation = super()._validate_input(input_data, attributes, properties)
        if not validation.ok:
            return validation
        if not attributes["kept_keys"]:
            return ValidationResult(False, "supply at least one kept key")
        return ValidationResult(True, None)

from __future__ import annotations

from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.classify_operator import ClassifyOperator
from blue_data_ops.operators.types import (
    Attributes,
    DataBundle,
    Properties,
    ValidationResult,
)


class ClassifyOutcomeOperator(_OutcomeOperator, ClassifyOperator):
    """Reject calls that cannot train the selected classifier."""

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        validation = super()._validate_input(input_data, attributes, properties)
        if not validation.ok:
            return validation

        algorithm = properties.get("algorithm", "decision_tree") if properties else "decision_tree"
        if algorithm not in {"decision_tree", "knn", "multinomial_nb"}:
            return ValidationResult(False, "supply a supported classification algorithm")

        # Any nonempty group requires usable training data in the first group.
        if not any(input_data):
            return ValidationResult(True, None)

        vector_key = attributes["vector_key"]
        label_key = attributes["label_key"]
        has_training_row = any(
            isinstance(record.get(vector_key), list) and record.get(label_key) is not None
            for record in input_data[0]
        )
        if not has_training_row:
            return ValidationResult(False, "supply usable training data in the first group")
        return ValidationResult(True, None)

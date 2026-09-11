from __future__ import annotations

from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.nl2sql_operator import NL2SQLOperator
from blue_data_ops.operators.types import (
    Attributes,
    DataBundle,
    Properties,
    ValidationResult,
)

_PROTOCOLS = {"postgres", "mysql", "sqlite"}


class NL2SQLOutcomeOperator(_OutcomeOperator, NL2SQLOperator):
    """Validate SQL routing fields before resolving registry or provider dependencies."""

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        validation = super()._validate_input(input_data, attributes, properties)
        if not validation.ok:
            return validation
        required = ("question", "source", "database", "collection", "protocol")
        if any(
            not isinstance(attributes.get(name), str) or not attributes[name].strip()
            for name in required
        ):
            return ValidationResult(False, "SQL routing fields must be nonblank strings")
        if attributes["protocol"] not in _PROTOCOLS:
            return ValidationResult(False, "protocol must be postgres, mysql, or sqlite")
        return validation

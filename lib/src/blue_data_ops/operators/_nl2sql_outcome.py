from __future__ import annotations

from types import MethodType

from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.nl2sql_operator import (
    NL2SQLOperator,
    _MissingRegistryError,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.types import (
    Attributes,
    DataBundle,
    FunctionResult,
    Properties,
    ValidationResult,
)

_PROTOCOLS = {"postgres", "mysql", "sqlite"}


class NL2SQLOutcomeOperator(_OutcomeOperator, NL2SQLOperator):
    """Validate SQL routing fields before resolving registry or provider dependencies."""

    def apply(
        self, input_data: DataBundle, attributes: Attributes, properties: Properties | None = None
    ) -> DataBundle:
        try:
            execute = self._execute
            if type(execute) is MethodType and execute.__func__ is _BUILTIN_EXECUTE:
                return self._execute_sql(input_data, attributes, properties).output_data
            return execute(input_data, attributes, properties).output_data
        except _MissingRegistryError:
            return [[]]

    def _execute(
        self, input_data: DataBundle, attributes: Attributes, properties: Properties | None = None
    ) -> FunctionResult:
        return self._execute_sql(
            input_data, attributes, properties, _diagnose_generation_target=True
        )

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


_BUILTIN_EXECUTE = NL2SQLOutcomeOperator.__dict__["_execute"]

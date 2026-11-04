from __future__ import annotations

from blue_data_ops.data import resolve_registry
from blue_data_ops.data.errors import RegistryFailure, RegistryReason
from blue_data_ops.data.local_names import sqlite_connect_missing
from blue_data_ops.data.registry_seam import (
    _diagnose_source,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.data.sql_insert import insert_batch
from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.insert_table_operator import InsertTableOperator
from blue_data_ops.operators.types import (
    Attributes,
    DataBundle,
    FunctionResult,
    Properties,
    ValidationResult,
)


class InsertTableOutcomeOperator(_OutcomeOperator, InsertTableOperator):
    """Preserve inserted records and report a count when every batch supplies one."""

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        validation = super()._validate_input(input_data, attributes, properties)
        if not validation.ok:
            return validation
        columns: set[str] | None = None
        for group in input_data:
            for record in group:
                if not record:
                    return ValidationResult(False, "supply nonempty records")
                if columns is None:
                    columns = set(record)
                if set(record) != columns:
                    return ValidationResult(False, "use the same columns in every record")
        return ValidationResult(True, None)

    def _execute_insert(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
        *,
        _diagnose_registry: bool = False,
    ) -> FunctionResult:
        registry = resolve_registry(properties)
        if registry is None:
            if _diagnose_registry:
                raise RegistryFailure(RegistryReason.NOT_CONFIGURED)
            raise RuntimeError("data registry is unavailable")
        count = 0
        count_known = True
        batch_size = attributes.get("batch_size", 100)
        for group in input_data:
            for offset in range(0, len(group), batch_size):
                batch = group[offset : offset + batch_size]
                columns = list(batch[0])
                rows = [tuple(record[column] for column in columns) for record in batch]
                checked = (
                    _diagnose_source(registry, attributes["source"]) if _diagnose_registry else None
                )
                source = (
                    checked
                    if checked is not None
                    else registry.connect_source(attributes["source"])
                )
                if source is None:
                    if _diagnose_registry:
                        raise RegistryFailure(RegistryReason.SOURCE_UNAVAILABLE)
                    raise RuntimeError("data source is unavailable")
                try:
                    batch_count = insert_batch(
                        source, attributes["database"], attributes["table"], columns, rows
                    )
                except FileNotFoundError as error:
                    if _diagnose_registry and sqlite_connect_missing(error, attributes["database"]):
                        raise RegistryFailure(RegistryReason.DATABASE_NOT_FOUND) from None
                    raise
                if batch_count is not None:
                    count += batch_count
                else:
                    count_known = False
        return FunctionResult(input_data, {"num_rows_insert": count} if count_known else {})

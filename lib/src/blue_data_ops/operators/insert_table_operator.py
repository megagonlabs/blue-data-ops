from __future__ import annotations

import logging
from types import MethodType
from typing import Any, ClassVar, cast

from blue_data_ops.data import RegistrySeam, resolve_registry
from blue_data_ops.data.errors import RegistryFailure, RegistryReason
from blue_data_ops.data.local_names import sqlite_connect_missing
from blue_data_ops.data.registry_seam import (
    _diagnose_source,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators._discovery import DiscoverySpec
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    DataBundle,
    FunctionResult,
    Properties,
    Record,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class _InsertTablePassThroughFailure(RegistryFailure):
    pass


class _InsertTableEmptyFailure(RegistryFailure):
    pass


class InsertTableOperator(Operator):
    """Insert data rows into a database table through the data registry's source."""

    # The empty-input guard checks only the first group, so later groups are ignored
    # when it is empty. Collection affects logging but not SQL. Connections reopen per
    # batch; insertion failure returns [[]], success returns the original input, and
    # operation errors are swallowed.

    name: ClassVar[str] = "insert_table"
    description: ClassVar[str] = "Inserts data rows into database tables in a data source."
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "source": AttributeSpec(
            type="str",
            description="Name of the data source where the table is located",
            required=True,
            default="default_source",
        ),
        "database": AttributeSpec(
            type="str",
            description="Name of the database where the table is located",
            required=True,
            default="default",
        ),
        "collection": AttributeSpec(
            type="str",
            description=(
                "Name of the collection where the table is located. For SQLite sources, "
                "defaults to 'public' if not specified"
            ),
            default="public",
        ),
        "table": AttributeSpec(
            type="str",
            description="Name of the table to insert data into",
            required=True,
            default="",
        ),
        "batch_size": AttributeSpec(
            type="int",
            description="Number of rows to insert in each batch (default: 100)",
            default=100,
        ),
    }

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        try:
            execute = self._execute
            if type(execute) is MethodType and execute.__func__ is _BUILTIN_EXECUTE:
                return self._execute_insert(input_data, attributes, properties).output_data
            return execute(input_data, attributes, properties).output_data
        except _InsertTableEmptyFailure:
            return [[]]
        except _InsertTablePassThroughFailure:
            return input_data

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        return self._execute_insert(input_data, attributes, properties, _diagnose_registry=True)

    def _execute_insert(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
        *,
        _diagnose_registry: bool = False,
    ) -> FunctionResult:
        source = cast(str, attributes.get("source", "default_source"))
        database = cast(str, attributes.get("database", "default"))
        collection = cast(str, attributes.get("collection", "public"))
        table = cast(str, attributes.get("table", ""))
        batch_size = cast(int, attributes.get("batch_size", 100))

        registry = resolve_registry(properties)
        if not registry:
            logger.error("Error: Data registry not found")
            raise _InsertTablePassThroughFailure(RegistryReason.NOT_CONFIGURED)

        # SQLite sources report 'public' as the collection name; the probe runs even
        # though collection only affects the log line below (lookup errors ignored).
        try:
            source_properties = registry.get_source_properties(source)
            if source_properties and "connection" in source_properties:
                protocol = source_properties["connection"].get("protocol", "")
                if protocol == "sqlite":
                    collection = "public"
        except Exception:
            pass

        try:
            # The guard checks only the first group: an empty first group ends the
            # whole operation even when later groups have rows.
            if not input_data or not input_data[0]:
                return FunctionResult([[]], {})

            total_inserted = 0
            for group_idx, row_group in enumerate(input_data):
                if not row_group:
                    continue

                group_inserted = _insert_data_group(
                    registry,
                    source,
                    database,
                    table,
                    row_group,
                    batch_size,
                    group_idx,
                    _diagnose_registry=_diagnose_registry,
                )
                if group_inserted is None:
                    raise _InsertTableEmptyFailure
                total_inserted += group_inserted

            logger.info(
                "Successfully inserted %d rows into table '%s' in database '%s' "
                "collection '%s' of source '%s'.",
                total_inserted,
                table,
                database,
                collection,
                source,
            )
            return FunctionResult(input_data, {})
        except _InsertTableEmptyFailure:
            raise
        except Exception as error:
            logger.error("insert_table failed; passing input through")
            raise _InsertTablePassThroughFailure(error) from None

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        result = self._validate_input(input_data, attributes, properties)
        return type(result) is ValidationResult and result.ok is True

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        suggestion = (
            "supply non-empty source, database, and table values with a positive batch size"
        )
        if not super().validate(input_data, attributes, properties):
            return ValidationResult(False, suggestion)

        source = attributes.get("source", "")
        database = attributes.get("database", "")
        table = attributes.get("table", "")

        if not source or not source.strip():
            return ValidationResult(False, suggestion)
        if not database or not database.strip():
            return ValidationResult(False, suggestion)
        if not table or not table.strip():
            return ValidationResult(False, suggestion)

        batch_size = attributes.get("batch_size", 100)
        if not isinstance(batch_size, int) or batch_size <= 0:
            return ValidationResult(False, suggestion)

        return ValidationResult(True, None)

    def explain(
        self,
        output: DataBundle,
        input_data: DataBundle,
        attributes: Attributes,
    ) -> dict[str, Any]:
        source = attributes.get("source", "default_source")
        database = attributes.get("database", "default")
        collection = attributes.get("collection", "public")
        table = attributes.get("table", "")
        batch_size = attributes.get("batch_size", 100)
        total_rows = sum(len(row_group) for row_group in input_data)
        num_data_groups = len(input_data)

        return {
            "input_data": input_data,
            "attributes": attributes,
            "explanation": (
                f"Insert table operator inserted {total_rows} data rows from "
                f"{num_data_groups} data groups into table '{table}' in database "
                f"'{database}' collection '{collection}' of source '{source}' using "
                f"batch size {batch_size}."
            ),
        }


def _insert_data_group(
    registry: RegistrySeam,
    source: str,
    database: str,
    table: str,
    row_group: list[Record],
    batch_size: int,
    group_idx: int,
    *,
    _diagnose_registry: bool = False,
) -> int | None:
    # Ignore empty and non-mapping entries before constructing SQL rows.
    data_rows = [
        row
        for row in row_group
        if isinstance(row, dict) and row  # pyright: ignore[reportUnnecessaryIsInstance]
    ]
    if not data_rows:
        return 0

    group_inserted = 0
    for i in range(0, len(data_rows), batch_size):
        batch = data_rows[i : i + batch_size]
        if not batch:
            continue

        # Column set comes from the batch's FIRST row; later rows fill missing
        # columns with None and drop extra keys.
        columns = list(batch[0].keys())
        columns_str = ", ".join('"' + str(col).replace('"', '""') + '"' for col in columns)
        placeholders = ", ".join(["?" for _ in columns])
        table_sql = '"' + str(table).replace('"', '""') + '"'
        insert_query = f"INSERT INTO {table_sql} ({columns_str}) VALUES ({placeholders})"

        batch_data = [tuple(row.get(col) for col in columns) for row in batch]

        try:
            # Reopen the source connection for every batch.
            checked = _diagnose_source(registry, source) if _diagnose_registry else None
            source_connection = checked if checked is not None else registry.connect_source(source)
            if source_connection:
                try:
                    db_connection = source_connection._db_connect(database)
                except FileNotFoundError as error:
                    if sqlite_connect_missing(error, database):
                        raise RegistryFailure(RegistryReason.DATABASE_NOT_FOUND) from None
                    raise
                cursor = db_connection.cursor()
                cursor.executemany(insert_query, batch_data)
                db_connection.commit()
                group_inserted += cursor.rowcount
                source_connection._db_disconnect(db_connection)
            else:
                return None
        except Exception as error:
            logger.error("insert batch failed")
            raise _InsertTableEmptyFailure(error) from None

    return group_inserted


DISCOVERY = DiscoverySpec(
    when_to_invoke="Use when record rows must be persisted into a registry-backed database table.",
    tags=(
        "domain-relational",
        "flow-sink",
        "accepts-data",
        "produces-data",
        "produces-side-effect",
        "capability-persist",
        "requires-data-registry",
        "requires-database-backend",
    ),
)


_BUILTIN_EXECUTE = InsertTableOperator.__dict__["_execute"]

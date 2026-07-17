from __future__ import annotations

import logging
from typing import Any, ClassVar, cast

from blue_data_ops.data import RegistrySeam, resolve_registry
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import Attributes, AttributeSpec, DataBundle, Properties, Record

logger = logging.getLogger(__name__)


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
        source = cast(str, attributes.get("source", "default_source"))
        database = cast(str, attributes.get("database", "default"))
        collection = cast(str, attributes.get("collection", "public"))
        table = cast(str, attributes.get("table", ""))
        batch_size = cast(int, attributes.get("batch_size", 100))

        registry = resolve_registry(properties)
        if not registry:
            logger.error("Error: Data registry not found")
            return input_data

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
                return [[]]

            total_inserted = 0
            for group_idx, row_group in enumerate(input_data):
                if not row_group:
                    continue

                group_inserted = _insert_data_group(
                    registry, source, database, table, row_group, batch_size, group_idx
                )
                if group_inserted is None:
                    return [[]]
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
            return input_data
        except Exception:
            logger.exception("insert_table failed; passing input through")
            return input_data

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        if not super().validate(input_data, attributes, properties):
            return False

        source = attributes.get("source", "")
        database = attributes.get("database", "")
        table = attributes.get("table", "")

        if not source or not source.strip():
            return False
        if not database or not database.strip():
            return False
        if not table or not table.strip():
            return False

        batch_size = attributes.get("batch_size", 100)
        if not isinstance(batch_size, int) or batch_size <= 0:
            return False

        return True

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
        columns_str = ", ".join([f'"{col}"' for col in columns])
        placeholders = ", ".join(["?" for _ in columns])
        insert_query = f'INSERT INTO "{table}" ({columns_str}) VALUES ({placeholders})'

        batch_data = [tuple(row.get(col) for col in columns) for row in batch]

        try:
            # Reopen the source connection for every batch.
            source_connection = registry.connect_source(source)
            if source_connection:
                db_connection = source_connection._db_connect(database)
                cursor = db_connection.cursor()
                cursor.executemany(insert_query, batch_data)
                db_connection.commit()
                group_inserted += cursor.rowcount
                source_connection._db_disconnect(db_connection)
            else:
                return None
        except Exception as e:
            logger.error(
                "Error inserting group %d, batch %d: %s", group_idx + 1, i // batch_size + 1, e
            )
            logger.exception("insert batch failed")
            return None

    return group_inserted

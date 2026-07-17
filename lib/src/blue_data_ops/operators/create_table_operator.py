from __future__ import annotations

import logging
from typing import Any, ClassVar, cast

from blue_data_ops.data import resolve_registry
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import Attributes, AttributeSpec, DataBundle, Properties

logger = logging.getLogger(__name__)


class CreateTableOperator(Operator):
    """Create a table (entity) in a database collection through the data registry."""

    # This operator is pass-through and swallows registry failures. SQLite sources use
    # collection="public". Building creation_properties aliases and mutates the
    # caller's misc mapping by inserting cols_definition.

    name: ClassVar[str] = "create_table"
    description: ClassVar[str] = (
        "Creates tables (entities) in database collections using the data registry. If the "
        "table already exists, it will be overwritten if overwrite is True."
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "source": AttributeSpec(
            type="str",
            description="Name of the data source where the table will be created",
            required=True,
            default="default_source",
        ),
        "database": AttributeSpec(
            type="str",
            description="Name of the database where the table will be created",
            required=True,
            default="default",
        ),
        "collection": AttributeSpec(
            type="str",
            description=(
                "Name of the collection where the table will be created. For SQLite sources, "
                "defaults to 'public' if not specified"
            ),
            default="public",
        ),
        "table": AttributeSpec(
            type="str", description="Name of the table to be created", required=True, default=""
        ),
        "description": AttributeSpec(
            type="str", description="Description of the table to be created", default=""
        ),
        # The public schema declares str while retaining an empty-mapping default.
        "properties": AttributeSpec(
            type="str", description="Properties of the table to be created", default={}
        ),
        "columns": AttributeSpec(
            type="list",
            description="Properties of the table to be created",
            required=True,
            default=[],
        ),
        "misc": AttributeSpec(
            type="dict",
            description="Miscellaneous keys such as primary and foreign keys ",
            default={},
        ),
        "created_by": AttributeSpec(type="str", description="Creator of the table", default=""),
        "overwrite": AttributeSpec(
            type="bool", description="Whether to overwrite the existing table", default=False
        ),
    }

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        overwrite = attributes.get("overwrite", False)
        source = cast(str, attributes.get("source", "default_source"))
        database = cast(str, attributes.get("database", "default"))
        collection = cast(str, attributes.get("collection", "public"))
        table = cast(str, attributes.get("table"))
        table_description = attributes.get("description", "")
        table_properties = attributes.get("properties", {})
        columns = attributes.get("columns")
        misc = cast("dict[str, Any]", attributes.get("misc", {}))

        registry = resolve_registry(properties)
        if not registry:
            logger.error("Error: Data registry not found")
            return input_data

        # SQLite sources always use 'public' as the collection name, even when the
        # caller specifies a different one (lookup errors are ignored).
        try:
            source_properties = registry.get_source_properties(source)
            if source_properties and "connection" in source_properties:
                protocol = source_properties["connection"].get("protocol", "")
                if protocol == "sqlite":
                    collection = "public"
        except Exception:
            pass

        try:
            creation_properties = misc
            creation_properties["cols_definition"] = columns

            registry.create_source_database_collection_entity(
                source=source,
                database=database,
                collection=collection,
                entity=table,
                properties=table_properties,
                creation_properties=creation_properties,
                overwrite=overwrite,
                rebuild=True,
                recursive=False,
            )

            if table_description:
                registry.set_source_database_collection_entity_description(
                    source=source,
                    database=database,
                    collection=collection,
                    entity=table,
                    description=table_description,
                    rebuild=True,
                )

            created_by = attributes.get("created_by")
            if created_by:
                registry.set_record_data(
                    name=table,
                    type="entity",
                    scope=f"/source/{source}/database/{database}/collection/{collection}",
                    key="created_by",
                    value=created_by,
                    rebuild=True,
                )

            logger.info(
                "Successfully created table '%s' in database '%s' collection '%s' of source '%s'.",
                table,
                database,
                collection,
                source,
            )
            return input_data
        except Exception:
            logger.exception("create_table failed; passing input through")
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
        if not source or not source.strip():
            return False

        database = attributes.get("database", "")
        if not database or not database.strip():
            return False

        collection = attributes.get("collection", "public")
        if not collection or not collection.strip():
            return False

        table = attributes.get("table", "")
        if not table or not table.strip():
            return False

        columns = attributes.get("columns", [])
        if not isinstance(columns, list) or not columns:
            return False

        for column in cast("list[Any]", columns):
            if not isinstance(column, dict):
                return False
            column = cast("dict[str, Any]", column)
            if "name" not in column or not column["name"]:
                return False
            if "type" in column and not isinstance(column["type"], str):
                return False
            if "misc" in column and not isinstance(column["misc"], str):
                return False

        column_dicts = cast("list[dict[str, Any]]", columns)
        misc = cast("dict[str, Any]", attributes.get("misc", {}))

        primary_key = misc.get("primary_key", [])
        if primary_key:
            if not isinstance(primary_key, list):
                return False
            col_names = [col["name"] for col in column_dicts]
            for pk_col in cast("list[Any]", primary_key):
                if pk_col not in col_names:
                    return False

        foreign_keys = misc.get("foreign_keys", [])
        if foreign_keys:
            if not isinstance(foreign_keys, list):
                return False
            for fk in cast("list[Any]", foreign_keys):
                if not isinstance(fk, dict):
                    return False
                fk = cast("dict[str, Any]", fk)
                required_fk_fields = [
                    "foreign_keys_source_columns",
                    "foreign_keys_target_table",
                    "foreign_keys_target_columns",
                ]
                for field in required_fk_fields:
                    if field not in fk:
                        return False
                col_names = [col["name"] for col in column_dicts]
                for fk_col in cast("list[Any]", fk["foreign_keys_source_columns"]):
                    if fk_col not in col_names:
                        return False

        return True

    def explain(
        self,
        output: DataBundle,
        input_data: DataBundle,
        attributes: Attributes,
    ) -> dict[str, Any]:
        # The explanation reports the first input record's name rather than the table
        # attribute; malformed input yields an empty name.
        source = attributes.get("source", "default_source")
        database = attributes.get("database", "default")
        collection = attributes.get("collection", "public")
        overwrite = attributes.get("overwrite", False)

        try:
            table_name = input_data[0][0].get("name", "") if input_data and input_data[0] else ""
        except (IndexError, KeyError, TypeError, AttributeError):
            table_name = ""

        return {
            "input_data": input_data,
            "attributes": attributes,
            "explanation": (
                f"Create table operator {'overwrote' if overwrite else 'created'} table "
                f"'{table_name}' in database '{database}' collection '{collection}' of "
                f"source '{source}'."
            ),
        }

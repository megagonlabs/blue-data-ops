from __future__ import annotations

import logging
from typing import Any, ClassVar, cast

from blue_data_ops.data import resolve_registry
from blue_data_ops.operators._discovery import DiscoverySpec
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    DataBundle,
    FunctionResult,
    Properties,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class _CreateDatabaseFailure(Exception):
    pass


class CreateDatabaseOperator(Operator):
    """Create a database in a data source through the data registry."""

    # This operator is pass-through: it returns the original input after success, a
    # missing registry, or a caught registry error. Registry failures do not propagate.

    name: ClassVar[str] = "create_database"
    description: ClassVar[str] = (
        "Creates databases in data sources using the data registry. If the database already "
        "exists, it will be overwritten if overwrite is True."
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "source": AttributeSpec(
            type="str",
            description="Name of the data source where the database will be created",
            required=True,
            default="",
        ),
        "database": AttributeSpec(
            type="str", description="Name of the database to be created", required=True, default=""
        ),
        "description": AttributeSpec(
            type="str", description="Description of the database to be created", default=""
        ),
        # The public schema declares str while retaining an empty-mapping default.
        # A caller-supplied mapping therefore fails normal attribute validation.
        "properties": AttributeSpec(
            type="str",
            description="Properties of the database to be created",
            default={},
            materialize_default=False,
        ),
        "created_by": AttributeSpec(type="str", description="Creator of the database", default=""),
        "overwrite": AttributeSpec(
            type="bool", description="Whether to overwrite the existing database", default=False
        ),
    }

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        try:
            return self._execute(input_data, attributes, properties).output_data
        except _CreateDatabaseFailure:
            return input_data

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        overwrite = attributes.get("overwrite", False)
        source = cast(str, attributes.get("source", ""))
        database = cast(str, attributes.get("database"))
        database_description = attributes.get("description", "")
        database_properties = attributes.get("properties", {})

        registry = resolve_registry(properties)
        if not registry:
            logger.error("Error: Data registry not found")
            raise _CreateDatabaseFailure

        try:
            registry.create_source_database(
                source=source,
                database=database,
                properties=database_properties,
                overwrite=overwrite,
                rebuild=True,
                recursive=False,
            )

            if database_description:
                registry.set_source_database_description(
                    source=source,
                    database=database,
                    description=database_description,
                    rebuild=True,
                )

            created_by = attributes.get("created_by")
            if created_by:
                registry.set_record_data(
                    name=database,
                    type="database",
                    scope=f"/source/{source}",
                    key="created_by",
                    value=created_by,
                    rebuild=True,
                )

            logger.info("Successfully created database '%s' in source '%s'.", database, source)
            return FunctionResult(input_data, {})
        except Exception as error:
            logger.exception("create_database failed; passing input through")
            raise _CreateDatabaseFailure from error

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
        suggestion = "supply non-empty source and database values"
        if not super().validate(input_data, attributes, properties):
            return ValidationResult(False, suggestion)

        source = attributes.get("source", "")
        if not source or not source.strip():
            return ValidationResult(False, suggestion)

        database = attributes.get("database", "")
        if not database or not database.strip():
            return ValidationResult(False, suggestion)

        return ValidationResult(True, None)

    def explain(
        self,
        output: DataBundle,
        input_data: DataBundle,
        attributes: Attributes,
    ) -> dict[str, Any]:
        # The explanation reports the first input record's name rather than the
        # database attribute; malformed input yields an empty name.
        source = attributes.get("source", "")
        overwrite = attributes.get("overwrite", False)
        try:
            database_name = input_data[0][0].get("name", "") if input_data and input_data[0] else ""
        except (IndexError, KeyError, TypeError, AttributeError):
            database_name = ""

        return {
            "input_data": input_data,
            "attributes": attributes,
            "explanation": (
                f"Create database operator {'overwrote' if overwrite else 'created'} "
                f"database '{database_name}' in source '{source}'."
            ),
        }


DISCOVERY = DiscoverySpec(
    when_to_invoke=(
        "Use when one or more databases must be created or overwritten through the data registry."
    ),
    tags=(
        "domain-relational",
        "flow-control",
        "accepts-data",
        "accepts-none",
        "produces-data",
        "produces-side-effect",
        "capability-create-database",
        "requires-data-registry",
        "requires-database-backend",
    ),
)

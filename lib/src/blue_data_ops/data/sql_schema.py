from __future__ import annotations

from typing import Any, cast

from blue_data_ops.data.registry_seam import RegistrySeam
from blue_data_ops.data.sql_errors import loaded_class

_RELATION_FIELDS = ("name", "source", "target", "source_entity", "target_entity")
_RELATION_COLUMN_FIELDS = ("foreign_keys_source_columns", "foreign_keys_target_columns")


def project_sql_schema(
    registry: Any, source: str, database: str, collection: str, *, protocol: str | None = None
) -> dict[str, Any]:
    """Project registered names, declared types, relation endpoints and join columns."""
    del protocol  # The registry derives the protocol from the registered source.
    if _has_schema_override(registry):
        schema = registry.get_data_source_schema(source, database, collection)
        return _custom_schema_projection(schema)
    entities: list[dict[str, Any]] = []
    for record in registry.list_collection_entities(source, database, collection):
        name = record["name"]
        if type(name) is not str:
            raise TypeError("entity name must be a string")
        attributes: dict[str, dict[str, str]] = {}
        for attribute in registry.list_entity_attributes(source, database, collection, name):
            attr_name = attribute["name"]
            if type(attr_name) is not str:
                raise TypeError("attribute name must be a string")
            info = attribute.get("properties", {}).get("info", {})
            declared_type = (
                cast(dict[str, Any], info).get("type") if isinstance(info, dict) else None
            )
            attributes[attr_name] = (
                {"type": declared_type} if type(declared_type) is str and declared_type else {}
            )
        entities.append({"name": name, "attributes": dict(sorted(attributes.items()))})
    relations: list[dict[str, Any]] = []
    for record in registry.list_collection_relations(source, database, collection):
        properties = record.get("properties", {})
        relations.append(_relation_projection({"name": record["name"], **properties}))
    return {
        "entities": sorted(entities, key=lambda entity: entity["name"]),
        "relations": sorted(relations, key=lambda relation: relation["name"]),
    }


def _has_schema_override(registry: Any) -> bool:
    registry_class = cast(type[Any], type(registry))
    if isinstance(registry, RegistrySeam):
        return (
            "get_data_source_schema" in vars(registry)
            or type(registry).get_data_source_schema is not RegistrySeam.get_data_source_schema
            or _has_schema_override(vars(registry).get("_delegate"))
        )
    native = loaded_class("blue_data.registry.data_registry", "DataRegistry")
    return (
        native is not None
        and isinstance(registry, native)
        and (
            "get_data_source_schema" in vars(registry)
            or getattr(registry_class, "get_data_source_schema")
            is not getattr(native, "get_data_source_schema")
        )
    )


def _custom_schema_projection(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        raise TypeError("unsupported SQL schema shape")
    schema = cast(dict[str, Any], schema)
    if "entities" not in schema and "relations" not in schema:
        schema = _legacy_schema(schema)
    if not isinstance(schema.get("entities", []), list) or not isinstance(
        schema.get("relations", []), list
    ):
        raise TypeError("unsupported SQL schema shape")
    entities: list[dict[str, Any]] = []
    for entity in schema.get("entities", []):
        name = entity["name"]
        if type(name) is not str:
            raise TypeError("entity name must be a string")
        if not isinstance(entity.get("attributes", {}), dict):
            raise TypeError("unsupported SQL schema shape")
        attributes: dict[str, dict[str, str]] = {}
        for attr_name, info in entity.get("attributes", {}).items():
            if type(attr_name) is not str:
                raise TypeError("attribute name must be a string")
            declared_type = (
                cast(dict[str, Any], info).get("type") if isinstance(info, dict) else info
            )
            attributes[attr_name] = (
                {"type": declared_type} if type(declared_type) is str and declared_type else {}
            )
        entities.append({"name": name, "attributes": dict(sorted(attributes.items()))})
    relations: list[dict[str, Any]] = []
    for record in schema.get("relations", []):
        relations.append(_relation_projection(record))
    return {
        "entities": sorted(entities, key=lambda entity: entity["name"]),
        "relations": sorted(relations, key=lambda relation: relation["name"]),
    }


def _legacy_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize table/column-type maps and the shipped columns-name list shape."""
    entities: list[dict[str, Any]] = []
    for name, columns in schema.items():
        if type(name) is not str or not isinstance(columns, dict):
            raise TypeError("unsupported SQL schema shape")
        columns = cast(dict[str, Any], columns)
        attributes: dict[str, dict[str, str]]
        if set(columns) == {"columns"} and isinstance(columns["columns"], list):
            names = cast(list[Any], columns["columns"])
            if any(type(column) is not str for column in names):
                raise TypeError("attribute name must be a string")
            attributes = {column: {} for column in names}
        else:
            if any(
                type(column) is not str or type(value) is not str
                for column, value in columns.items()
            ):
                raise TypeError("unsupported SQL schema shape")
            attributes = {column: {"type": value} for column, value in columns.items()}
        entities.append({"name": name, "attributes": attributes})
    return {"entities": entities, "relations": []}


def _relation_projection(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise TypeError("unsupported SQL schema shape")
    record = cast(dict[str, Any], record)
    relation = {key: record[key] for key in _RELATION_FIELDS if key in record}
    if "name" not in relation or any(type(value) is not str for value in relation.values()):
        raise TypeError("relation fields must be strings")
    for key in _RELATION_COLUMN_FIELDS:
        if key in record:
            columns = record[key]
            if type(columns) is not list or any(
                type(column) is not str for column in cast(list[Any], columns)
            ):
                raise TypeError("relation columns must be lists of strings")
            relation[key] = list(cast(list[str], columns))
    return relation

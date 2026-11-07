from __future__ import annotations

from typing import Any

from blue_data_ops.data.errors import RegistryFailure, RegistryReason
from blue_data_ops.data.local_names import peer_names, sqlite_names
from blue_data_ops.data.sql_errors import loaded_class

_SQL_SOURCES = (
    ("blue_data.source.sql.sqlite.sqlite_sql_source", "SQLiteDBSource"),
    ("blue_data.source.sql.postgres.postgres_sql_source", "PostgresDBSource"),
    ("blue_data.source.sql.mysql.mysql_sql_source", "MySQLDBSource"),
)


def validate_sql_target(
    registry: Any,
    source: str,
    database: str,
    collection: str,
    *,
    schema_override: bool,
    generation: bool = False,
) -> None:
    if schema_override:
        return
    native = loaded_class("blue_data.registry.data_registry", "DataRegistry")
    if native is None or not isinstance(registry, native):
        return
    try:
        live = registry.get_source(source)
    except Exception:
        raise RuntimeError("SQL target catalog lookup failed") from None
    classes = tuple(loaded_class(module, name) for module, name in _SQL_SOURCES)
    if not any(cls is not None and type(live) is cls for cls in classes):
        return
    try:
        databases = peer_names(registry.list_source_databases(source))
        collections = peer_names(registry.list_database_collections(source, database))
    except Exception:
        raise RuntimeError("SQL target catalog lookup failed") from None
    database_absent = databases is not None and database not in databases
    collection_absent = collections is not None and collection not in collections
    if not database_absent and not collection_absent:
        return
    if generation and type(live) is classes[0]:
        names = sqlite_names(live)
        if names is None:
            return
        if database_absent and database not in names:
            raise RegistryFailure(RegistryReason.DATABASE_ABSENT)
        if database in names and collection_absent and collection != "public":
            raise RegistryFailure(RegistryReason.COLLECTION_ABSENT)
        return
    if database_absent:
        raise RegistryFailure(RegistryReason.DATABASE_ABSENT)
    if collection_absent:
        raise RegistryFailure(RegistryReason.COLLECTION_ABSENT)

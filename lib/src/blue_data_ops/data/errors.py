from __future__ import annotations

import sqlite3
from enum import StrEnum

from blue_data_ops.data.sql_errors import driver_reason


class RegistryReason(StrEnum):
    NOT_CONFIGURED = "REGISTRY_NOT_CONFIGURED"
    SOURCE_NOT_REGISTERED = "SOURCE_NOT_REGISTERED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    RESTART_REQUIRED = "REGISTRY_RESTART_REQUIRED"
    CONFIGURATION_FAILED = "REGISTRY_CONFIGURATION_FAILED"
    CONSTRAINT_FAILED = "CONSTRAINT_FAILED"
    QUERY_FAILED = "QUERY_FAILED"
    BACKEND_FAILED = "BACKEND_FAILED"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    DATABASE_NOT_FOUND = "DATABASE_NOT_FOUND"
    DATABASE_ABSENT = "DATABASE_ABSENT"
    COLLECTION_ABSENT = "COLLECTION_ABSENT"


REGISTRY_DIAGNOSTICS: dict[RegistryReason, tuple[str, str]] = {
    RegistryReason.NOT_CONFIGURED: (
        "data registry is not configured",
        "Ask the deployment owner to configure a data registry and restart the server.",
    ),
    RegistryReason.SOURCE_NOT_REGISTERED: (
        "data source is not registered",
        "Check the declared source attribute against the deployment's registered sources.",
    ),
    RegistryReason.SOURCE_UNAVAILABLE: (
        "data source is unavailable",
        "Ask the deployment owner to check source connectivity and restart after recovery.",
    ),
    RegistryReason.RESTART_REQUIRED: (
        "data registry access is suspended after an operator timeout",
        (
            "The worker may still finish; check backend effects and restart the "
            "server before further registry calls."
        ),
    ),
    RegistryReason.CONFIGURATION_FAILED: (
        "data registry configuration failed",
        (
            "Ask the deployment owner to check the registry store and sources "
            "configuration, then restart the server."
        ),
    ),
    RegistryReason.CONSTRAINT_FAILED: (
        "database constraint rejected the operation",
        "Check required values, uniqueness and related records against the database constraints.",
    ),
    RegistryReason.QUERY_FAILED: (
        "database query or operation failed",
        "Check the query, declared schema, database permissions and backend availability.",
    ),
    RegistryReason.CONNECTION_FAILED: (
        "database connection or access failed",
        "Ask the deployment owner to check connectivity and database permissions.",
    ),
    RegistryReason.DATABASE_NOT_FOUND: (
        "database does not exist",
        "Check the declared database or create it before this operation.",
    ),
    RegistryReason.DATABASE_ABSENT: (
        "database is not available in the declared source",
        (
            "Check the database name against the registered databases. "
            "If it was created after the last sync, sync the source."
        ),
    ),
    RegistryReason.COLLECTION_ABSENT: (
        "collection is not available in the declared database",
        (
            "Check the collection name against the registered collections; "
            "sync the source if it was created after the last sync. "
            "MySQL and SQLite use 'public'."
        ),
    ),
    RegistryReason.BACKEND_FAILED: (
        "operator execution failed",
        "Check the declared inputs and backend configuration.",
    ),
}


class RegistryFailure(RuntimeError):
    def __init__(self, reason: RegistryReason | BaseException = RegistryReason.BACKEND_FAILED):
        self.reason = owned_reason(reason) if isinstance(reason, BaseException) else reason
        super().__init__(REGISTRY_DIAGNOSTICS[self.reason][0])


class RegistryNotConfigured(RegistryFailure):
    def __init__(self) -> None:
        super().__init__(RegistryReason.NOT_CONFIGURED)


def owned_reason(error: BaseException) -> RegistryReason:
    if isinstance(error, RegistryFailure):
        return error.reason
    if isinstance(error, sqlite3.IntegrityError):
        return RegistryReason.CONSTRAINT_FAILED
    if isinstance(error, sqlite3.Error):
        return RegistryReason.QUERY_FAILED
    reason = driver_reason(error)
    return RegistryReason(reason) if reason is not None else RegistryReason.BACKEND_FAILED

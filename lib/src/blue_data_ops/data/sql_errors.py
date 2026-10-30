from __future__ import annotations

import sqlite3
import sys
from types import ModuleType
from typing import Any, cast


def loaded_class(module_name: str, name: str) -> type[Any] | None:
    module = sys.modules.get(module_name)
    if type(module) is not ModuleType:
        return None
    value = ModuleType.__getattribute__(module, "__dict__").get(name)
    return value if isinstance(value, type) else None


def _is(error: BaseException, module: str, name: str) -> bool:
    cls = loaded_class(module, name)
    return cls is not None and isinstance(error, cls)


_PG = {
    "InvalidCatalogName": ("3D000", "DATABASE_NOT_FOUND"),
    "UniqueViolation": ("23505", "CONSTRAINT_FAILED"),
    "NotNullViolation": ("23502", "CONSTRAINT_FAILED"),
    "UndefinedTable": ("42P01", "QUERY_FAILED"),
    "UndefinedColumn": ("42703", "QUERY_FAILED"),
    "SyntaxError": ("42601", "QUERY_FAILED"),
    "InsufficientPrivilege": ("42501", "CONNECTION_FAILED"),
}
_MYSQL = {
    **dict.fromkeys((1049,), "DATABASE_NOT_FOUND"),
    **dict.fromkeys((1062, 1048, 1451, 1452), "CONSTRAINT_FAILED"),
    **dict.fromkeys((1146, 1054, 1064), "QUERY_FAILED"),
    **dict.fromkeys((1044, 1045, 1142, 1143, 2002, 2003, 2005, 2006, 2013), "CONNECTION_FAILED"),
}


def driver_reason(error: BaseException) -> str | None:
    if _is(error, "mysql.connector.errors", "Error"):
        try:
            errno = cast(Any, error).errno
        except Exception:
            return None
        return _MYSQL.get(errno) if type(errno) is int else None
    if not _is(error, "psycopg2", "Error"):
        return None
    try:
        code = cast(Any, error).pgcode
    except Exception:
        return None
    if code is not None and type(code) is not str:
        return None
    for name, (expected, reason) in _PG.items():
        if _is(error, "psycopg2.errors", name):
            return reason if code is None or code == expected else None
    if code is not None:
        return next((reason for expected, reason in _PG.values() if code == expected), None)
    if _is(error, "psycopg2", "IntegrityError"):
        return "CONSTRAINT_FAILED"
    if any(_is(error, "psycopg2", name) for name in ("OperationalError", "InterfaceError")):
        return "CONNECTION_FAILED"
    return None


def query_schema_failure(error: BaseException) -> bool:
    if isinstance(error, sqlite3.Error):
        try:
            code = cast(Any, error).sqlite_errorcode
        except Exception:
            return False
        return type(code) is int and code == sqlite3.SQLITE_ERROR
    return driver_reason(error) == "QUERY_FAILED"

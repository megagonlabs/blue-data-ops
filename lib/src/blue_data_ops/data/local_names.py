from __future__ import annotations

import os
from types import FunctionType
from typing import Any, cast

from blue_data_ops.data.sql_errors import loaded_class

_SQLITE_MODULE = "blue_data.source.sql.sqlite.sqlite_sql_source"


def sqlite_names(source: object) -> set[str] | None:
    cls = loaded_class(_SQLITE_MODULE, "SQLiteDBSource")
    if cls is None or type(source) is not cls:
        return None
    try:
        state: Any = object.__getattribute__(source, "__dict__")
        properties = cast(dict[str, Any], state).get("properties") if type(state) is dict else None
        connection = (
            cast(dict[str, Any], properties).get("connection") if type(properties) is dict else None
        )
        directory = (
            cast(dict[str, Any], connection).get("database_directory")
            if type(connection) is dict
            else None
        )
        if type(directory) is not str or not directory:
            return None
        entries = os.listdir(directory)
    except (OSError, ValueError, TypeError):
        return None
    names: set[str] = set()
    for entry in entries:
        if type(entry) is not str or not entry or not entry.isprintable():
            return None
        for suffix in (".db", ".sqlite"):
            if entry.endswith(suffix):
                name = entry[: -len(suffix)]
                if not name or not name.isprintable():
                    return None
                names.add(name)
                break
    return names


def peer_names(records: object) -> set[str] | None:
    if type(records) is not list or not records:
        return None
    names: set[str] = set()
    for record in cast(list[object], records):
        if type(record) is not dict:
            return None
        name = cast(dict[str, object], record).get("name")
        if type(name) is not str or not name:
            return None
        names.add(name)
    return names


def sqlite_connect_missing(error: BaseException, database: str) -> bool:
    if not isinstance(error, FileNotFoundError):
        return False
    cls = loaded_class(_SQLITE_MODULE, "SQLiteDBSource")
    if cls is None:
        return False
    connect = vars(cls).get("_db_connect")
    if type(connect) is not FunctionType:
        return False
    # The delegated create-table call must have failed inside this exact SDK connect.
    trace = error.__traceback__
    while trace is not None:
        if trace.tb_frame.f_code is connect.__code__:
            source = trace.tb_frame.f_locals.get("self")
            names = sqlite_names(source)
            return names is not None and database not in names
        trace = trace.tb_next
    return False

"""Checks on the names and column text the create operators pass to a SQL source.

The SQL sources build ``CREATE`` statements from unescaped names and insert a column's
``type`` and ``misc`` as written. A name that closes its quote, or column text that ends
the statement, would make the source run SQL the caller did not declare, so either is
refused before the source is called.

Column ``type`` and ``misc`` are still SQL. Their checks refuse a second statement and
``--`` and ``/*`` comments; they do not refuse MySQL's ``#`` comment, which literal
defaults such as ``'#fff'`` contain, and they do not stop a comma from adding further
clauses or columns. SQLite inserts column names without quotes, and names are checked
only for a double quote, a backtick, ``;`` and NUL, so there a column name is SQL too.

The SQL sources also drop an existing table before they build the new definition when
``overwrite`` is set. SQLite and MySQL commit that drop at once, so there a definition the
source cannot build loses the table. Everything the sources read while building it is
therefore checked here too.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

_NAME_MARKS = (
    ('"', "a double quote"),
    ("`", "a backtick"),
    (";", "a semicolon"),
    ("\x00", "a NUL character"),
)
_DEFINITION_MARKS = (
    (";", "a semicolon"),
    ("--", "a comment marker (--)"),
    ("/*", "a comment marker (/*)"),
    ("\x00", "a NUL character"),
)


def _problem(label: str, value: object, marks: tuple[tuple[str, str], ...], why: str) -> str | None:
    # A source formats whatever it is given, so a list or a mapping would reach the SQL as
    # its repr, quotes and all.
    if not isinstance(value, str):
        return f"{label} must be a string"
    for mark, described in marks:
        if mark in value:
            return f"{label} cannot contain {described}: {why}"
    return None


def name_problem(label: str, value: object) -> str | None:
    """Why *value* cannot be a database, collection, table or column name, or None."""
    return _problem(label, value, _NAME_MARKS, "SQL sources quote names without escaping them")


def definition_problem(label: str, value: object) -> str | None:
    """Why *value* cannot be a column's ``type`` or ``misc`` text, or None."""
    return _problem(
        label, value, _DEFINITION_MARKS, "SQL sources insert column definitions as written"
    )


def _names_problem(label: str, value: object) -> str | None:
    """Why *value* cannot be a list of names, or None."""
    if not isinstance(value, list):
        return f"{label} must be a list of strings"
    for index, item in enumerate(cast("list[object]", value)):
        problem = name_problem(f"{label}[{index}]", item)
        if problem:
            return problem
    return None


def _mappings_problem(label: str, value: object, *, empty: bool = True) -> str | None:
    if (
        not isinstance(value, list)
        or not (empty or value)
        or not all(isinstance(item, dict) for item in cast("list[object]", value))
    ):
        return f"{label} must be a {'' if empty else 'non-empty '}list of mappings"
    return None


_FOREIGN_KEY_FIELDS = (
    ("foreign_keys_source_columns", _names_problem),
    ("foreign_keys_target_table", name_problem),
    ("foreign_keys_target_columns", _names_problem),
)


def create_table_problem(attributes: Mapping[str, Any]) -> str | None:
    """The first field in a ``create_table`` call that a source cannot build from, or None.

    ``database`` and ``collection`` may be absent, because the operator supplies defaults,
    and so may ``misc``, its ``primary_key``, its ``foreign_keys`` and a column's ``type``
    and ``misc``. A null ``primary_key`` counts as absent, because every SQL source skips a
    falsy one; any other value that is not a list is refused. Everything else the sources
    read must be present with the shape they format: every source iterates or quotes a null
    foreign-key field, and the PostgreSQL and MySQL sources iterate a null ``foreign_keys``
    where SQLite skips it, so both are refused.
    """
    for key in ("database", "collection"):
        if key in attributes:
            problem = name_problem(key, attributes[key])
            if problem:
                return problem
    table = attributes.get("table")
    problem = name_problem("table", table)
    if problem:
        return problem
    if not cast(str, table).strip():
        return "table must not be blank"
    columns = attributes.get("columns")
    problem = _mappings_problem("columns", columns, empty=False)
    if problem:
        return problem
    for index, column in enumerate(cast("list[dict[str, Any]]", columns)):
        label = f"columns[{index}]"
        problem = name_problem(f"{label}.name", column.get("name"))
        if problem:
            return problem
        if not column["name"]:
            return f"{label}.name must not be empty"
        for key in ("type", "misc"):
            if key in column:
                problem = definition_problem(f"{label}.{key}", column[key])
                if problem:
                    return problem
    if "misc" not in attributes:
        return None
    misc = attributes["misc"]
    if not isinstance(misc, dict):
        return "misc must be a mapping"
    misc = cast("dict[str, Any]", misc)
    if misc.get("primary_key") is not None:
        problem = _names_problem("misc.primary_key", misc["primary_key"])
        if problem:
            return problem
    if "foreign_keys" not in misc:
        return None
    foreign_keys = misc["foreign_keys"]
    problem = _mappings_problem("misc.foreign_keys", foreign_keys)
    if problem:
        return problem
    for index, entry in enumerate(cast("list[dict[str, Any]]", foreign_keys)):
        for key, check in _FOREIGN_KEY_FIELDS:
            label = f"misc.foreign_keys[{index}].{key}"
            if key not in entry:
                return f"{label} is required"
            problem = check(label, entry[key])
            if problem:
                return problem
    return None

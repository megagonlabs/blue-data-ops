from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from decimal import Decimal
from typing import Any, cast

_BACKENDS = {
    ("blue_data.source.sql.postgres.postgres_sql_source", "PostgresDBSource"): "postgres",
    ("blue_data.source.sql.mysql.mysql_sql_source", "MySQLDBSource"): "mysql",
}


def insert_dialect(source: Any) -> str:
    for cls in type(source).__mro__:
        dialect = _BACKENDS.get((cls.__module__, cls.__name__))
        if dialect is not None:
            return dialect
    return "qmark"


def insert_sql(table: str, columns: Sequence[str], dialect: str, *, native: bool = False) -> str:
    quote = "`" if dialect == "mysql" else '"'

    def identifier(name: str) -> str:
        value = str(name).replace(quote, quote * 2)
        if dialect == "postgres":
            value = value.replace("%", "%%")
        return quote + value + quote

    placeholder = "%s" if dialect in ("postgres", "mysql") and not native else "?"
    return (
        f"INSERT INTO {identifier(table)} ({', '.join(map(identifier, columns))}) "
        f"VALUES ({', '.join(placeholder for _ in columns)})"
    )


class _MySQLInsert:
    """Bind native prepared parameters without connector placeholder rewriting."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.statement: Any = None
        self.parameters: Any = None
        self.rowcount: int | None = 0
        self.python_driver = False

    def executemany(self, query: str, rows: list[tuple[Any, ...]]) -> None:
        prepared = self.connection.cmd_stmt_prepare(query.encode(self.connection.python_charset))
        self.python_driver = isinstance(prepared, dict)
        if self.python_driver:
            self.statement = prepared["statement_id"]
            self.parameters = prepared["parameters"]
        else:
            self.statement = prepared
        for row in rows:
            self.connection.cmd_stmt_reset(self.statement)
            if self.python_driver:
                data = row
                if self.connection.charset == "utf8mb3":
                    # The pure protocol encoder does not map MySQL's utf8mb3 alias.
                    data = tuple(
                        str(value).encode(self.connection.python_charset)
                        if isinstance(value, (str, Decimal))
                        else value
                        for value in row
                    )
                result = self.connection.cmd_stmt_execute(
                    self.statement, data=data, parameters=self.parameters
                )
            else:
                result = self.connection.cmd_stmt_execute(self.statement, *row)
            count = (
                cast(dict[str, Any], result).get("affected_rows")
                if isinstance(result, dict)
                else None
            )
            if type(count) is int and count >= 0 and self.rowcount is not None:
                self.rowcount += count
            else:
                self.rowcount = None

    def close(self) -> None:
        if self.statement is not None:
            try:
                self.connection.cmd_stmt_close(self.statement)
            finally:
                self.statement = None
                self.parameters = None


def insert_batch(
    source: Any, database: str, table: str, columns: Sequence[str], rows: list[tuple[Any, ...]]
) -> int | None:
    dialect = insert_dialect(source)
    connection = source._db_connect(database)
    cursor: Any = None
    try:
        native = dialect == "mysql" and any("%s" in str(name) for name in (table, *columns))
        cursor = _MySQLInsert(connection) if native else connection.cursor()
        cursor.executemany(insert_sql(table, columns, dialect, native=native), rows)
        connection.commit()
        try:
            count = cursor.rowcount
        except Exception:
            count = None
        return count if type(count) is int and count >= 0 else None
    except BaseException:
        with suppress(Exception):
            connection.rollback()
        raise
    finally:
        if cursor is not None:
            with suppress(Exception):
                cursor.close()
        with suppress(Exception):
            source._db_disconnect(connection)

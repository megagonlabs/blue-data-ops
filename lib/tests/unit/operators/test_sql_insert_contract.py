from __future__ import annotations

import importlib
from decimal import Decimal
from typing import Any, cast

import pytest

from blue_data_ops.data import RegistrySeam
from blue_data_ops.operators import versioned_registry


class Cursor:
    def __init__(self, connection: Any):
        self.connection = connection
        self.rowcount: int | None = 1

    def executemany(self, query: str, rows: Any):
        c = self.connection
        c.sql.append(query)
        c.rows.extend(rows)
        if c.fail:
            raise ValueError("original insert failure")
        self.rowcount = c.count

    def close(self):
        self.connection.closed_cursor = True
        if self.connection.fail_cleanup:
            raise RuntimeError("cursor close failure")


class Connection:
    charset = "utf8mb4"
    python_charset = "utf8"

    def __init__(self, fail: bool = False, count: int | None = 1, cext: bool = False):
        self.sql: list[str] = []
        self.rows: list[Any] = []
        self.fail = fail
        self.count = count
        self.cext = cext
        self.fail_cleanup = False
        self.commits = self.rollbacks = 0
        self.closed_cursor = self.disconnected = False

    def cursor(self):
        return Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1
        if self.fail_cleanup:
            raise RuntimeError("rollback failure")

    def cmd_stmt_prepare(self, query: bytes):
        self.sql.append(query.decode())
        return object() if self.cext else {"statement_id": 7, "parameters": [("value",)]}

    def cmd_stmt_reset(self, statement: Any):
        pass

    def cmd_stmt_execute(self, statement: Any, *args: Any, **kwargs: Any):
        self.rows.append(args if self.cext else kwargs["data"])
        if self.fail:
            raise ValueError("original insert failure")
        return {"affected_rows": self.count}

    def cmd_stmt_close(self, statement: Any):
        self.closed_cursor = True
        if self.fail_cleanup:
            raise RuntimeError("statement close failure")


class Source:
    def __init__(self, connections: list[Any]):
        self.connections = connections
        self.next = 0

    def _db_connect(self, database: str):
        connection = self.connections[self.next]
        self.next += 1
        return connection

    def _db_disconnect(self, connection: Any):
        connection.disconnected = True
        if connection.fail_cleanup:
            raise RuntimeError("disconnect failure")


class Registry:
    def __init__(self, source: Any):
        self.source = source

    def connect_source(self, source: str):
        return self.source


def source_for(backend: str, connections: list[Any]):
    if backend == "unknown":
        return Source(connections)
    if backend in {"postgres", "mysql"}:
        pytest.importorskip("psycopg2" if backend == "postgres" else "mysql.connector")
    module = importlib.import_module(f"blue_data.source.sql.{backend}.{backend}_sql_source")
    base = getattr(
        module,
        {"sqlite": "SQLiteDBSource", "postgres": "PostgresDBSource", "mysql": "MySQLDBSource"}[
            backend
        ],
    )

    class Derived(Source, base):
        pass

    return Derived(connections)


@pytest.mark.parametrize("version", ["2.0.0", "3.0.0"])
@pytest.mark.parametrize("backend", ["sqlite", "postgres", "mysql", "unknown"])
def test_bound_dialect_identifiers_values_and_identity(version: str, backend: str):
    connection = Connection()
    source = source_for(backend, [connection])
    table = 'select%s"`列%'
    column = 'column%s"`列%'
    payload = [[{column: "value'); DROP TABLE ignored; -- %s"}]]
    output, reported, meta = (
        versioned_registry()
        .resolve("insert_table@" + version)
        .run(
            payload,
            {"source": "demo", "database": "db", "table": table},
            {"data_registry": RegistrySeam(cast(Any, Registry(source)))},
        )
    )
    assert meta.errors == []
    assert output is payload
    assert connection.rows == [(payload[0][0][column],)]
    quote = "`" if backend == "mysql" else '"'

    def ident(name: str) -> str:
        return quote + name.replace(quote, quote * 2) + quote

    marker = "%s" if backend == "postgres" else "?"
    expected = f"INSERT INTO {ident(table)} ({ident(column)}) VALUES ({marker})"
    if backend == "postgres":
        expected = expected[:-4].replace("%", "%%") + "(%s)"
    assert connection.sql == [expected]
    assert connection.commits == 1 and connection.closed_cursor and connection.disconnected
    assert reported == ({"num_rows_insert": 1} if version == "3.0.0" else {})


@pytest.mark.parametrize("backend", ["postgres", "mysql", "unknown"])
@pytest.mark.parametrize("version", ["2.0.0", "3.0.0"])
def test_second_batch_failure_cleanup_and_partial_commit(backend: str, version: str):
    first, second = Connection(), Connection(fail=True)
    second.fail_cleanup = True
    source = source_for(backend, [first, second])
    _, _, meta = (
        versioned_registry()
        .resolve("insert_table@" + version)
        .run(
            [[{"a": 1}, {"a": 2}]],
            {"source": "demo", "database": "db", "table": "t", "batch_size": 1},
            {"data_registry": RegistrySeam(cast(Any, Registry(source)))},
        )
    )
    assert meta.errors
    assert first.commits == 1 and first.rollbacks == 0
    assert second.commits == 0 and second.rollbacks == 1
    assert all(c.closed_cursor and c.disconnected for c in [first, second])


@pytest.mark.parametrize("backend", ["mysql", "postgres", "unknown"])
@pytest.mark.parametrize("count", [None, -1, 0])
def test_unknown_count_is_omitted_and_zero_is_known(backend: str, count: int | None):
    c = Connection(count=count)
    _, reported, meta = (
        versioned_registry()
        .resolve("insert_table@3.0.0")
        .run(
            [[{"a": 1}]],
            {"source": "demo", "database": "db", "table": "t"},
            {"data_registry": RegistrySeam(cast(Any, Registry(source_for(backend, [c]))))},
        )
    )
    assert not meta.errors
    assert reported == ({"num_rows_insert": 0} if count == 0 else {})


@pytest.mark.parametrize("cext", [False, True])
def test_mysql_native_binding_does_not_rewrite_percent_identifiers(cext: bool):
    pytest.importorskip("mysql.connector")
    from mysql.connector.cursor import RE_SQL_FIND_PARAM

    cext_param = getattr(
        importlib.import_module("mysql.connector.cursor_cext"), "RE_SQL_FIND_PARAM"
    )

    from blue_data_ops.data.sql_insert import insert_batch, insert_sql

    table, column = 'a%s"', "b%s`"
    query = insert_sql(table, [column], "mysql")
    expected = insert_sql(table, [column], "mysql", native=True)
    # Both installed connector cursor formatters corrupt this valid identifier.
    assert RE_SQL_FIND_PARAM.sub(b"?", query.encode()) != expected.encode()
    assert cext_param.sub(b"?", query.encode()) != expected.encode()
    c = Connection(cext=cext)
    assert insert_batch(source_for("mysql", [c]), "db", table, [column], [(7,)]) == 1
    assert c.sql == [expected] and c.rows == [(7,)]


def test_installed_postgres_mogrify_preserves_percent_identifiers():
    pytest.importorskip("psycopg2")
    import psycopg2.extensions as extensions

    from blue_data_ops.data.sql_insert import insert_sql

    # No connection initialization or server: mogrify runs the installed C formatter.
    driver = cast(Any, extensions)
    cur = driver.cursor(driver.connection.__new__(driver.connection))
    query = insert_sql('a%s"%', ["列%s%"], "postgres")
    assert cur.mogrify(query, (7,)) == 'INSERT INTO "a%s""%" ("列%s%") VALUES (7)'.encode()


@pytest.mark.parametrize("backend", ["mysql", "postgres", "unknown"])
def test_original_error_survives_cleanup_failures(backend: str):
    from blue_data_ops.data.sql_insert import insert_batch

    c = Connection(fail=True)
    c.fail_cleanup = True
    with pytest.raises(ValueError, match="original insert failure"):
        insert_batch(source_for(backend, [c]), "db", "t", ["a"], [(1,)])
    assert c.rollbacks == 1 and c.closed_cursor and c.disconnected


def test_empty_outcome_does_not_connect():
    source = Source([])
    _, reported, meta = (
        versioned_registry()
        .resolve("insert_table@3.0.0")
        .run(
            [[]],
            {"source": "demo", "database": "db", "table": "t"},
            {"data_registry": RegistrySeam(cast(Any, Registry(source)))},
        )
    )
    assert not meta.errors and reported == {"num_rows_insert": 0}
    assert source.next == 0


@pytest.mark.parametrize("charset_id", [33, 255])
@pytest.mark.parametrize("value", ["bound'); SELECT ignored -- %s", Decimal("12.3400")])
def test_installed_mysql_native_driver_sends_exact_identifier_bytes(
    monkeypatch: pytest.MonkeyPatch,
    charset_id: int,
    value: str | Decimal,
):
    pytest.importorskip("mysql.connector")
    from mysql.connector.connection import MySQLConnection
    from mysql.connector.constants import ServerCmd
    from mysql.connector.protocol import MySQLProtocol

    from blue_data_ops.data.sql_insert import insert_batch, insert_sql

    connection = MySQLConnection()
    connection._character_set.set_mysql_version((8, 4, 0))  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(connection, "_charset_id", charset_id)
    monkeypatch.setattr(connection, "_protocol", MySQLProtocol())
    packets: list[tuple[Any, Any]] = []
    ok = b"\x07\x00\x00\x01\x00\x01\x00\x00\x00\x00\x00"
    prepare_ok = b"\x0c\x00\x00\x01\x00\x07\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"

    def send(command: Any, argument: Any = None, packet: Any = None, **kwargs: Any):
        packets.append((command, argument if argument is not None else packet))
        return prepare_ok if command == ServerCmd.STMT_PREPARE else ok

    monkeypatch.setattr(connection, "_send_cmd", send)
    real_prepare = connection.cmd_stmt_prepare

    def prepare(query: bytes):
        result: dict[str, Any] = dict(real_prepare(query))
        # Synthetic server metadata for the one value; no socket or server is used.
        result["parameters"] = [("value",)]
        return result

    monkeypatch.setattr(connection, "cmd_stmt_prepare", prepare)
    source = source_for("mysql", [connection])
    disconnected: list[Any] = []
    monkeypatch.setattr(source, "_db_disconnect", disconnected.append)
    assert insert_batch(source, "db", 'a%s"`列%', ['b%s"`列%'], [(value,)]) == 1
    expected = insert_sql('a%s"`列%', ['b%s"`列%'], "mysql", native=True).encode()
    assert packets[0] == (ServerCmd.STMT_PREPARE, expected)
    execute_packet = next(
        packet for command, packet in packets if command == ServerCmd.STMT_EXECUTE
    )
    assert str(value).encode() in execute_packet
    assert str(value).encode() not in expected
    assert any(command == ServerCmd.STMT_CLOSE for command, _packet in packets)
    assert disconnected == [connection]


@pytest.mark.parametrize("backend", ["mysql", "postgres", "unknown"])
@pytest.mark.parametrize("cext", [False, True])
def test_committed_insert_stays_successful_if_cleanup_fails(backend: str, cext: bool):
    from blue_data_ops.data.sql_insert import insert_batch

    connection = Connection(cext=cext)
    connection.fail_cleanup = True
    assert insert_batch(source_for(backend, [connection]), "db", "t", ["a"], [(1,)]) == 1
    assert connection.commits == 1 and connection.rollbacks == 0
    assert connection.closed_cursor and connection.disconnected


def test_mysql_ordinary_names_use_driver_cursor_batching():
    from blue_data_ops.data.sql_insert import insert_batch

    connection = Connection()
    assert (
        insert_batch(source_for("mysql", [connection]), "db", "orders", ["id"], [(1,), (2,)]) == 1
    )
    assert connection.sql == ["INSERT INTO `orders` (`id`) VALUES (%s)"]
    assert connection.rows == [(1,), (2,)]


@pytest.mark.parametrize("charset", ["utf8mb3", "utf8mb4"])
def test_mysql_native_identifiers_use_driver_python_charset(charset: str):
    from blue_data_ops.data.sql_insert import insert_batch

    connection = Connection()
    connection.charset = charset
    assert insert_batch(source_for("mysql", [connection]), "db", "orders%s", ["列"], [(1,)]) == 1
    assert connection.sql == ["INSERT INTO `orders%s` (`列`) VALUES (?)"]


def test_native_statement_is_released_before_connection_disconnect(monkeypatch: pytest.MonkeyPatch):
    from blue_data_ops.data.sql_insert import insert_batch

    disposed_after_disconnect: list[bool] = []
    connection = Connection(cext=True)

    class Statement:
        def __del__(self):
            disposed_after_disconnect.append(connection.disconnected)

    def prepare(query: bytes):
        connection.sql.append(query.decode())
        return Statement()

    monkeypatch.setattr(connection, "cmd_stmt_prepare", prepare)
    assert insert_batch(source_for("mysql", [connection]), "db", "orders%s", ["id"], [(1,)]) == 1
    assert disposed_after_disconnect == [False]

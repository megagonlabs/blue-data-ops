from __future__ import annotations

import importlib
import importlib.util
import sqlite3
from typing import Any

import pytest

from tests.optional_integrations import require_optional
from tests.unit.data.test_sql_diagnostics import MARKER, Raising


def query_schema_failure(error: BaseException) -> bool:
    if importlib.util.find_spec("blue_data_ops.data.sql_errors") is None:
        return False
    module = importlib.import_module("blue_data_ops.data.sql_errors")
    return bool(vars(module)["query_schema_failure"](error))


@pytest.mark.parametrize(
    "name,message",
    [
        ("InvalidCatalogName", "database does not exist"),
        ("IntegrityError", "database constraint rejected the operation"),
    ],
)
def test_additional_genuine_postgres(name: str, message: str) -> None:
    require_optional("psycopg2")
    module = importlib.import_module("psycopg2" if name == "IntegrityError" else "psycopg2.errors")
    assert module.__file__ and "site-packages/psycopg2/" in module.__file__
    error = vars(module)[name](MARKER)
    record = Raising(error).run([[]], {})[2].errors[0]
    assert record.message == message and record.retryable is False


@pytest.mark.parametrize("code", ["23505", "unmapped", True, 1])
def test_contradictory_or_malformed_pgcode_generic(code: Any) -> None:
    require_optional("psycopg2")
    module = importlib.import_module("psycopg2.errors")
    base: Any = module.SyntaxError

    class Contradictory(base):
        @property
        def pgcode(self) -> Any:
            return code

    record = Raising(Contradictory(MARKER)).run([[]], {})[2].errors[0]
    assert record.message == "operator execution failed"


@pytest.mark.parametrize("code", [None, True, 8, 14, 23, 999])
def test_sqlite_unknown_access_and_readonly_not_schema(code: Any) -> None:
    error: Any = sqlite3.OperationalError(MARKER)
    if code is not None:
        error.sqlite_errorcode = code
    assert query_schema_failure(error) is False


def test_real_sqlite_extended_constraints_and_unknown_function() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO records VALUES (1, 'ordinary')")
        for query in (
            "INSERT INTO records VALUES (1, 'duplicate')",
            "INSERT INTO records VALUES (2, NULL)",
        ):
            with pytest.raises(sqlite3.IntegrityError) as captured:
                connection.execute(query)
            assert captured.value.sqlite_errorcode & 0xFF == sqlite3.SQLITE_CONSTRAINT
            record = Raising(captured.value).run([[]], {})[2].errors[0]
            assert record.message == "database constraint rejected the operation"
        with pytest.raises(sqlite3.OperationalError) as missing_function:
            connection.execute("SELECT synthetic_unknown_function(id) FROM records")
        assert missing_function.value.sqlite_errorcode == 1
        assert query_schema_failure(missing_function.value)
    finally:
        connection.close()

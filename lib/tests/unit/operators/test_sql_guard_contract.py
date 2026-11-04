from __future__ import annotations

from typing import Any

import pytest

from blue_data_ops.llm import LLMError
from tests.unit.operators.test_nl2sql_security import TARGET, Host, execute
from tests.unit.operators.test_nl2sql_security import host as sql_host

host = sql_host

BLOCKED = [
    {"op": "SQL.QUERY", "query": "SELECT 1"},
    {"op": "SQL.FETCH_ALL"},
    None,
    1,
    "",
    "SELECTED 1",
    "SELECTé 1",
    "ſELECT 1",
    "SQL.FETCH_ALL",
    "DELETE FROM records",
    "SELECT 1; SELECT 2",
    "SELECT 1;;",
    "SELECT 1 INTO OUTFILE '/synthetic/unused'",
    "SELECT 1e0INTO OUTFILE '/synthetic/unused'",
    "SELECT 1.e0INTO OUTFILE '/synthetic/unused'",
    "SELECT 1.5INTO OUTFILE '/synthetic/unused'",
    "SELECT .1INTO OUTFILE '/synthetic/unused'",
    "SELECT 1e+1INTO DUMPFILE '/synthetic/unused'",
    "SELECT id FROM records WHERE id=1e0INTO OUTFILE '/synthetic/unused'",
    "SELECT 1into OUTFILE '/synthetic/unused'",
    "SELECT 1 --1 INTO OUTFILE '/synthetic/unused'",
    "SELECT 1 # INTO OUTFILE '/synthetic/unused'",
    "SELECT 1 FROM orders -- x\r'\nINTO OUTFILE '/tmp/pwn.csv' -- '",
    "SELECT 1 AS n -- comment\r",
    "SELECT 1 AS n --\rtrailing",
    "SELECT 1 AS n -- comment\rmore",
    "SELECT 1 AS n -- comment\r\r\n",
    "SELECT 1 /* outer /* nested */ INTO x */",
    "SELECT 1 /*! INTO OUTFILE '/synthetic/unused' */",
    "SELECT 1 /*!50000 INTO x */",
    "SELECT 1 /*M! INTO x */",
    "SELECT 'a\\' INTO x -- '",
    'SELECT "a\\" INTO x -- "',
    "SELECT $$ INTO x $$",
    "SELECT 1 INTO @x",
    "SELECT * FROM records INTO x",
    "SELECT (SELECT 1 INTO x)",
    "SELECT 1 UNION SELECT 2 INTO x",
    "SELECT 1 INTO/**/OUTFILE '/synthetic/unused'",
    "SELECT 1\0",
    "SELECT\v1 INTO x",
    "SELECT\f1",
    "SELECT 'unterminated",
    "SELECT `unterminated",
    "SELECT /* unterminated",
    "SELECT [INTO] FROM records",
]


@pytest.mark.parametrize("query", BLOCKED)
@pytest.mark.parametrize("version", [None, "1.0.0", "2.0.0", "3.0.0", "4.0.0"])
def test_public_guard_rejects_before_driver(
    host: Host, monkeypatch: pytest.MonkeyPatch, query: Any, version: str | None
):
    import sqlite3

    entries: list[object] = []

    def forbidden(*args: Any, **kwargs: Any):
        entries.append(args)
        raise AssertionError("driver entered")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    with pytest.raises(LLMError) as error:
        if version is None:
            host[2].execute(query, TARGET)
        else:
            execute(host[2], query, version)
    assert error.value.code == "sql_query_rejected"
    assert entries == []


@pytest.mark.parametrize(
    "query",
    [
        "SELECT 1 AS n",
        " \t\nselect 1 AS n;",
        "SELECT 'INTO -- # /* words */' AS n",
        "SELECT 1 /* ordinary comment */ AS n",
        "SELECT 1 AS n -- comment\n",
        "SELECT 1 AS n -- comment",
        "SELECT 1 AS n -- comment\r\n",
        "SELECT 1 AS n --\r\n",
        "SELECT 'line\rbreak' AS n",
        "SELECT 1 AS `a``b`",
        'SELECT 1 AS "a""b"',
        "SELECT X'41' AS n",
        "SELECT 1.5 AS n",
        "SELECT 1.e0 AS n",
        "SELECT 1 AS `1.e0INTO`",
        "SELECT 1e+1 AS n",
        "SELECT 1 AS `1e0INTO`",
        "SELECT 'a''INTO' AS n",
    ],
)
def test_ordinary_select_still_executes(host: Host, query: str):
    assert len(host[2].execute(query, TARGET)) == 1


def test_string_subclass_is_refused(host: Host):
    class Query(str):
        pass

    with pytest.raises(LLMError) as error:
        host[2].execute(Query("SELECT 1"), TARGET)
    assert error.value.code == "sql_query_rejected"


@pytest.mark.parametrize(
    "query",
    [
        "SELECT N'INTO'",
        "SELECT B'0101'",
        "SELECT _utf8'INTO'",
        "SELECT 'INTO;'",
        "SELECT 1; /* trailing */",
    ],
)
def test_guard_recognizes_literals_without_hiding_tokens(query: str):
    from blue_data_ops.llm.sql_guard import is_read_query

    assert is_read_query(query)

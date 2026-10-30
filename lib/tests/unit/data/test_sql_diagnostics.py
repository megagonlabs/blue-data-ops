from __future__ import annotations

import hashlib
import importlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from blue_data.registry.data_registry import DataRegistry  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.json.memory_json_source import MemoryJSONSource  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource  # pyright: ignore[reportMissingTypeStubs]

from blue_data_ops.llm import LLMClient
from blue_data_ops.llm.errors import LLMError
from blue_data_ops.llm.sql_execution import ReadOnlySQLExecutor
from blue_data_ops.operators import Operator, active_registry, versioned_registry
from blue_data_ops.operators.types import Attributes, DataBundle, Properties

MARKER = "SYNTHETIC_PRIVATE_DATABASE_DETAIL"


class Reply(LLMClient):
    def __init__(self) -> None:
        self.calls = 0

    def execute_api_call(
        self,
        input: Any,
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        self.calls += 1
        return {"query": "SELECT id FROM people"}


class Raising(Operator):
    name = "sql_diagnostic_probe"
    description = "Local database exception fixture."
    attributes = {}

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def apply(
        self, input_data: DataBundle, attributes: Attributes, properties: Properties | None = None
    ) -> DataBundle:
        raise self.error


@pytest.fixture
def host(tmp_path: Path) -> tuple[Any, Any]:
    with sqlite3.connect(tmp_path / "shop.db") as conn:
        conn.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO people VALUES (1, 'ordinary')")
    registry = DataRegistry(store=MemoryJSONSource(), rebuild=False)
    source = SQLiteDBSource(
        "local", properties={"connection": {"database_directory": str(tmp_path)}}
    )
    registry.register_source(source)
    registry.sync_source("local", recursive=True)
    return registry, source


def snapshot(root: Path) -> list[tuple[str, int, str]]:
    return [
        (
            p.relative_to(root).as_posix(),
            p.stat().st_mode,
            hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "directory",
        )
        for p in sorted(root.rglob("*"))
    ]


def attrs() -> Attributes:
    return {
        "source": "local",
        "database": "shop",
        "collection": "public",
        "protocol": "sqlite",
        "question": "list people",
    }


@pytest.mark.parametrize(
    "field,message",
    [
        ("database", "database is not available in the declared source"),
        ("collection", "collection is not available in the declared database"),
    ],
)
def test_generation_negative_proof_no_effects(
    host: tuple[Any, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    message: str,
) -> None:
    registry, source = host

    def deny(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("generation attempted backend enumeration or connection")

    for name in (
        "fetch_databases",
        "fetch_database_collections",
        "_get_database_directory",
        "_db_connect",
    ):
        monkeypatch.setattr(source, name, deny)
    before = snapshot(tmp_path)
    records = json.dumps(registry.list_source_databases("local"), sort_keys=True)
    client = Reply()
    result = (
        active_registry()
        .resolve("nl2sql@3.0.0")
        .run([[]], {**attrs(), field: MARKER}, {"data_registry": registry, "llm_client": client})
    )
    assert snapshot(tmp_path) == before
    assert json.dumps(registry.list_source_databases("local"), sort_keys=True) == records
    assert client.calls == 0
    error = result[2].errors[0]
    assert error.message == message and error.suggestion
    assert MARKER not in json.dumps(error._asdict())


@pytest.mark.parametrize(
    "identity,structured",
    [
        ("nl2sql@1.0.0", False),
        ("nl2sql@2.0.0", False),
        ("nl2sql@2.0.0", True),
        ("nl2sql@3.0.0", False),
    ],
)
def test_legacy_and_raw_target_control(
    host: tuple[Any, Any], identity: str, structured: bool
) -> None:
    registry, _ = host
    op = versioned_registry().resolve(identity)
    client = Reply()
    call: Any = op.run if structured else op.apply
    result: Any = call(
        [[]], {**attrs(), "database": MARKER}, {"data_registry": registry, "llm_client": client}
    )
    assert client.calls == 1
    if structured:
        assert not result[2].errors


@pytest.mark.parametrize("name", ["fresh.db", "fresh.sqlite"])
def test_stale_registry_new_live_name_control(
    host: tuple[Any, Any], tmp_path: Path, name: str
) -> None:
    registry, _ = host
    (tmp_path / name).touch()
    client = Reply()
    before = snapshot(tmp_path)
    result = (
        active_registry()
        .resolve("nl2sql@3.0.0")
        .run(
            [[]],
            {**attrs(), "database": "fresh"},
            {"data_registry": registry, "llm_client": client},
        )
    )
    assert client.calls == 1 and not result[2].errors
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize(
    "identity", ["insert_table@2.0.0", "insert_table@3.0.0", "create_table@2.0.0"]
)
def test_write_missing_database(host: tuple[Any, Any], identity: str) -> None:
    registry, _ = host
    result = (
        versioned_registry()
        .resolve(identity)
        .run(
            [[{"id": 2}]],
            {
                "source": "local",
                "database": MARKER,
                "table": "people",
                "columns": [{"name": "id", "type": "INTEGER"}],
            },
            {"data_registry": registry},
        )
    )
    error = result[2].errors[0]
    assert error.message == "database does not exist"
    assert error.suggestion == "Check the declared database or create it before this operation."
    assert MARKER not in json.dumps(error._asdict())


@pytest.mark.parametrize(
    "module,names,message",
    [
        (
            "psycopg2.errors",
            ["UniqueViolation", "NotNullViolation"],
            "database constraint rejected the operation",
        ),
        (
            "psycopg2.errors",
            ["UndefinedTable", "UndefinedColumn", "SyntaxError"],
            "database query or operation failed",
        ),
        ("psycopg2.errors", ["InsufficientPrivilege"], "database connection or access failed"),
        (
            "psycopg2",
            ["OperationalError", "InterfaceError"],
            "database connection or access failed",
        ),
    ],
)
def test_genuine_postgres_conditions(module: str, names: list[str], message: str) -> None:
    loaded = importlib.import_module(module)
    assert loaded.__file__ and "site-packages/psycopg2/" in loaded.__file__
    for name in names:
        error = vars(loaded)[name](MARKER)
        assert error.pgcode is None
        record = Raising(error).run([[]], {})[2].errors[0]
        assert record.message == message and record.retryable is False
        assert MARKER not in json.dumps(record._asdict())


@pytest.mark.parametrize(
    "errno,message",
    [
        (1049, "database does not exist"),
        *[(n, "database constraint rejected the operation") for n in (1062, 1048, 1451, 1452)],
        *[(n, "database query or operation failed") for n in (1146, 1054, 1064)],
        *[
            (n, "database connection or access failed")
            for n in (1044, 1045, 1142, 1143, 2002, 2003, 2005, 2006, 2013)
        ],
    ],
)
def test_mysql_errno_beats_contradictory_subclass(errno: int, message: str) -> None:
    module = importlib.import_module("mysql.connector")
    assert module.__file__ and "site-packages/mysql/connector/" in module.__file__
    error = module.ProgrammingError(MARKER, errno=errno, sqlstate="23000")
    record = Raising(error).run([[]], {})[2].errors[0]
    assert record.message == message and record.retryable is False
    assert MARKER not in json.dumps(record._asdict())


@pytest.mark.parametrize("errno", [True, 99999, 0])
def test_mysql_unknown_metadata_generic(errno: Any) -> None:
    module = importlib.import_module("mysql.connector")
    error = module.ProgrammingError(MARKER, errno=errno, sqlstate="42000")
    assert Raising(error).run([[]], {})[2].errors[0].message == "operator execution failed"


@pytest.mark.parametrize(
    "query", ["SELECT absent FROM people", "SELECT * FROM absent", "SELECT FROM people"]
)
def test_host_query_schema_distinction(host: tuple[Any, Any], query: str) -> None:
    registry, _ = host
    executor = ReadOnlySQLExecutor(registry, frozenset({("local", "shop", "public")}))
    with pytest.raises(LLMError) as captured:
        executor.execute(query, ("local", "shop", "public"))
    record = Raising(captured.value).run([[]], {})[2].errors[0]
    assert record.message == "generated SQL failed against the approved schema"
    assert record.suggestion and "schema" in record.suggestion


@pytest.mark.parametrize(
    "directory", [None, 1, "", "nul\x00directory", "absent-directory", "regular-file"]
)
def test_unavailable_directory_is_inconclusive_without_creation(
    host: tuple[Any, Any],
    tmp_path: Path,
    directory: Any,
) -> None:
    registry, source = host
    if directory == "absent-directory":
        directory = str(tmp_path / "must-stay-absent")
    elif directory == "regular-file":
        regular = tmp_path / "regular-file"
        regular.write_text("ordinary")
        directory = str(regular)
    source.properties["connection"]["database_directory"] = directory
    before = snapshot(tmp_path)
    client = Reply()
    result = (
        active_registry()
        .resolve("nl2sql@3.0.0")
        .run(
            [[]], {**attrs(), "database": MARKER}, {"data_registry": registry, "llm_client": client}
        )
    )
    assert client.calls == 1 and not result[2].errors
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("peers", [[], None, {}, [None], [{"name": ""}], [{"name": 1}]])
def test_malformed_or_empty_metadata_not_absence(
    host: tuple[Any, Any],
    monkeypatch: pytest.MonkeyPatch,
    peers: Any,
) -> None:
    registry, _ = host

    def peer_records(*args: Any) -> Any:
        return peers

    monkeypatch.setattr(registry, "list_source_databases", peer_records)
    client = Reply()
    result = (
        active_registry()
        .resolve("nl2sql@3.0.0")
        .run(
            [[]], {**attrs(), "database": MARKER}, {"data_registry": registry, "llm_client": client}
        )
    )
    assert client.calls == 1 and not result[2].errors


@pytest.mark.parametrize(
    "filename,target",
    [("new.db", "new"), ("new.sqlite", "new"), ("new.DB", "new"), ("new.db", "NEW")],
)
def test_name_suffix_and_case_semantics(
    host: tuple[Any, Any],
    tmp_path: Path,
    filename: str,
    target: str,
) -> None:
    registry, _ = host
    (tmp_path / filename).touch()
    client = Reply()
    result = (
        active_registry()
        .resolve("nl2sql@3.0.0")
        .run(
            [[]], {**attrs(), "database": target}, {"data_registry": registry, "llm_client": client}
        )
    )
    live = filename in {"new.db", "new.sqlite"} and target == "new"
    assert client.calls == int(live)
    assert bool(result[2].errors) is (not live)


def test_no_result_query_and_empty_database_control(host: tuple[Any, Any], tmp_path: Path) -> None:
    registry, _ = host
    executor = ReadOnlySQLExecutor(registry, frozenset({("local", "shop", "public")}))
    assert executor.execute("SELECT * FROM people WHERE id = -1", ("local", "shop", "public")) == []
    (tmp_path / "empty.db").touch()
    client = Reply()
    result = (
        active_registry()
        .resolve("nl2sql@3.0.0")
        .run(
            [[]],
            {**attrs(), "database": "empty"},
            {"data_registry": registry, "llm_client": client},
        )
    )
    assert client.calls == 1 and not result[2].errors


def test_foreign_driver_name_errno_pgcode_stays_generic() -> None:
    for module, name, fields in [
        ("psycopg2.errors", "UniqueViolation", {"pgcode": "23505"}),
        ("mysql.connector", "IntegrityError", {"errno": 1062, "sqlstate": "23000"}),
        ("sqlite3", "OperationalError", {"sqlite_errorcode": 1}),
    ]:
        cls = type(name, (Exception,), {"__module__": module, **fields})
        record = Raising(cls(MARKER)).run([[]], {})[2].errors[0]
        assert record.message == "operator execution failed"


@pytest.mark.parametrize("kind", ["postgres", "mysql", "sqlite-subclass", "foreign"])
def test_generation_never_enumerates_other_source_types(
    host: tuple[Any, Any],
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    registry, _ = host
    if kind in {"postgres", "mysql"}:
        module_name, class_name = {
            "postgres": ("blue_data.source.sql.postgres.postgres_sql_source", "PostgresDBSource"),
            "mysql": ("blue_data.source.sql.mysql.mysql_sql_source", "MySQLDBSource"),
        }[kind]
        module = importlib.import_module(module_name)
        source: Any = object.__new__(vars(module)[class_name])
    else:
        base: Any = SQLiteDBSource if kind == "sqlite-subclass" else object

        class Hostile(base):
            def __getattribute__(self, name: str) -> Any:
                raise AssertionError("nonexact source accessor used")

        source = object.__new__(Hostile)

    def deny(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("remote or subclass enumeration or connection used")

    if kind in {"postgres", "mysql"}:
        for name in ("fetch_databases", "fetch_database_collections", "_connect", "execute_query"):
            monkeypatch.setattr(source, name, deny)
    registry.sources["local"] = source

    def schema(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(registry, "get_data_source_schema", schema)
    client = Reply()
    result = (
        active_registry()
        .resolve("nl2sql@3.0.0")
        .run(
            [[]], {**attrs(), "database": MARKER}, {"data_registry": registry, "llm_client": client}
        )
    )
    assert client.calls == 1 and not result[2].errors

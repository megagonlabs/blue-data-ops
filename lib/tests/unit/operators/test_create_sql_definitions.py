"""Names and column text that would change the SQL a source builds are refused up front.

The SQLite cases run against a real temporary database. PostgreSQL and MySQL run the
sources' own ``CREATE`` builders over a connection that records each statement instead of
sending it, so no server is needed.
"""

# blue-data ships no py.typed; the narrow ignores below cover only its imports and the
# private connection hooks these tests replace.

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from pydantic import create_model

blue_data = pytest.importorskip("blue_data")

from blue_data.registry.data_registry import (  # noqa: E402  # pyright: ignore[reportMissingTypeStubs]
    DataRegistry,
)
from blue_data.source.sql.sqlite.sqlite_sql_source import (  # noqa: E402  # pyright: ignore[reportMissingTypeStubs]
    SQLiteDBSource,
)

from blue_data_ops.data import RegistrySeam  # noqa: E402
from blue_data_ops.operators import versioned_registry  # noqa: E402
from blue_data_ops.operators._coercion import coerce_flag  # noqa: E402
from blue_data_ops.operators._sql_definitions import create_table_problem  # noqa: E402
from blue_data_ops.operators.create_database_operator import (  # noqa: E402
    CreateDatabaseOperator,
)
from blue_data_ops.operators.create_table_operator import CreateTableOperator  # noqa: E402
from blue_data_ops.operators.types import ErrorCode  # noqa: E402
from blue_data_ops.utils.type_utils import validate_parameter_type  # noqa: E402
from tests.doubles.data import RegistrySeamDouble  # noqa: E402

INPUT: list[list[dict[str, Any]]] = [[]]
LEGITIMATE_COLUMNS: list[dict[str, Any]] = [
    {"name": "id", "type": "INTEGER"},
    {"name": "code", "type": "VARCHAR(20)", "misc": "NOT NULL DEFAULT 'x'"},
    {"name": "price", "type": "NUMERIC(10,2)"},
    {"name": "prénom", "type": "TEXT"},
]


def table_attributes(**changes: Any) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "source": "src",
        "database": "db",
        "collection": "public",
        "table": "orders",
        "columns": [dict(column) for column in LEGITIMATE_COLUMNS],
    }
    attributes.update(changes)
    return attributes


def column(**fields: Any) -> list[dict[str, Any]]:
    return [{"name": "id", "type": "INTEGER"}, fields]


def foreign_key(**changes: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "foreign_keys_source_columns": ["id"],
        "foreign_keys_target_table": "customers",
        "foreign_keys_target_columns": ["id"],
    }
    entry.update(changes)
    return {"foreign_keys": [entry]}


REFUSED: list[tuple[dict[str, Any], str]] = [
    ({"table": 'y"(id int); DELETE FROM other; --'}, "table cannot contain a double quote"),
    ({"table": "y`; DELETE FROM other"}, "table cannot contain a backtick"),
    ({"table": "y; z"}, "table cannot contain a semicolon"),
    ({"table": "y\x00"}, "table cannot contain a NUL character"),
    ({"collection": 'public"."other'}, "collection cannot contain a double quote"),
    ({"database": "db`; DROP DATABASE prod"}, "database cannot contain a backtick"),
    ({"columns": column(name='a" int); DELETE FROM other; --')}, "columns[1].name"),
    ({"columns": column(name="b", type="int); DELETE FROM other")}, "columns[1].type"),
    ({"columns": column(name="b", type="int /* hidden */")}, "columns[1].type"),
    ({"columns": column(name="b", misc="NOT NULL -- trailing")}, "columns[1].misc"),
    ({"columns": column(name="b", misc="NULL); DELETE FROM other")}, "columns[1].misc"),
    (
        {"misc": foreign_key(foreign_keys_target_table='c"(id); DELETE FROM other; --')},
        "misc.foreign_keys[0].foreign_keys_target_table cannot contain a double quote",
    ),
    (
        {"misc": foreign_key(foreign_keys_target_columns=['id"); DELETE FROM other; --'])},
        "misc.foreign_keys[0].foreign_keys_target_columns[0] cannot contain a double quote",
    ),
    # A source formats any value into its SQL, so a list or mapping arrives as its repr.
    (
        {"columns": column(name=['x" int); DELETE FROM victim; --'], type="INTEGER")},
        "columns[1].name must be a string",
    ),
    ({"columns": column(name={"x": 'y" int); DELETE FROM victim; --'})}, "columns[1].name"),
    ({"columns": column(name="b", type=["int); DELETE FROM victim"])}, "columns[1].type"),
    ({"columns": column(name="b", misc={"x": "); DELETE FROM victim"})}, "columns[1].misc"),
    ({"columns": {"name": "id"}}, "columns must be a non-empty list of mappings"),
    ({"columns": [["id", "INTEGER"]]}, "columns must be a non-empty list of mappings"),
    ({"table": ['y"; DELETE FROM victim; --']}, "table must be a string"),
    ({"collection": {"x": 'p"; DELETE FROM victim'}}, "collection must be a string"),
    ({"database": ["db"]}, "database must be a string"),
    ({"misc": [{"primary_key": ["id"]}]}, "misc must be a mapping"),
    ({"misc": {"primary_key": "id"}}, "misc.primary_key must be a list of strings"),
    ({"misc": {"primary_key": [["id"]]}}, "misc.primary_key[0] must be a string"),
    ({"misc": {"foreign_keys": {"x": 1}}}, "misc.foreign_keys must be a list of mappings"),
    (
        {"misc": foreign_key(foreign_keys_target_table=['c"; DELETE FROM victim; --'])},
        "misc.foreign_keys[0].foreign_keys_target_table must be a string",
    ),
    (
        {"misc": foreign_key(foreign_keys_target_columns="id")},
        "misc.foreign_keys[0].foreign_keys_target_columns must be a list of strings",
    ),
    (
        {"misc": foreign_key(foreign_keys_source_columns=[["id"]])},
        "misc.foreign_keys[0].foreign_keys_source_columns[0] must be a string",
    ),
]
REFUSED_IDS = [
    "table-quote",
    "table-backtick",
    "table-semicolon",
    "table-nul",
    "collection-quote",
    "database-backtick",
    "column-name",
    "column-type-semicolon",
    "column-type-comment",
    "column-misc-comment",
    "column-misc-semicolon",
    "fk-target-table",
    "fk-target-column",
    "column-name-list",
    "column-name-dict",
    "column-type-list",
    "column-misc-dict",
    "columns-dict",
    "column-entry-list",
    "table-list",
    "collection-dict",
    "database-list",
    "misc-list",
    "pk-string",
    "pk-nested-list",
    "fk-dict",
    "fk-target-table-list",
    "fk-target-columns-string",
    "fk-source-columns-nested",
]


class _RecordingSeam(RegistrySeamDouble, RegistrySeam):
    """The recording double, typed as a RegistrySeam so injection resolves it."""


class _Cursor:
    def __init__(self, statements: list[str], existing: bool) -> None:
        self.statements = statements
        self.existing = existing

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def execute(self, statement: str, parameters: object = None) -> None:
        self.statements.append(statement)

    def fetchone(self) -> tuple[str] | None:
        return ("orders",) if self.existing else None

    def close(self) -> None:
        pass


class _Connection:
    """Records what a source would send to its server, and answers whether a table exists."""

    def __init__(self, existing: bool = False) -> None:
        self.statements: list[str] = []
        self.autocommit = False
        self.existing = existing

    def cursor(self) -> _Cursor:
        return _Cursor(self.statements, self.existing)

    def commit(self) -> None:
        pass


def _source_type(backend: str) -> type[Any]:
    """The SDK's own source class; its module imports the driver, which bare installs lack."""
    if backend == "postgres":
        pytest.importorskip("psycopg2")
        from blue_data.source.sql.postgres.postgres_sql_source import (  # pyright: ignore[reportMissingTypeStubs]
            PostgresDBSource,
        )

        return PostgresDBSource
    pytest.importorskip("mysql.connector")
    from blue_data.source.sql.mysql.mysql_sql_source import (  # pyright: ignore[reportMissingTypeStubs]
        MySQLDBSource,
    )

    return MySQLDBSource


def _offline(backend: str, existing: bool = False) -> tuple[Any, _Connection]:
    """A real SQL source whose connections are recorded rather than opened."""
    connection = _Connection(existing)

    def connect(database: str) -> _Connection:
        return connection

    def disconnect(opened: _Connection) -> None:
        pass

    def databases() -> list[str]:
        return []

    source: Any = object.__new__(_source_type(backend))
    source.properties = {"connection": {}}
    source.connection = connection
    source._db_connect = connect
    source._db_disconnect = disconnect
    source.fetch_databases = databases
    return source, connection


class _ForwardingSeam(_RecordingSeam):
    """Records each call, then hands the create calls to one SQL source as the registry does."""

    def __init__(self, source: Any) -> None:
        super().__init__()
        self.sql = source

    def create_source_database(self, *args: Any, **kwargs: Any) -> None:
        super().create_source_database(*args, **kwargs)
        call = self.calls_to("create_source_database")[-1]
        self.sql.create_database(call["database"], call["properties"], call["overwrite"])

    def create_source_database_collection_entity(self, *args: Any, **kwargs: Any) -> None:
        super().create_source_database_collection_entity(*args, **kwargs)
        call = self.calls_to("create_source_database_collection_entity")[-1]
        self.sql.create_database_collection_entity(
            call["database"],
            call["collection"],
            call["entity"],
            properties=call["creation_properties"],
            overwrite=call["overwrite"],
        )


def _invalid_input(meta: Any) -> str:
    [error] = meta.errors
    assert error.code == ErrorCode.INVALID_INPUT
    assert isinstance(error.suggestion, str)
    return error.suggestion


# ------------------------------------------------------------------ the rule --
@pytest.mark.parametrize(("changes", "expected"), REFUSED, ids=REFUSED_IDS)
def test_a_breaking_name_or_definition_is_named(changes: dict[str, Any], expected: str) -> None:
    problem = create_table_problem(table_attributes(**changes))
    assert problem is not None
    assert expected in problem


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"table": "order lines"},
        {"table": "Bestellungen_ü"},
        {"collection": "sales-2026"},
        {"columns": column(name="first name", type="VARCHAR(20)")},
        {"columns": column(name="名前", type="TEXT", misc='CHECK (length("名前") > 0)')},
        {"columns": column(name="total", type="DECIMAL(12, 4)", misc="NOT NULL DEFAULT 0")},
        {"columns": column(name="note", misc="DEFAULT 'it''s fine'")},
        {"misc": {"primary_key": ["id"], **foreign_key()}},
        {"misc": {"primary_key": None, "foreign_keys": []}},
        {"misc": {}},
    ],
)
def test_ordinary_definitions_pass(changes: dict[str, Any]) -> None:
    assert create_table_problem(table_attributes(**changes)) is None


def test_absent_optional_fields_are_left_to_the_defaults() -> None:
    assert create_table_problem({"table": "t", "columns": [{"name": "id"}]}) is None


# A SQL source drops an existing table before it builds the new definition, and SQLite and
# MySQL commit that drop at once, so with overwrite set, anything they cannot build can
# cost the table.
UNBUILDABLE: list[tuple[dict[str, Any], str]] = [
    ({"misc": {"foreign_keys": None}}, "misc.foreign_keys must be a list of mappings"),
    (
        {"misc": foreign_key(foreign_keys_source_columns=None)},
        "misc.foreign_keys[0].foreign_keys_source_columns must be a list of strings",
    ),
    (
        {"misc": foreign_key(foreign_keys_target_table=None)},
        "misc.foreign_keys[0].foreign_keys_target_table must be a string",
    ),
    (
        {"misc": foreign_key(foreign_keys_target_columns=None)},
        "misc.foreign_keys[0].foreign_keys_target_columns must be a list of strings",
    ),
    (
        {"misc": {"foreign_keys": [{"foreign_keys_source_columns": ["id"]}]}},
        "misc.foreign_keys[0].foreign_keys_target_table is required",
    ),
    ({"misc": {"primary_key": "id"}}, "misc.primary_key must be a list of strings"),
    ({"columns": []}, "columns must be a non-empty list of mappings"),
    ({"columns": None}, "columns must be a non-empty list of mappings"),
    ({"columns": [{"type": "INTEGER"}]}, "columns[0].name must be a string"),
    ({"columns": [{"name": ""}]}, "columns[0].name must not be empty"),
    ({"table": None}, "table must be a string"),
    ({"table": "  "}, "table must not be blank"),
]
UNBUILDABLE_IDS = [
    "fk-null",
    "fk-source-null",
    "fk-target-table-null",
    "fk-target-columns-null",
    "fk-field-missing",
    "pk-string",
    "columns-empty",
    "columns-null",
    "column-unnamed",
    "column-name-empty",
    "table-null",
    "table-blank",
]


@pytest.mark.parametrize("backend", ["postgres", "mysql"])
@pytest.mark.parametrize("version", ["1.0.0", "2.0.0"])
@pytest.mark.parametrize(("changes", "expected"), UNBUILDABLE, ids=UNBUILDABLE_IDS)
def test_an_overwrite_that_cannot_be_built_sends_nothing(
    backend: str, version: str, changes: dict[str, Any], expected: str
) -> None:
    attributes = table_attributes(overwrite=True, **changes)
    source, connection = _offline(backend, existing=True)
    operator = versioned_registry().resolve(f"create_table@{version}")
    _, _, meta = operator.run(INPUT, attributes, {"data_registry": _ForwardingSeam(source)})

    assert expected in _invalid_input(meta)
    assert connection.statements == []

    marker: list[list[dict[str, Any]]] = [[{"name": "kept"}]]
    seam = _ForwardingSeam(source)
    assert CreateTableOperator().apply(marker, attributes, {"data_registry": seam}) is marker
    assert seam.calls == []
    assert connection.statements == []


@pytest.mark.parametrize("backend", ["postgres", "mysql"])
def test_raw_apply_without_columns_sends_nothing(backend: str) -> None:
    attributes = table_attributes(overwrite=True)
    del attributes["columns"]
    source, connection = _offline(backend, existing=True)
    seam = _ForwardingSeam(source)
    assert CreateTableOperator().apply(INPUT, attributes, {"data_registry": seam}) == INPUT
    assert connection.statements == []


@pytest.mark.parametrize("backend", ["postgres", "mysql"])
def test_an_ordinary_overwrite_still_drops_and_creates(backend: str) -> None:
    source, connection = _offline(backend, existing=True)
    _, _, meta = CreateTableOperator().run(
        INPUT, table_attributes(overwrite=True), {"data_registry": _ForwardingSeam(source)}
    )
    assert meta.errors == []
    assert [statement.split()[0] for statement in connection.statements[1:]] == (
        ["DROP", "CREATE", "CREATE"] if backend == "postgres" else ["DROP", "CREATE"]
    )


# -------------------------------------------- every retained version refuses --
@pytest.mark.parametrize("version", ["1.0.0", "2.0.0"])
@pytest.mark.parametrize(("changes", "expected"), REFUSED, ids=REFUSED_IDS)
def test_create_table_refuses_before_any_registry_call(
    version: str, changes: dict[str, Any], expected: str
) -> None:
    seam = _RecordingSeam()
    operator = versioned_registry().resolve(f"create_table@{version}")
    _, _, meta = operator.run(INPUT, table_attributes(**changes), {"data_registry": seam})

    assert expected in _invalid_input(meta)
    assert seam.calls == []


@pytest.mark.parametrize(("changes", "expected"), REFUSED, ids=REFUSED_IDS)
def test_raw_create_table_apply_passes_input_through_without_a_call(
    changes: dict[str, Any], expected: str
) -> None:
    seam = _RecordingSeam()
    marker: list[list[dict[str, Any]]] = [[{"name": "kept"}]]
    out = CreateTableOperator().apply(marker, table_attributes(**changes), {"data_registry": seam})

    assert out is marker
    assert seam.calls == []


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0"])
@pytest.mark.parametrize(
    ("database", "expected"),
    [
        ('x"; DROP DATABASE prod; --', "database cannot contain a double quote"),
        ("x`; DROP DATABASE prod", "database cannot contain a backtick"),
        ("x;y", "database cannot contain a semicolon"),
        ("x\x00", "database cannot contain a NUL character"),
        (['x"; DROP DATABASE prod; --'], "database must be a string"),
        ({"x": 'x"; DROP DATABASE prod'}, "database must be a string"),
    ],
)
def test_create_database_refuses_before_any_registry_call(
    version: str, database: object, expected: str
) -> None:
    seam = _RecordingSeam()
    operator = versioned_registry().resolve(f"create_database@{version}")
    _, _, meta = operator.run(
        INPUT, {"source": "src", "database": database}, {"data_registry": seam}
    )

    assert expected in _invalid_input(meta)
    assert seam.calls == []
    assert (
        CreateDatabaseOperator().apply(
            INPUT, {"source": "src", "database": database}, {"data_registry": seam}
        )
        == INPUT
    )
    assert seam.calls == []


# ----------------------------------------------------------- real SQLite --
def _sqlite(tmp_path: Path) -> tuple[RegistrySeam, Path]:
    seam = RegistrySeam(DataRegistry(name="definitions", rebuild=True))
    source: Any = SQLiteDBSource(
        "src",
        properties={"connection": {"protocol": "sqlite", "database_directory": str(tmp_path)}},
    )
    seam.register_source(source)
    source.create_database("db")
    path = tmp_path / "db.db"
    with sqlite3.connect(path) as setup:
        setup.execute('CREATE TABLE "other" ("id" INTEGER)')
        setup.execute('INSERT INTO "other" VALUES (1)')
    return seam, path


def test_sqlite_creates_an_ordinary_table(tmp_path: Path) -> None:
    seam, path = _sqlite(tmp_path)
    _, _, meta = CreateTableOperator().run(INPUT, table_attributes(), {"data_registry": seam})
    assert meta.errors == []

    with sqlite3.connect(path) as check:
        columns = check.execute('PRAGMA table_info("orders")').fetchall()
    assert [(name, kind, notnull, default) for _, name, kind, notnull, default, _ in columns] == [
        ("id", "INTEGER", 0, None),
        ("code", "VARCHAR(20)", 1, "'x'"),
        ("price", "NUMERIC(10,2)", 0, None),
        ("prénom", "TEXT", 0, None),
    ]


@pytest.mark.parametrize(("changes", "expected"), REFUSED, ids=REFUSED_IDS)
def test_sqlite_is_left_unchanged_by_a_refused_call(
    tmp_path: Path, changes: dict[str, Any], expected: str
) -> None:
    seam, path = _sqlite(tmp_path)
    _, _, meta = CreateTableOperator().run(
        INPUT, table_attributes(**changes), {"data_registry": seam}
    )
    assert expected in _invalid_input(meta)

    with sqlite3.connect(path) as check:
        tables = check.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        rows = check.execute('SELECT "id" FROM "other"').fetchall()
    assert tables == [("other",)]
    assert rows == [(1,)]


# ------------------------------------------------- PostgreSQL and MySQL --
@pytest.mark.parametrize(
    ("backend", "expected"),
    [
        (
            "postgres",
            'CREATE TABLE "public"."orders" ("id" INTEGER, "code" VARCHAR(20) NOT NULL '
            'DEFAULT \'x\', "price" NUMERIC(10,2), "prénom" TEXT, "first name" TEXT);',
        ),
        (
            "mysql",
            "CREATE TABLE `orders` (`id` INTEGER, `code` VARCHAR(20) NOT NULL DEFAULT 'x', "
            "`price` NUMERIC(10,2), `prénom` TEXT, `first name` TEXT);",
        ),
    ],
    ids=["postgres", "mysql"],
)
def test_server_sources_build_an_ordinary_table(backend: str, expected: str) -> None:
    source, connection = _offline(backend)
    columns = [*LEGITIMATE_COLUMNS, {"name": "first name", "type": "TEXT"}]
    _, _, meta = CreateTableOperator().run(
        INPUT, table_attributes(columns=columns), {"data_registry": _ForwardingSeam(source)}
    )

    assert meta.errors == []
    assert connection.statements[-1] == expected


@pytest.mark.parametrize("backend", ["postgres", "mysql"])
@pytest.mark.parametrize(("changes", "expected"), REFUSED, ids=REFUSED_IDS)
def test_server_sources_receive_nothing_for_a_refused_call(
    backend: str, changes: dict[str, Any], expected: str
) -> None:
    source, connection = _offline(backend)
    seam = _ForwardingSeam(source)
    _, _, meta = CreateTableOperator().run(
        INPUT, table_attributes(**changes), {"data_registry": seam}
    )

    assert expected in _invalid_input(meta)
    assert connection.statements == []


def test_postgres_creates_an_ordinarily_named_database() -> None:
    source, connection = _offline("postgres")
    _, _, meta = CreateDatabaseOperator().run(
        INPUT,
        {"source": "src", "database": "sales 2026"},
        {"data_registry": _ForwardingSeam(source)},
    )
    assert meta.errors == []
    assert connection.statements == ['CREATE DATABASE "sales 2026";']


# ------------------------------------------------------ overwrite strings --
# Attribute validation accepts these strings for a bool but leaves them in the attributes,
# and the sources test the value as Python does, where any non-empty string is true.
FALSE_STRINGS = ["false", "False", "no", "0", "off"]


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0"])
@pytest.mark.parametrize("value", FALSE_STRINGS)
def test_sqlite_keeps_the_table_when_overwrite_is_a_false_string(
    tmp_path: Path, version: str, value: str
) -> None:
    seam, path = _sqlite(tmp_path)
    operator = versioned_registry().resolve(f"create_table@{version}")
    attributes = table_attributes(
        table="other", columns=[{"name": "new", "type": "TEXT"}], overwrite=value
    )
    _, _, meta = operator.run(INPUT, attributes, {"data_registry": seam})

    assert meta.errors == []
    with sqlite3.connect(path) as check:
        rows = check.execute('SELECT "id" FROM "other"').fetchall()
    assert rows == [(1,)]


@pytest.mark.parametrize("value", [True, "true", "yes"])
def test_sqlite_replaces_the_table_when_overwrite_is_true(tmp_path: Path, value: object) -> None:
    seam, path = _sqlite(tmp_path)
    attributes = table_attributes(
        table="other", columns=[{"name": "new", "type": "TEXT"}], overwrite=value
    )
    _, _, meta = CreateTableOperator().run(INPUT, attributes, {"data_registry": seam})

    assert meta.errors == []
    with sqlite3.connect(path) as check:
        columns = check.execute('PRAGMA table_info("other")').fetchall()
    assert [name for _, name, *_ in columns] == ["new"]


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0"])
@pytest.mark.parametrize("value", FALSE_STRINGS)
def test_sqlite_keeps_the_database_when_overwrite_is_a_false_string(
    tmp_path: Path, version: str, value: str
) -> None:
    seam, path = _sqlite(tmp_path)
    operator = versioned_registry().resolve(f"create_database@{version}")
    attributes = {"source": "src", "database": "db", "overwrite": value}
    _, _, meta = operator.run(INPUT, attributes, {"data_registry": seam})

    assert meta.errors == []
    with sqlite3.connect(path) as check:
        rows = check.execute('SELECT "id" FROM "other"').fetchall()
    assert rows == [(1,)]


@pytest.mark.parametrize(
    ("value", "expected"),
    [(False, False), ("false", False), ("no", False), ("0", False), (None, False)]
    + [(True, True), ("true", True), ("yes", True), ("1", True)],
)
def test_the_registry_receives_overwrite_as_a_bool(value: object, expected: bool) -> None:
    seam = _RecordingSeam()
    CreateTableOperator().apply(INPUT, table_attributes(overwrite=value), {"data_registry": seam})
    CreateDatabaseOperator().apply(
        INPUT, {"source": "src", "database": "db", "overwrite": value}, {"data_registry": seam}
    )

    [table_call] = seam.calls_to("create_source_database_collection_entity")
    [database_call] = seam.calls_to("create_source_database")
    assert table_call["overwrite"] is expected
    assert database_call["overwrite"] is expected


def test_run_names_overwrite_when_it_is_null() -> None:
    seam = _RecordingSeam()
    table = table_attributes(overwrite=None)
    database = {"source": "src", "database": "db", "overwrite": None}
    _, _, meta = CreateTableOperator().run(INPUT, table, {"data_registry": seam})
    assert _invalid_input(meta) == "overwrite must be true or false"
    _, _, meta = CreateDatabaseOperator().run(INPUT, database, {"data_registry": seam})
    assert _invalid_input(meta) == "overwrite must be true or false"
    assert seam.calls == []


@pytest.mark.parametrize(
    "value",
    [True, False, 0, 1, 2, 0.0, 1.0, 0.5, b"false", b"1", "TRUE", "No", "on", "OFF"]
    + ["t", "f", "y", "n", " false", "false ", "maybe", "", [], {}, ["false"]],
)
def test_overwrite_is_converted_exactly_as_validation_converts_it(value: object) -> None:
    flag = create_model("Flag", value=(bool, ...))
    if validate_parameter_type(value, "bool"):
        assert coerce_flag(value, default=False) is flag(value=value).model_dump()["value"]
    else:
        assert coerce_flag(value, default=False) is None


def test_explain_reads_a_false_string_as_false() -> None:
    table = CreateTableOperator().explain(INPUT, INPUT, table_attributes(overwrite="false"))
    database = CreateDatabaseOperator().explain(INPUT, INPUT, {"source": "src", "overwrite": "no"})
    assert "operator created table" in table["explanation"]
    assert "operator created database" in database["explanation"]


@pytest.mark.parametrize("value", [True, "true"])
def test_sqlite_replaces_the_database_when_overwrite_is_true(tmp_path: Path, value: object) -> None:
    seam, path = _sqlite(tmp_path)
    attributes = {"source": "src", "database": "db", "overwrite": value}
    _, _, meta = CreateDatabaseOperator().run(INPUT, attributes, {"data_registry": seam})

    assert meta.errors == []
    assert path.exists()
    with sqlite3.connect(path) as check:
        tables = check.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    assert tables == []


@pytest.mark.parametrize("value", ["maybe", "", 2, ["false"], {"overwrite": False}])
def test_an_overwrite_validation_refuses_is_refused_by_raw_apply_too(value: object) -> None:
    seam = _RecordingSeam()
    marker: list[list[dict[str, Any]]] = [[{"name": "kept"}]]
    table = table_attributes(overwrite=value)
    database = {"source": "src", "database": "db", "overwrite": value}

    _, _, meta = CreateTableOperator().run(INPUT, table, {"data_registry": seam})
    assert _invalid_input(meta) == "overwrite must be true or false"
    _, _, meta = CreateDatabaseOperator().run(INPUT, database, {"data_registry": seam})
    assert _invalid_input(meta) == "overwrite must be true or false"
    assert CreateTableOperator().apply(marker, table, {"data_registry": seam}) is marker
    assert CreateDatabaseOperator().apply(marker, database, {"data_registry": seam}) is marker
    assert seam.calls == []

# Insert into a disposable SQLite database

Environment: base

This example creates a table in a temporary directory. It registers a SQLite source, inserts rows from a later input group, and reads the stored rows. The returned groups then feed an average after the caller combines their rows into one group.

```python
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from blue_data.registry.data_registry import DataRegistry
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource
from blue_data_ops import RegistrySeam
from blue_data_ops.operators import versioned_registry

operator = versioned_registry().resolve("insert_table@3.0.0")
average = versioned_registry().resolve("avg@3.0.0")
source_name = "example_sqlite"
database = "readings"
table = "samples"

with TemporaryDirectory(prefix="blue-data-ops-insert-") as directory:
    database_path = Path(directory) / f"{database}.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(f'CREATE TABLE "{table}" ("id" INTEGER, "value" INTEGER)')

    source = SQLiteDBSource(
        source_name,
        properties={"connection": {"protocol": "sqlite", "database_directory": directory}},
    )
    registry = RegistrySeam(DataRegistry(name="insert-example", rebuild=True))
    registry.register_source(source)
    attributes = {
        "source": source_name,
        "database": database,
        "table": table,
        "batch_size": 1,
    }
    properties = {"data_registry": registry}
    rows = [[], [{"id": 1, "value": 10}, {"id": 2, "value": 20}], []]

    output_data, output_attributes, exec_meta = operator.run(rows, attributes, properties)
    if exec_meta.errors:
        with sqlite3.connect(database_path) as connection:
            observed = connection.execute(f'SELECT "id", "value" FROM "{table}"').fetchall()
        raise RuntimeError(
            f"Write failed; observed rows: {observed!r}. Inspect before retrying.", exec_meta.errors
        )
    with sqlite3.connect(database_path) as connection:
        stored = connection.execute(f'SELECT "id", "value" FROM "{table}" ORDER BY "id"').fetchall()

    assert output_data == rows and not exec_meta.is_empty
    assert stored == [(1, 10), (2, 20)]
    count = output_attributes.get("num_rows_insert")
    if count is None:
        print("Insertion succeeded; inserted-row count unavailable")
    else:
        assert count == len(stored) == 2
        print(f"Inserted rows: {count}")

    downstream = [[record for group in output_data for record in group]]
    summary, _, summary_meta = average.run(downstream, {"avg_key": "value"})
    if summary_meta.errors:
        raise RuntimeError(summary_meta.errors)
    assert summary == [[{"avg": 15.0}]]
    print(summary)

    empty, empty_attributes, empty_meta = operator.run([[]], attributes, properties)
    assert not empty_meta.errors and empty_meta.is_empty and empty == [[]]
    assert empty_attributes["num_rows_insert"] == 0
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone() == (2,)
```

The table is new and empty before the call, so its stored row count can be compared with this call's insertion count. For an existing table, a total row count alone would not isolate the effect of one call. The source, database, and table names above are fixed local example values.

The temporary directory removes the database when the example exits. For a real target, inspect it after an error or timeout before repeating the write; do not assume rollback or that a timed-out worker has stopped. See the [guide](Operator.md) for input validation and partial-write behavior.

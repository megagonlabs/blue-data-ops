# Insert-table owner check

This check creates a temporary SQLite database, inserts one row, exercises the empty-first-group rule, and contains a failed write. It runs with the base installation and leaves no database behind.

```python
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from blue_data.registry.data_registry import DataRegistry
from blue_data.source.json.memory_json_source import MemoryJSONSource
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource
from blue_data_ops import RegistrySeam
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("insert_table@2.0.0", level=3)
operator = registry.resolve("insert_table@2.0.0")

with TemporaryDirectory(prefix="blue-data-ops-skill-") as directory:
    database_path = Path(directory) / "shop.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute('CREATE TABLE "people" ("id" INTEGER, "name" TEXT)')

    source = SQLiteDBSource(
        "demo_sqlite",
        properties={"connection": {"protocol": "sqlite", "database_directory": directory}},
    )
    data_registry = DataRegistry(store=MemoryJSONSource(), rebuild=False)
    data_registry.register_source(source)
    seam = RegistrySeam(data_registry)
    properties = {"data_registry": seam}
    attributes = {
        "source": "demo_sqlite",
        "database": "shop",
        "table": "people",
        "batch_size": 1,
    }
    rows = [[{"id": 1, "name": "Ada"}]]

    written, output_attributes, written_meta = operator.run(rows, attributes, properties)
    empty, _, empty_meta = operator.run([[], [{"id": 2, "name": "Lin"}]], attributes, properties)
    failed, _, failed_meta = operator.run(rows, {**attributes, "table": "missing"}, properties)

    with sqlite3.connect(database_path) as connection:
        stored = connection.execute('SELECT "id", "name" FROM "people"').fetchall()

assert skill.card.operator_id == "insert_table@2.0.0"
assert written == rows
assert stored == [(1, "Ada")]
assert empty == [[]] and empty_meta.errors == []
assert failed == [[]] and len(failed_meta.errors) == 1
assert output_attributes == {}
assert written_meta.errors == []
```

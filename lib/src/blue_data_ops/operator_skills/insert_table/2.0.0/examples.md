# Insert-table check

Environment: base

This check creates a temporary SQLite table, writes one row, and removes the database with its temporary directory.

```python
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from blue_data.registry.data_registry import DataRegistry
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
    seam = RegistrySeam(DataRegistry(name="skill-check", rebuild=True))
    seam.register_source(source)
    attributes = {
        "source": "demo_sqlite",
        "database": "shop",
        "table": "people",
        "batch_size": 1,
    }
    rows = [[{"id": 1, "name": "Ada"}]]

    output, output_attributes, meta = operator.run(
        rows,
        attributes,
        {"data_registry": seam},
    )
    with sqlite3.connect(database_path) as connection:
        stored = connection.execute('SELECT "id", "name" FROM "people"').fetchall()

assert skill.card.operator_id == "insert_table@2.0.0"
assert output is rows
assert stored == [(1, "Ada")]
assert output_attributes == {}
assert meta.errors == []
```

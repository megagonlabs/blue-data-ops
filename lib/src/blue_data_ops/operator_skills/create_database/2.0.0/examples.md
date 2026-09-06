# Create-database check

Environment: base

This check uses an in-memory registry and source. It records the database locally and makes no network request.

```python
from typing import Any

from blue_data.registry.data_registry import DataRegistry
from blue_data_ops import RegistrySeam
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry


class MemoryDatabaseSource:
    def __init__(self) -> None:
        self.name = "skill_source"
        self.properties = {"connection": {"protocol": "memory"}}
        self.databases: list[str] = []

    def create_database(self, database: str, **_kwargs: Any) -> dict[str, str]:
        self.databases.append(database)
        return {"status": "success"}

    def fetch_databases(self) -> list[str]:
        return list(self.databases)

    def fetch_metadata(self) -> dict[str, Any]:
        return {}

    def fetch_database_metadata(self, database: str) -> dict[str, Any]:
        return {}

    def fetch_database_collections(self, database: str) -> list[str]:
        return []


registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("create_database@2.0.0", level=3)
operator = registry.resolve("create_database@2.0.0")
seam = RegistrySeam(DataRegistry(name="skill-check", rebuild=True))
source = MemoryDatabaseSource()
seam.register_source(source)  # type: ignore[arg-type]
input_data = [[{"name": "displayed_by_explain"}]]

output, output_attributes, meta = operator.run(
    input_data,
    {
        "source": source.name,
        "database": "analytics",
        "description": "temporary skill check",
        "created_by": "example",
    },
    {"data_registry": seam},
)

assert skill.card.operator_id == "create_database@2.0.0"
assert output is input_data
assert source.databases == ["analytics"]
assert seam.get_record("analytics", "database", "/source/skill_source") is not None
assert output_attributes == {}
assert meta.errors == []
```

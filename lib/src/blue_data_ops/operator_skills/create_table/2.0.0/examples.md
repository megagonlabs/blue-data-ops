# Create-table check

Environment: base

The injected seam below records one local create request. It does not connect to a database.

```python
from typing import Any

from blue_data_ops import RegistrySeam
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry


class RecordingSeam(RegistrySeam):
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    def get_source_properties(self, source: str) -> dict[str, Any]:
        return {"connection": {"protocol": "sqlite"}}

    def create_source_database_collection_entity(self, **kwargs: Any) -> None:
        self.created.append(kwargs)


registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("create_table@2.0.0", level=3)
operator = registry.resolve("create_table@2.0.0")
seam = RecordingSeam()
input_data = [[{"name": "displayed_by_explain"}]]
misc = {"primary_key": ["id"]}
attributes = {
    "source": "local",
    "database": "analytics",
    "collection": "ignored_for_sqlite",
    "table": "events",
    "columns": [{"name": "id", "type": "INTEGER"}],
    "misc": misc,
}

output, output_attributes, meta = operator.run(
    input_data,
    attributes,
    {"data_registry": seam},
)

assert skill.card.operator_id == "create_table@2.0.0"
assert output is input_data
assert seam.created[0]["collection"] == "public"
assert seam.created[0]["creation_properties"] is not misc
assert seam.created[0]["creation_properties"]["cols_definition"] == attributes["columns"]
assert "cols_definition" not in misc
assert output_attributes == {}
assert meta.errors == []

raw_misc = {"primary_key": ["id"]}
raw_attributes = {**attributes, "misc": raw_misc}
assert operator.apply(input_data, raw_attributes, {"data_registry": seam}) is input_data
assert raw_misc["cols_definition"] == attributes["columns"]
```

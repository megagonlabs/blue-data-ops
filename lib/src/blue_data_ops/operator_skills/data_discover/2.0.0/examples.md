# Data-discovery example

Environment: base

This injected seam returns local records and captures the search boundary.

```python
from typing import Any

from blue_data_ops import RegistrySeam
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry


class LocalSearchSeam(RegistrySeam):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def search_records_hierarchical(self, input_query: Any, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"input_query": input_query, **kwargs})
        return [
            {"name": "near", "id": "/source/near", "scope": "/", "score": 0.2},
            {"name": "far", "id": "/source/far", "scope": "/", "score": 0.8},
        ]

    def get_record(self, name: str, type: str, scope: str) -> dict[str, Any] | None:
        if name != "near":
            return None
        return {
            "description": "local source",
            "properties": {"kind": "json", "protocol": "memory"},
            "metadata": {"owner": "example"},
        }


registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("data_discover@2.0.0", level=3)
operator = registry.resolve("data_discover@2.0.0")
seam = LocalSearchSeam()

output, output_attributes, meta = operator.run(
    [[]],
    {
        "search_query": "local",
        "approximate": True,
        "threshold": 0.5,
    },
    {"data_registry": seam},
)

assert skill.card.operator_id == "data_discover@2.0.0"
assert [record["name"] for record in output[0]] == ["near"]
assert output[0][0] == {
    "type": "source",
    "name": "near",
    "id": "/source/near",
    "scope": "/",
    "score": 0.2,
    "properties": {"kind": "json"},
}
assert seam.calls[0]["scope"] is None
assert output_attributes == {}
assert meta.errors == []
```

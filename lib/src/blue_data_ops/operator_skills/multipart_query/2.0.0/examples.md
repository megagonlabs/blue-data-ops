# Multipart-query check

Environment: base

This check refines one local CTE, verifies the selected child versions, and performs no query.

```python
from typing import Any, cast

from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("multipart_query@2.0.0", level=3)
operator = registry.resolve("multipart_query@2.0.0")
cte = {
    "table": "facts",
    "description": "read facts",
    "sql": "SELECT 1 AS answer",
    "columns": [{"name": "answer", "type": "int"}],
    "dependency": [],
    "generality": 0,
}

plans, refine_meta = operator.refine([[cte]], {})
compute, output_attributes, compute_meta = operator.run([[]], {})
child_ids = sorted(
    cast(str, cast(dict[str, Any], entity)["operator_id"])
    for entity in plans[0].get_entities(type="OPERATOR").values()
)

try:
    operator.invoke([[]], {})
except TypeError as error:
    assert "input_data" in str(error)
else:
    raise AssertionError("canonical invoke unexpectedly accepted multipart_query")

assert skill.card.operator_id == "multipart_query@2.0.0"
assert child_ids == [
    "create_database@2.0.0",
    "create_table@2.0.0",
    "data_discover@2.0.0",
    "insert_table@2.0.0",
    "nl2query_router@2.0.0",
]
assert compute == [[]]
assert output_attributes == {}
assert compute_meta.errors == []
assert refine_meta.errors == []
```

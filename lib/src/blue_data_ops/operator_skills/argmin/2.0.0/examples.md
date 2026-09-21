# Minimum-record example

Environment: base

This example preserves a numeric tie and also shows the empty and invalid outcomes.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("argmin@2.0.0", level=3)
operator = registry.resolve("argmin@2.0.0")
first = {"value": 1, "name": "first"}
second = {"value": "1.0", "name": "second"}
data = [[{"value": 3}, first, second, {"other": 0}]]

records, output_attributes, meta = operator.run(data, {"argmin_key": "value"})
indices, _, index_meta = operator.run(
    data,
    {"argmin_key": "value", "return_index": True},
)
empty, _, empty_meta = operator.run([], {"argmin_key": "value"})
invalid, _, invalid_meta = operator.run(data, {})

assert skill.card.operator_id == "argmin@2.0.0"
assert records == [[first, second]]
assert records[0][0] is first
assert indices == [[{"indices": [1, 2]}]]
assert empty == [[]] and empty_meta.is_empty
assert invalid == [[]] and invalid_meta.errors[0].code.value == "INVALID_INPUT"
assert output_attributes == {}
assert meta.errors == [] and index_meta.errors == []
```

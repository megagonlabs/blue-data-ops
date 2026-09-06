# Projection check

Environment: base

This call keeps field order, renames one field, and omits missing fields.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("project@2.0.0", level=3)
operator = registry.resolve("project@2.0.0")
data = [[{"id": 1, "name": "Ada"}, {"id": 2}]]
attributes = {
    "kept_keys": ["name", "id", "missing"],
    "key_mapping": {"name": "person"},
}

output, output_attributes, meta = operator.run(data, attributes)
empty, _, empty_meta = operator.run(data, {"kept_keys": []})
invalid, _, invalid_meta = operator.run(
    data,
    {"kept_keys": ["id", "name"], "key_mapping": {"name": "id"}},
)

assert skill.card.operator_id == "project@2.0.0"
assert output == [[{"person": "Ada", "id": 1}, {"id": 2}]]
assert output[0][0] is not data[0][0]
assert empty == [[]] and empty_meta.is_empty
assert invalid == [[]] and invalid_meta.errors[0].code.value == "INVALID_INPUT"
assert output_attributes == {} and meta.errors == []
```

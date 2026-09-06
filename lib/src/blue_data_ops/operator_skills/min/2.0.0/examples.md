# Minimum-value check

Environment: base

This check skips unusable values and verifies the successful null result.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("min@2.0.0", level=3)
operator = registry.resolve("min@2.0.0")
data = [[{"value": "bad"}, {"value": "4"}, {"value": 2}, {"other": 1}]]

output, output_attributes, meta = operator.run(
    data,
    {"min_key": "value", "output_key": "smallest"},
)
null_result, _, null_meta = operator.run(data, {"min_key": "missing"})
invalid, _, invalid_meta = operator.run(data, {})

assert skill.card.operator_id == "min@2.0.0"
assert output == [[{"smallest": 2}]]
assert null_result == [[{"min": None}]] and not null_meta.is_empty
assert invalid == [[]] and invalid_meta.errors[0].code.value == "INVALID_INPUT"
assert output_attributes == {} and meta.errors == []
```

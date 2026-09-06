# Delete check

Environment: base

The list form accepts negative positions, ignores an out-of-range value, and deletes duplicates once.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("delete@2.0.0", level=3)
operator = registry.resolve("delete@2.0.0")
first, second, third = {"id": 1}, {"id": 2}, {"id": 3}
data = [[first, second, third]]

output, output_attributes, meta = operator.run(
    data,
    {"delete_idx": [1, 1, 99]},
)
empty, _, empty_meta = operator.run([[]], {"delete_idx": 0})
invalid, _, invalid_meta = operator.run(data, {"delete_idx": "1"})

assert skill.card.operator_id == "delete@2.0.0"
assert output == [[first, third]]
assert output[0][0] is first and output[0] is not data[0]
assert empty == [[]] and empty_meta.is_empty
assert invalid == [[]] and invalid_meta.errors[0].code.value == "INVALID_INPUT"
assert output_attributes == {} and meta.errors == []
```

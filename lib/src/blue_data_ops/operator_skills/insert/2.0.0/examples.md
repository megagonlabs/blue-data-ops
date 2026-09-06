# Insert check

Environment: base

A non-empty second group overrides the declared `insert_records` value.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("insert@2.0.0", level=3)
operator = registry.resolve("insert@2.0.0")
first, second = {"id": 1}, {"id": 2}
from_second = {"id": 3}
ignored = {"id": 4}
data = [[first, second], [from_second]]

output, output_attributes, meta = operator.run(
    data,
    {"insert_records": [ignored], "insert_idx": 1},
)
failed, _, failed_meta = operator.run(
    [[first]],
    {"insert_records": [{"id": 5}], "insert_idx": (0,)},
)
empty, _, empty_meta = operator.run([], {"insert_records": [ignored]})

assert skill.card.operator_id == "insert@2.0.0"
assert output == [[first, from_second, second]]
assert output[0] is not data[0] and output[0][0] is first
assert failed == [[]] and failed_meta.errors[0].code.value == "EXECUTION_FAILED"
assert empty == [[]] and empty_meta.is_empty
assert output_attributes == {} and meta.errors == []
```

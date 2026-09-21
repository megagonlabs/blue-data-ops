# Maximum-value example

Environment: base

The first equal maximum supplies the returned value and its type.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("max@2.0.0", level=3)
operator = registry.resolve("max@2.0.0")
data = [[{"value": 3}, {"value": 5}, {"value": "5.0"}, {"value": "bad"}]]

output, output_attributes, meta = operator.run(
    data,
    {"max_key": "value", "output_key": "largest"},
)
empty, _, empty_meta = operator.run([[]], {"max_key": "value"})
invalid, _, invalid_meta = operator.run(data, {})

assert skill.card.operator_id == "max@2.0.0"
assert output == [[{"largest": 5}]]
assert type(output[0][0]["largest"]) is int
assert empty == [[{"max": None}]] and not empty_meta.is_empty
assert invalid == [[]] and invalid_meta.errors[0].code.value == "INVALID_INPUT"
assert output_attributes == {} and meta.errors == []
```

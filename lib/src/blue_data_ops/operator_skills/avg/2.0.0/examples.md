# Average owner check

This check loads the package, averages the first group, and verifies the successful empty result. It runs with the base installation.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("avg@2.0.0", level=3)
operator = registry.resolve("avg@2.0.0")

output, output_attributes, meta = operator.run(
    [[{"value": 2}, {"value": "4"}, {"value": True}, {"value": "bad"}]],
    {"avg_key": "value"},
)
empty, _, empty_meta = operator.run([[]], {"avg_key": "value"})

assert skill.card.operator_id == "avg@2.0.0"
assert skill.loaded_kinds == ("guide", "examples")
assert output == [[{"avg": 7 / 3}]]
assert empty == [[{"avg": 0}]]
assert output_attributes == {}
assert meta.errors == []
assert empty_meta.errors == []
```

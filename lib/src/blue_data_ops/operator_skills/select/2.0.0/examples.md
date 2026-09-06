# Select check

Environment: base

This example filters one group, verifies record identity, and checks both successful-empty and invalid outcomes.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("select@2.0.0", level=3)
operator = registry.resolve("select@2.0.0")
records = [
    [
        {"id": 1, "score": 0.81},
        {"id": 2, "score": 0.93},
        {"id": 3},
    ]
]

selected, output_attributes, meta = operator.run(
    records,
    {"operand_key": "score", "operand": ">=", "operand_val": 0.9},
)
empty, _, empty_meta = operator.run(
    records,
    {"operand_key": "score", "operand": ">", "operand_val": 1.0},
)
invalid, _, invalid_meta = operator.run(
    records,
    {"operand_key": "score", "operand": "contains", "operand_val": 0.9},
)

assert skill.card.operator_id == "select@2.0.0"
assert selected == [[records[0][1]]]
assert selected[0][0] is records[0][1]
assert empty == [[]] and empty_meta.errors == []
assert invalid == [[]] and invalid_meta.errors
assert output_attributes == {}
assert meta.errors == []
```

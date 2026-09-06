# Join check

Environment: base

The composite-key join retains both key sets and suffixes the colliding value field.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("join@2.0.0", level=3)
operator = registry.resolve("join@2.0.0")
data = [
    [{"tenant": "a", "code": 1, "value": "left"}],
    [{"org": "a", "sku": 1, "value": "right"}],
]
attributes = {
    "join_on": [["tenant", "code"], ["org", "sku"]],
    "join_type": "inner",
    "join_suffix": ["_left", "_right"],
    "keep_keys": "both",
}

output, output_attributes, meta = operator.run(data, attributes)
none, _, none_meta = operator.run(
    [[{"id": 1}], [{"id": 2}]],
    {"join_on": [["id"], ["id"]]},
)
guarded, _, guard_meta = operator.run(data, {**attributes, "join_suffix": ["_x", "_x"]})

assert skill.card.operator_id == "join@2.0.0"
assert output == [
    [
        {
            "tenant": "a",
            "code": 1,
            "org": "a",
            "sku": 1,
            "value_left": "left",
            "value_right": "right",
        }
    ]
]
assert none == [[]] and none_meta.is_empty
assert guarded == [[]] and guard_meta.is_empty and guard_meta.errors == []
assert output_attributes == {} and meta.errors == []
```

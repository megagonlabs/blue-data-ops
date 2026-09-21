# Intersection example

Environment: base

The first non-empty group supplies both duplicate records and their identities.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("intersect@2.0.0", level=3)
operator = registry.resolve("intersect@2.0.0")
first = {"id": 1, "name": "A"}
duplicate = {"id": 1, "name": "A"}
data = [[], [first, duplicate, {"id": 2}], [{"name": "A", "id": 1}]]

output, output_attributes, meta = operator.run(data, {})
none, _, none_meta = operator.run([[{"id": 1}], [{"id": 2}]], {})
invalid, _, invalid_meta = operator.run(data, {"match_option": "identity"})

assert skill.card.operator_id == "intersect@2.0.0"
assert output == [[first, duplicate]]
assert output[0][0] is first and output[0][1] is duplicate
assert none == [[]] and none_meta.is_empty
assert invalid == [[]] and invalid_meta.errors[0].code.value == "INVALID_INPUT"
assert output_attributes == {} and meta.errors == []
```

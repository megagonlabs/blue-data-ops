# Sum check

Environment: base

Bytes convert through `int()`, a fractional `Decimal` is truncated, and Booleans count as integers.

```python
from decimal import Decimal

from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("sum@2.0.0", level=3)
operator = registry.resolve("sum@2.0.0")
data = [[{"value": b"4"}, {"value": Decimal("3.9")}, {"value": True}]]

output, output_attributes, meta = operator.run(data, {"sum_key": "value"})
zero, _, zero_meta = operator.run([[]], {"sum_key": "value"})
invalid, _, invalid_meta = operator.run(data, {})

assert skill.card.operator_id == "sum@2.0.0"
assert output == [[{"sum": 8}]]
assert zero == [[{"sum": 0}]] and not zero_meta.is_empty
assert invalid == [[]] and invalid_meta.errors[0].code.value == "INVALID_INPUT"
assert output_attributes == {} and meta.errors == []
```

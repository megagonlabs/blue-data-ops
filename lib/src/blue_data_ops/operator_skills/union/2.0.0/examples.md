# Union owner check

This check loads the package and compares the two matching modes on records whose keys differ but whose values align. It also verifies which record survives. It runs with the base installation.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("union@2.0.0", level=3)
operator = registry.resolve("union@2.0.0")

first = {"a": 1, "b": "x"}
same_values = {"other": True, "fields": "x"}
different = {"other": 2, "fields": "y"}
input_data = [[first], [same_values, different]]

key_output, output_attributes, key_meta = operator.run(
    input_data,
    {"match_option": "key_match"},
)
sequence_output, _, sequence_meta = operator.run(
    input_data,
    {"match_option": "seq_match"},
)

assert skill.card.operator_id == "union@2.0.0"
assert skill.loaded_kinds == ("guide", "examples")
assert key_output == [[first, same_values, different]]
assert sequence_output == [[first, different]]
assert sequence_output[0][0] is first
assert output_attributes == {}
assert key_meta.errors == []
assert sequence_meta.errors == []
```

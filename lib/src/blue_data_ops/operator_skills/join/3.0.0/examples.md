# Join example

Environment: base

The join keeps both groups' `value` fields under distinct suffixes. Its output then becomes the input to `avg`; the caller reads execution metadata separately.

```python
from blue_data_ops.operators import versioned_registry

operator = versioned_registry().resolve("join@3.0.0")
data = [
    [{"id": 1, "value": 10}, {"id": 2, "value": 20}],
    [{"id": 1, "value": 12}, {"id": 2, "value": 24}],
]
attributes = {
    "join_on": [["id"], ["id"]],
    "join_suffix": ["_left", "_right"],
}
joined, output_attributes, exec_meta = operator.run(data, attributes)
if exec_meta.errors:
    raise RuntimeError(exec_meta.errors)
assert joined == [
    [
        {"id": 1, "value_left": 10, "value_right": 12},
        {"id": 2, "value_left": 20, "value_right": 24},
    ]
]
assert output_attributes == {} and not exec_meta.is_empty

average = versioned_registry().resolve("avg@3.0.0")
summary, summary_attributes, summary_meta = average.run(joined, {"avg_key": "value_left"})
if summary_meta.errors:
    raise RuntimeError(summary_meta.errors)
assert summary == [[{"avg": 15.0}]]
print(summary)
count = summary_attributes.get("num_values_used")
if count is not None:
    print(f"Values averaged: {count}")

empty, _, empty_meta = operator.run([[{"id": 1}], [{"id": 2}]], {"join_on": [["id"], ["id"]]})
assert not empty_meta.errors and empty_meta.is_empty and empty == [[]]

invalid, invalid_attributes, invalid_meta = operator.run(
    [[], []], {**attributes, "join_suffix": ["_same", "_same"]}
)
assert invalid_meta.errors[0].code.value == "INVALID_INPUT"
assert invalid == [[]] and invalid_attributes == {} and not invalid_meta.is_empty
```

Empty input groups do not bypass suffix validation. The [guide](Operator.md) lists the accepted key, suffix, and join settings.

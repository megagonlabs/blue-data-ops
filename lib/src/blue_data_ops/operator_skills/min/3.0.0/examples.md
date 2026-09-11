# Minimum-value example

Environment: base

This call mixes the accepted legacy conversions with a real zero. A separate call has no usable value.

```python
from blue_data_ops.operators import versioned_registry

operator = versioned_registry().resolve("min@3.0.0")
data = [
    [
        {"reading": b"7"},
        {"reading": "2.5"},
        {"reading": 0},
        {"reading": "not-a-number"},
    ]
]

output, output_attributes, meta = operator.run(data, {"min_key": "reading", "output_key": "lowest"})
assert output == [[{"lowest": 0}]] and type(output[0][0]["lowest"]) is int
assert output_attributes == {} and not meta.errors and not meta.is_empty

empty, empty_attributes, empty_meta = operator.run(
    [[{"reading": None}, {"reading": "not-a-number"}]], {"min_key": "reading"}
)
assert empty == [[]] and empty_attributes == {}
assert not empty_meta.errors and empty_meta.is_empty

invalid, _, invalid_meta = operator.run(data, {})
assert invalid == [[]] and not invalid_meta.is_empty
assert invalid_meta.errors[0].code.value == "INVALID_INPUT"
```

The zero record is nonempty data. Only the call with no accepted value returns successful empty.

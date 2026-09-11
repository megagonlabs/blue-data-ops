# Maximum-value example

Environment: base

The integer-first conversion truncates the Decimal before comparison, while bytes and a fractional string also convert.

```python
from decimal import Decimal

from blue_data_ops.operators import versioned_registry

operator = versioned_registry().resolve("max@3.0.0")
data = [
    [
        {"reading": Decimal("8.9")},
        {"reading": b"11"},
        {"reading": "10.5"},
        {"reading": "not-a-number"},
    ]
]

output, output_attributes, meta = operator.run(
    data, {"max_key": "reading", "output_key": "highest"}
)
assert output == [[{"highest": 11}]] and type(output[0][0]["highest"]) is int
assert output_attributes == {} and not meta.errors and not meta.is_empty

empty, empty_attributes, empty_meta = operator.run(
    [[{"reading": None}, {"other": 4}]], {"max_key": "reading"}
)
assert empty == [[]] and empty_attributes == {}
assert not empty_meta.errors and empty_meta.is_empty
```

`Decimal("8.9")` contributes as 8 because `int()` is tried first. This is retained compatibility behavior, not a decimal-preserving reduction.

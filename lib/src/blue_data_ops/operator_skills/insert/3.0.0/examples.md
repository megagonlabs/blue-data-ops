# Insert example

Environment: base

A record from the second group populates an existing empty first group and takes precedence over the declared fallback.

```python
from blue_data_ops.operators import versioned_registry

operator = versioned_registry().resolve("insert@3.0.0")
supplied = {"sku": "mug-42", "stock": 3}
fallback = {"sku": "fallback", "stock": 0}

output, output_attributes, meta = operator.run(
    [[], [supplied]],
    {"insert_records": [fallback], "insert_idx": 0},
)
assert output == [[supplied]] and output[0][0] is supplied
assert output_attributes == {} and not meta.errors and not meta.is_empty

empty, empty_attributes, empty_meta = operator.run(
    [], {"insert_records": [fallback], "insert_idx": 0}
)
assert empty == [[]] and empty_attributes == {}
assert not empty_meta.errors and empty_meta.is_empty
```

`[[]]` is an existing empty target and can be populated. `[]` has no target and stays successful empty.

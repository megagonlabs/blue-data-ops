# Projection example

Environment: base

This call keeps field order, renames one field, and retains a record that has none of the requested fields.

```python
from blue_data_ops.operators import versioned_registry

operator = versioned_registry().resolve("project@3.0.0")
data = [
    [
        {"sku": "cup-7", "title": "Blue cup", "price": 12},
        {"sku": "plate-3"},
        {"warehouse": "north"},
    ]
]
attributes = {
    "kept_keys": ["title", "sku", "price"],
    "key_mapping": {"sku": "item_code"},
}

output, output_attributes, meta = operator.run(data, attributes)
assert output == [
    [
        {"title": "Blue cup", "item_code": "cup-7", "price": 12},
        {"item_code": "plate-3"},
        {},
    ]
]
assert output_attributes == {} and not meta.errors and not meta.is_empty

invalid, invalid_attributes, invalid_meta = operator.run([[]], {"kept_keys": []})
assert invalid == [[]] and invalid_attributes == {} and not invalid_meta.is_empty
assert invalid_meta.errors[0].code.value == "INVALID_INPUT"
assert invalid_meta.errors[0].stage.value == "VALIDATE"
```

The final `{}` is a projected record. It is different from the successful-empty tensor `[[]]`.

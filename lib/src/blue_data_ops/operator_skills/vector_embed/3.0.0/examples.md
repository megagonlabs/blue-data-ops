# Vector-embed empty example

Environment: base

This call has two empty groups, so it does not import or download an embedding model. Invalid settings still take precedence over a successful empty result.

```python
from blue_data_ops.operators import versioned_registry

operator = versioned_registry().resolve("vector_embed@3.0.0")

output_data, output_attributes, exec_meta = operator.run(
    [[], []],
    {"text_field": ["body"]},
)
assert output_data == [[]]
assert output_attributes == {}
assert exec_meta.errors == [] and exec_meta.is_empty

invalid_data, invalid_attributes, invalid_meta = operator.run(
    [[], []],
    {"text_field": ["body"], "on_missing_fields": "skip"},
)
assert invalid_data == [[]] and invalid_attributes == {}
assert invalid_meta.errors[0].code.value == "INVALID_INPUT"
assert not invalid_meta.is_empty
```

Nonempty calls need the `vector` extra and an available sentence-transformers model. The [guide](Operator.md) describes group processing, record keys, and raw-call behavior.

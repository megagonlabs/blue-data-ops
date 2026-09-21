# Vector-embed example

Environment: base

The empty-input example uses the successful-empty path and requires no optional model package.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("vector_embed@2.0.0", level=3)
operator = registry.resolve("vector_embed@2.0.0")

output, output_attributes, meta = operator.run(
    [[], [{"id": "later", "text": "not processed"}]],
    {"text_field": ["text"]},
)

assert skill.card.operator_id == "vector_embed@2.0.0"
assert output == [[]]
assert output_attributes == {}
assert meta.errors == []
```

The nonempty path needs `blue-data-ops[vector]`. It downloads the named model over the network, and a restricted model host may require credentials.

```python live
from blue_data_ops.operators import versioned_registry

operator = versioned_registry().resolve("vector_embed@2.0.0")
output, output_attributes, meta = operator.run(
    [[{"id": "note-1", "text": "A short note."}]],
    {"text_field": ["text"], "append": True, "add_meta_data": True},
)
assert output[0][0]["embed.model"] == "all-MiniLM-L6-v2"
assert output_attributes == {}
assert meta.errors == []
```

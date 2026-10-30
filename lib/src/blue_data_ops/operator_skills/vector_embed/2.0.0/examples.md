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

To embed nonempty input, install `blue-data-ops[vector]`. The default
`all-MiniLM-L6-v2` model may need to download files from its model host.

Running this example may send requests over the network. A remote service may require credentials. The test suite does not run this example.

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

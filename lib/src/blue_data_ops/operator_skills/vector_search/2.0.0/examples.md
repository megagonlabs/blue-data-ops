# Vector-search example

Environment: vector

This example ranks existing embeddings without constructing or downloading a model. It also shows that `top_k` is effective only as a property in this version.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("vector_search@2.0.0", level=3)
operator = registry.resolve("vector_search@2.0.0")
candidates = [
    [
        {"id": "a", "embedding": [1.0, 0.0], "embed.model": "local-2d"},
        {"id": "b", "embedding": [0.8, 0.2], "embed.model": "local-2d"},
        {"id": "c", "embedding": [0.0, 1.0], "embed.model": "local-2d"},
    ]
]
query = {"embedding": [1.0, 0.0], "model": "local-2d"}

attribute_only, _, attribute_meta = operator.run(
    candidates,
    {"query": query, "top_k": 1},
)
limited, output_attributes, meta = operator.run(
    candidates,
    {"query": query, "add_meta_data": True},
    {"top_k": 1},
)

assert skill.card.operator_id == "vector_search@2.0.0"
assert len(attribute_only[0]) == 3
assert [row["id"] for row in limited[0]] == ["a"]
assert limited[0][0]["search.rank"] == 1
assert limited[0][0]["search.model"] == "local-2d"
assert output_attributes == {}
assert attribute_meta.errors == []
assert meta.errors == []
```

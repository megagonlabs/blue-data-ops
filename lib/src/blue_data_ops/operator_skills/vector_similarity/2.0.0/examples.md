# Vector-similarity example

Environment: vector

This example uses existing embeddings, so it does not construct or download a model. It shows the result keys and the error returned for a mismatched pairwise call.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("vector_similarity@2.0.0", level=3)
operator = registry.resolve("vector_similarity@2.0.0")
left = [
    {"id": "left-a", "embedding": [1.0, 0.0]},
    {"id": "left-b", "embedding": [0.0, 1.0]},
]
right = [
    {"id": "right-a", "embedding": [1.0, 0.0]},
    {"id": "right-b", "embedding": [1.0, 1.0]},
]

output, output_attributes, meta = operator.run(
    [left, right],
    {
        "comparison_mode": "pairwise",
        "metric": "cosine",
        "threshold": 0.75,
        "add_meta_data": True,
    },
)
mismatched, _, mismatch_meta = operator.run(
    [left, right[:1]],
    {"comparison_mode": "pairwise"},
)

assert skill.card.operator_id == "vector_similarity@2.0.0"
assert [record["id"] for record in output[0]] == ["left-a_right-a", "left-b_right-b"]
assert output[0][0]["similarity.score"] == 1.0
assert output[0][0]["similarity.passed"] is True
assert "similarity.model" not in output[0][0]
assert output_attributes == {}
assert meta.errors == []
assert mismatched == [[]] and mismatch_meta.errors
```

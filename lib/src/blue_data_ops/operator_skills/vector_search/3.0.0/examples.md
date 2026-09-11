# Vector-search example

Environment: vector

This example uses precomputed vectors with matching model labels. Attribute controls are effective in this version, and a present property takes precedence.

```python
from blue_data_ops.operators import versioned_registry

operator = versioned_registry().resolve("vector_search@3.0.0")
candidates = [
    [
        {"id": "cedar", "embedding": [1.0, 0.0], "embed.model": "manual-2d"},
        {"id": "maple", "embedding": [0.0, 2.0], "embed.model": "manual-2d"},
        {"id": "birch", "embedding": [1.0, 1.0], "embed.model": "manual-2d"},
    ]
]
attributes = {
    "query": {"embedding": [1.0, 2.0], "model": "manual-2d"},
    "metric": "dot",
    "top_k": 2,
}

output_data, output_attributes, exec_meta = operator.run(candidates, attributes)
assert [row["id"] for row in output_data[0]] == ["maple", "birch"]
assert [row["search.score"] for row in output_data[0]] == [4.0, 3.0]
assert output_attributes == {}
assert exec_meta.errors == [] and not exec_meta.is_empty

limited, _, limited_meta = operator.run(candidates, attributes, {"top_k": 1})
assert [row["id"] for row in limited[0]] == ["maple"]
assert limited_meta.errors == []

unbounded, _, unbounded_meta = operator.run(candidates, {**attributes, "top_k": 1}, {"top_k": None})
assert len(unbounded[0]) == 3 and unbounded_meta.errors == []

empty, empty_attributes, empty_meta = operator.run(
    candidates,
    {**attributes, "min_score": 5.0},
)
assert empty == [[]] and empty_attributes == {}
assert empty_meta.errors == [] and empty_meta.is_empty
```

No sentence-transformers model is constructed for these calls. The [guide](Operator.md) covers the other `None` cases, metadata keys, and raw-call differences.

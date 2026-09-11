# Vector-similarity example

Environment: vector

Precomputed vectors use installed NumPy without constructing an embedding model. The threshold stays on each pair record, while `output_attributes` remains empty.

```python
from blue_data_ops.operators import versioned_registry

operator = versioned_registry().resolve("vector_similarity@3.0.0")
left = [
    {"id": "left-copper", "embedding": [2.0, 1.0]},
    {"id": "left-slate", "embedding": [-1.0, 2.0]},
]
right = [
    {"id": "right-copper", "embedding": [1.0, 2.0]},
    {"id": "right-slate", "embedding": [3.0, 0.0]},
]

output_data, output_attributes, exec_meta = operator.run(
    [left, right],
    {
        "comparison_mode": "pairwise",
        "metric": "dot",
        "threshold": 0.0,
        "add_meta_data": True,
    },
)
assert [row["similarity.score"] for row in output_data[0]] == [4.0, -3.0]
assert [row["similarity.passed"] for row in output_data[0]] == [True, False]
assert all("search.score" not in row for row in output_data[0])
assert all("similarity.model" not in row for row in output_data[0])
assert output_attributes == {}
assert exec_meta.errors == [] and not exec_meta.is_empty

empty, empty_attributes, empty_meta = operator.run(
    [left, []],
    {"comparison_mode": "cartesian", "metric": "dot"},
)
assert empty == [[]] and empty_attributes == {}
assert empty_meta.errors == [] and empty_meta.is_empty
```

The [guide](Operator.md) explains pairwise empty rules, generated embeddings, and conditional metadata.

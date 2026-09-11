# Clustering example

Environment: ml

Fixed initial centroids make the KMeans labels deterministic and require no download.

```python
from blue_data_ops.operators import versioned_registry

operator = versioned_registry().resolve("cluster@3.0.0")
data = [
    [
        {"sample": "west-a", "features": [-5.0, -4.0]},
        {"sample": "west-b", "features": [-4.0, -5.0]},
        {"sample": "not-measured"},
        {"sample": "east-a", "features": [6.0, 5.0]},
        {"sample": "east-b", "features": [5.0, 6.0]},
    ]
]
attributes = {
    "vector_key": "features",
    "n_cluster": 2,
    "init": "specified",
    "init_centroids": [[-5.0, -5.0], [5.0, 5.0]],
}

output, output_attributes, meta = operator.run(data, attributes, {"algorithm": "kmeans"})
assert not meta.errors and not meta.is_empty
assert [record["cluster_index"] for record in output[0]] == [0, 0, None, 1, 1]
assert output_attributes == {}

invalid, invalid_attributes, invalid_meta = operator.run(
    [[{"features": [0.0, 0.0]}, {"features": [1.0, 1.0]}]],
    {"vector_key": "features", "n_cluster": 3},
    {"algorithm": "kmeans"},
)
assert invalid == [[]] and invalid_attributes == {} and not invalid_meta.is_empty
assert invalid_meta.errors[0].code.value == "INVALID_INPUT"
assert invalid_meta.errors[0].stage.value == "VALIDATE"
```

The exact version is resolved explicitly. Default planner and MCP selection are separate from this call.

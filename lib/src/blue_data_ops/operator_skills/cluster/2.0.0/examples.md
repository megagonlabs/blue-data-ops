# Clustering check

Environment: ml

Fixed initial centroids make this KMeans result deterministic and require no download.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("cluster@2.0.0", level=3)
operator = registry.resolve("cluster@2.0.0")
data = [
    [
        {"id": "a", "vector": [0.0, 0.1]},
        {"id": "b", "vector": [0.2, 0.0]},
        {"id": "missing"},
        {"id": "c", "vector": [9.9, 10.1]},
        {"id": "d", "vector": [10.2, 9.8]},
    ]
]
attributes = {
    "vector_key": "vector",
    "n_cluster": 2,
    "init": "specified",
    "init_centroids": [[0.0, 0.0], [10.0, 10.0]],
}

output, output_attributes, meta = operator.run(data, attributes)
empty, _, empty_meta = operator.run([[]], attributes)
unchanged = operator.apply(data, {"vector_key": "vector"}, {"algorithm": "unknown"})

assert skill.card.operator_id == "cluster@2.0.0"
assert [record["cluster_index"] for record in output[0]] == [0, 0, None, 1, 1]
assert output[0][0] is not data[0][0]
assert empty == [[]] and empty_meta.is_empty
assert unchanged[0] is data[0]
assert output_attributes == {} and meta.errors == []
```

# Classification example

Environment: ml

The first group trains a decision tree. The second supplies prediction records, including one without a vector.

```python
from blue_data_ops.operators import versioned_registry

operator = versioned_registry().resolve("classify@3.0.0")
training = [
    {"sample": "cool-a", "features": [0.0, 0.0], "kind": "cool"},
    {"sample": "cool-b", "features": [0.0, 1.0], "kind": "cool"},
    {"sample": "warm-a", "features": [8.0, 8.0], "kind": "warm"},
    {"sample": "warm-b", "features": [9.0, 8.0], "kind": "warm"},
]
samples = [
    {"sample": "near-cool", "features": [0.2, 0.7]},
    {"sample": "near-warm", "features": [8.4, 8.1]},
    {"sample": "not-measured"},
]
attributes = {
    "vector_key": "features",
    "label_key": "kind",
    "output_key": "predicted_kind",
    "random_state": 7,
}

output, output_attributes, meta = operator.run(
    [training, samples],
    attributes,
    {"algorithm": "decision_tree"},
)
assert not meta.errors and not meta.is_empty
assert [record["predicted_kind"] for record in output[1]] == ["cool", "warm", None]
assert output_attributes == {}

invalid, invalid_attributes, invalid_meta = operator.run(
    [training], attributes, {"algorithm": "svm"}
)
assert invalid == [[]] and invalid_attributes == {} and not invalid_meta.is_empty
assert invalid_meta.errors[0].code.value == "INVALID_INPUT"
assert invalid_meta.errors[0].stage.value == "VALIDATE"
```

The exact version is resolved explicitly. Default planner and MCP selection are separate from this call.

# Classification check

Environment: ml

The first group trains each supported model. The second group checks prediction and missing-vector handling.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("classify@2.0.0", level=3)
operator = registry.resolve("classify@2.0.0")
training = [
    {"label": "first", "vector": [10.0, 1.0]},
    {"label": "first", "vector": [9.0, 0.5]},
    {"label": "first", "vector": [8.0, 1.5]},
    {"label": "first", "vector": [11.0, 1.0]},
    {"label": "second", "vector": [1.0, 10.0]},
    {"label": "second", "vector": [0.5, 9.0]},
    {"label": "second", "vector": [1.5, 8.0]},
    {"label": "second", "vector": [1.0, 11.0]},
]
samples = [{"vector": [9.0, 1.0]}, {"vector": [1.0, 9.0]}, {"id": "missing"}]
common = {"vector_key": "vector", "label_key": "label"}
checks = (
    ("decision_tree", {"criterion": "gini", "random_state": 42}),
    ("knn", {"n_neighbors": 3, "weights": "distance"}),
    ("multinomial_nb", {"alpha": 0.5, "fit_prior": True}),
)

for algorithm, settings in checks:
    output, output_attributes, meta = operator.run(
        [training, samples],
        {**common, **settings},
        {"algorithm": algorithm},
    )
    assert [record["predicted_label"] for record in output[1]] == [
        "first",
        "second",
        None,
    ]
    assert output_attributes == {}
    assert meta.errors == []

unchanged = operator.apply([training], common, {"algorithm": "unknown"})
assert skill.card.operator_id == "classify@2.0.0"
assert unchanged[0] is training
```

# Scikit-learn estimator check

Environment: ml

The first group trains a classifier. The second group checks inference and missing-vector handling.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("sklearn_estimator@2.0.0", level=3)
operator = registry.resolve("sklearn_estimator@2.0.0")
training = [
    {"label": "low", "vector": [0.0, 0.0]},
    {"label": "low", "vector": [0.2, 0.1]},
    {"label": "high", "vector": [9.8, 10.0]},
    {"label": "high", "vector": [10.2, 9.9]},
]
samples = [
    {"id": "a", "vector": [0.1, 0.2]},
    {"id": "b", "vector": [10.0, 10.1]},
    {"id": "missing"},
]

output, output_attributes, meta = operator.run(
    [training, samples],
    {
        "vector_key": "vector",
        "label_key": "label",
        "output_key": "class",
        "random_state": 42,
    },
    {"algorithm": "decisiontreeclassifier"},
)

assert skill.card.operator_id == "sklearn_estimator@2.0.0"
assert [record["class"] for record in output[1]] == ["low", "high", None]
assert output_attributes == {}
assert meta.errors == []
```

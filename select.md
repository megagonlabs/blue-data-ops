# Select

`select@2.0.0` filters the first input group with one comparison. Later groups are not read, and matching records are returned by identity.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `approximate_match` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `eps` | `attributes` | `yes` | `1e-09` | `attribute-spec:float` | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | `finite-positive-number` | `scalar` |
| `operand` | `attributes` | `yes` | `none` | `attribute-spec:str` | `scalar` |
| `operand_key` | `attributes` | `yes` | `none` | `attribute-spec:str` | `scalar` |
| `operand_val` | `attributes` | `yes` | `none` | `attribute-spec:Any` | `scalar` |

## Comparisons and results

Numeric values are compared after conversion to `float`; booleans therefore take part as `0` and `1`. Approximate matching affects only numeric equality and inequality. Strings use ordinary Python ordering. When one side is numeric and the other is not, `!=` is true and every other comparison is false. Other types support only equality and inequality.

Records missing `operand_key` are skipped. No match returns `[[]]`. Empty input or an empty first group returns the raw shape `[]`; `run()` normalizes a successful empty result to `[[]]`. The current `output_attributes` mapping is empty.

## Call boundaries

`validate()` checks the declared settings, operand vocabulary, and nonnegative epsilon. `invoke()` returns `None` when validation fails. `apply()` returns the raw result and can expose a comparison exception from incompatible values. `run()` contains validation and execution failures in `ExecMeta`.

The operator has no registry, provider, model, or data-store side effect.


# Select example

Environment: base

This example filters one group, preserves record identity, and shows both successful-empty and invalid outcomes.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("select@2.0.0", level=3)
operator = registry.resolve("select@2.0.0")
records = [
    [
        {"id": 1, "score": 0.81},
        {"id": 2, "score": 0.93},
        {"id": 3},
    ]
]

selected, output_attributes, meta = operator.run(
    records,
    {"operand_key": "score", "operand": ">=", "operand_val": 0.9},
)
empty, _, empty_meta = operator.run(
    records,
    {"operand_key": "score", "operand": ">", "operand_val": 1.0},
)
invalid, _, invalid_meta = operator.run(
    records,
    {"operand_key": "score", "operand": "contains", "operand_val": 0.9},
)

assert skill.card.operator_id == "select@2.0.0"
assert selected == [[records[0][1]]]
assert selected[0][0] is records[0][1]
assert empty == [[]] and empty_meta.errors == []
assert invalid == [[]] and invalid_meta.errors
assert output_attributes == {}
assert meta.errors == []
```

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

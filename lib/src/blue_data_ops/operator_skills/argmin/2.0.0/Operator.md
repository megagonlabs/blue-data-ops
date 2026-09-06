# Minimum records

`argmin@2.0.0` returns every first-group record tied for the smallest usable value at `argmin_key`. Later groups are ignored.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `argmin_key` | `attributes` | `yes` | `none` | attribute-spec:str; non-empty string; selected data values use `int()` then `float()`, so bytes convert and fractional `Decimal` values truncate | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `return_index` | `attributes` | `yes` | `false` | attribute-spec:bool; execution uses the original value's truthiness | `scalar` |

## Behavior

Missing keys and values that fail numeric conversion are skipped. Equal numeric forms tie. With `return_index=false`, the output contains the original record objects in input order. A truthy value returns one new record, `{"indices": [...]}`; the validated string `"no"` is still truthy during execution.

`apply()` returns `[[]]` when no usable value exists. On empty outer input it also returns `[[]]`, or `[[{"indices": []}]]` when indices were requested. `invoke()` returns `None` for invalid settings. `run()` contains validation, execution, and timeout failures in `ExecMeta`, normalizes empty output to `[[]]`, and returns `{}` for `output_attributes`.

`explain()` uses the shared statistics. The operator has no side effect, provider call, registry call, or optional extra. Its default raw `refiner()` returns `[]`; it has no structured `refine()` surface.

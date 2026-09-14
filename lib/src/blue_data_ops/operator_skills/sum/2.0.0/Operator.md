# Sum

`sum@2.0.0` adds usable values at `sum_key` from the first input group. Later groups are ignored.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `output_key` | `attributes` | `yes` | `"sum"` | `attribute-spec:str` | `scalar` |
| `sum_key` | `attributes` | `yes` | `none` | attribute-spec:str; non-empty string; selected data values use `int()` then `float()`, so bytes convert and fractional `Decimal` values truncate | `scalar` |

## Behavior

Integers and floats count directly, including Boolean values. Other values are converted with `int()` first and `float()` second. Missing keys and conversion failures are skipped. Exceptions outside those conversion failures propagate from the raw calls.

`apply()` returns one new result record. Empty input, an empty first group, or no convertible values produces `[[{"sum": 0}]]`, a successful non-empty result. `invoke()` returns `None` for invalid settings. `run()` contains execution and timeout failures in `ExecMeta`; `output_attributes` is `{}`.

`explain()` uses the shared statistics. There is no side effect, external disclosure, or optional extra.

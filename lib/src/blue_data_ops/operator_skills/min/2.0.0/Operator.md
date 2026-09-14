# Minimum value

`min@2.0.0` reduces the first input group to the smallest usable value at `min_key`. Later groups are ignored.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `min_key` | `attributes` | `yes` | `none` | attribute-spec:str; non-empty string; selected data values use `int()` then `float()`, so bytes convert and fractional `Decimal` values truncate | `scalar` |
| `output_key` | `attributes` | `yes` | `"min"` | `attribute-spec:str` | `scalar` |

## Behavior

Integers and floats are compared directly. Other values are converted with `int()` first and `float()` second. Missing keys and conversion failures are skipped. The first value at an equal minimum supplies the returned numeric type.

`apply()` returns one new record. Empty input, an empty first group, a missing key, or no convertible value produces `[[{"min": None}]]`; this is a successful result. `invoke()` returns `None` for invalid settings. Raw exceptions outside the guarded conversions propagate, while `run()` contains them and timeout failures in `ExecMeta`. `output_attributes` is `{}`.

`explain()` uses the shared statistics. There is no side effect, external disclosure, or optional extra.

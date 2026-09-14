# Maximum value

`max@2.0.0` reduces the first input group to the largest usable value at `max_key`. Later groups are ignored.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `max_key` | `attributes` | `yes` | `none` | attribute-spec:str; non-empty string; selected data values use `int()` then `float()`, so bytes convert and fractional `Decimal` values truncate | `scalar` |
| `output_key` | `attributes` | `yes` | `"max"` | `attribute-spec:str` | `scalar` |

## Behavior

Integers and floats are compared directly. Other values are converted with `int()` first and `float()` second. Missing keys and conversion failures are skipped. The first value at an equal maximum supplies the returned numeric type.

`apply()` returns one new record. Empty input, an empty first group, a missing key, or no convertible value produces `[[{"max": None}]]`; this is a successful result. `invoke()` returns `None` for invalid settings. Raw exceptions outside the guarded conversions propagate, while `run()` contains them and timeout failures in `ExecMeta`. `output_attributes` is `{}`.

`explain()` uses the shared statistics. There is no side effect, external disclosure, or optional extra.

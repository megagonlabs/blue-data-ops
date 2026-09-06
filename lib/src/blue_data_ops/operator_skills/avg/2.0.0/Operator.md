# Average

`avg@2.0.0` calculates one arithmetic mean from the first input group. Later groups are ignored.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `avg_key` | `attributes` | `yes` | `none` | attribute-spec:str; non-empty string; selected data values use `int()` then `float()`, so bytes convert and fractional `Decimal` values truncate | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `output_key` | `attributes` | `yes` | `"avg"` | `attribute-spec:str` | `scalar` |

## Behavior

Integers and floats count directly, including Boolean values. Other values are converted with `int()` first and `float()` second. A string such as `"3.5"` reaches the floating-point conversion; an unconvertible value or missing key is skipped. Exceptions other than conversion failures propagate from the raw calls.

`apply()` returns one new result record. Empty input, an empty first group, or no convertible values produces `[[{"avg": 0}]]`, which is a successful non-empty result. `invoke()` returns `None` for invalid settings. `run()` contains execution and timeout failures in `ExecMeta`; `output_attributes` is `{}`.

`explain()` uses the shared statistics. The operator has no side effect, provider call, registry call, or optional extra. Its default raw `refiner()` returns `[]`; it has no structured `refine()` surface.

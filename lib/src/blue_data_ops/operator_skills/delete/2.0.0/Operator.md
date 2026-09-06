# Delete records

`delete@2.0.0` removes positions from the first input group. Later groups are ignored.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `delete_idx` | `attributes` | `yes` | `[]` | attribute-spec:Union[int, list[int]]; Boolean values count as integers | `structured` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |

## Behavior

Negative positions count from the end. Duplicate positions are removed once and out-of-range positions are ignored. Omitting `delete_idx` is a no-op. A scalar out-of-range index returns the original first-group list, while a list of out-of-range indices returns a shallow list copy. Successful deletion also returns a shallow list copy and retains the original record objects.

Raw `apply()` returns `[]` for empty outer input or an empty first group. `invoke()` returns `None` for an invalid setting. `run()` materializes the default list, contains failures, normalizes an empty result to `[[]]`, and returns `{}` for `output_attributes`.

`explain()` uses shared statistics. There is no external disclosure, side effect, or optional extra. The default raw `refiner()` returns `[]`; no structured `refine()` method exists.

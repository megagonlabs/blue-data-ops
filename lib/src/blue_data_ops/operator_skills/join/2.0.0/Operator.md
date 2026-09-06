# Join groups

`join@2.0.0` joins two or more record groups through an ordered key list for each group. It supports composite keys and more than two inputs.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `join_on` | `attributes` | `yes` | `[]` | attribute-spec:list[list[str]]; custom validation requires non-empty lists but not one entry per input group | `structured` |
| `join_suffix` | `attributes` | `yes` | `[]` | attribute-spec:list[str]; empty uses `_dsN`; non-empty length must match `join_on`, while duplicates pass validation and fail the raw guard | `structured` |
| `join_type` | `attributes` | `yes` | `"inner"` | attribute-spec:str; `inner`, `left`, `right`, or `outer` | `scalar` |
| `keep_keys` | `attributes` | `yes` | `"left"` | attribute-spec:str; `left` or `both` | `scalar` |

## Behavior

Repeated key matches produce the Cartesian combinations for that key. `keep_keys=left` keeps the left key names; `both` retains each source's keys under suffixes. Colliding non-key names are suffixed, and unmatched outer records receive `None` for fields contributed by the absent side. Output records are newly built.

Raw guards return `[]` when the number of key lists does not equal the number of input groups, or when supplied suffixes repeat. A valid join with no matches returns `[[]]`. Empty outer input and a single empty group return `[]`; two input groups with an empty side return `[[]]`. `invoke()` returns `None` for settings rejected by validation, but guard failures can pass validation and return `[]`. `run()` normalizes these empty shapes to `[[]]`, contains exceptions, and returns `{}` for `output_attributes`.

`explain()` uses shared statistics. There is no external disclosure, side effect, or optional extra. The default raw `refiner()` returns `[]`; no structured `refine()` method exists.

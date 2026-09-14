# Insert records

`insert@2.0.0` inserts records into a shallow copy of the first input group. A non-empty second group is the insertion source and takes precedence over `insert_records`.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `insert_idx` | `attributes` | `yes` | `-1` | attribute-spec:Union[int, list[int]]; list entries below `-1` rejected; some non-list scalar values pass validation but fail in raw execution | `structured` |
| `insert_records` | `attributes` | `yes` | `[]` | attribute-spec:list[dict]; a tuple currently validates but fails in raw execution | `structured` |

## Behavior

Raw `apply()` treats any negative scalar as append, while validation accepts only `-1`. Non-negative scalar positions insert before that position, and positions past the end append. With a position list, missing positions append the remaining records and extra positions are ignored. Repeated positions preserve insertion order. The output list is new, but input and inserted record objects are retained.

Raw `apply()` returns `[]` when the outer input or first group is empty, even if `insert_records` is present. `invoke()` returns `None` for settings the validator rejects. The current validator accepts tuple, string, and float scalar forms that can raise `AttributeError` or `TypeError` in `apply()` and `invoke()`; `run()` contains those failures as `EXECUTION_FAILED` and returns `[[]]`. `output_attributes` is `{}`.

`explain()` uses shared statistics. The operator has no external disclosure, persistent side effect, or optional extra.

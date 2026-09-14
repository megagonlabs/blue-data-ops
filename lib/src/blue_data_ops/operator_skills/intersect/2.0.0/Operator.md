# Intersection

`intersect@2.0.0` keeps records from the first non-empty input group whose signatures occur in every other non-empty group. Empty groups are ignored.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `match_option` | `attributes` | `yes` | `"key_match"` | attribute-spec:str; `key_match` or `seq_match` | `scalar` |

## Behavior

`key_match` compares sorted field names and values. `seq_match` ignores field names and compares values in insertion order. Numeric forms are converted to float, NaNs share one sentinel, and nested containers are normalized recursively. The base group's duplicates are retained, and returned records are the original base objects.

Raw `apply()` returns `[]` when every group is empty and `[[]]` for a valid intersection with no matches. An invalid match option can raise `ValueError` when a signature is built. `invoke()` returns `None` for that invalid setting. `run()` contains failures, normalizes empty output to `[[]]`, and returns `{}` for `output_attributes`.

The operator has no custom `explain()`, external disclosure, side effect, or optional extra.

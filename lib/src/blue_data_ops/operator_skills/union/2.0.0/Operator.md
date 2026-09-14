# Union

`union@2.0.0` appends records from all input groups and removes duplicates. The first record for a signature is retained as the original object.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `match_option` | `attributes` | `yes` | `"key_match"` | attribute-spec:str; `key_match` or `seq_match` | `scalar` |

## Behavior

`key_match` builds a signature from sorted key/value pairs, so key order does not matter and differently named fields remain different. `seq_match` ignores keys and compares values in insertion order. Numeric forms such as `1`, `1.0`, and `True` collide. NaNs share one sentinel; lists, mappings, and sets are normalized recursively. A value that remains unhashable falls back to its string form.

Raw `apply()` returns `[]` for empty outer input and `[[]]` when input groups contain no records. `run()` normalizes either to `[[]]` and marks it empty. Invalid input produces structured validation output from `run()` and `None` from `invoke()`; direct `apply()` can raise `ValueError` once it builds a signature. Successful `output_attributes` is `{}`.

`explain()` uses shared statistics. The operator has no provider, registry, optional dependency, or side effect.

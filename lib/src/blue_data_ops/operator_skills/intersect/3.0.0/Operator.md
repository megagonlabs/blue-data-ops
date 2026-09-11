# Intersection

`intersect@3.0.0` keeps records from the first input group whose signatures occur in every other supplied group. Every group is an operand. Resolve the exact version with `versioned_registry().resolve("intersect@3.0.0")`.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `match_option` | `attributes` | `yes` | `"key_match"` | attribute-spec:str; `key_match` or `seq_match` | `scalar` |

## Result

`key_match` compares sorted field names and recursively normalized values. `seq_match` ignores field names and compares values in insertion order. Numeric forms are converted to float, and NaNs share one sentinel. Nested mappings and containers are normalized. Matching duplicates from the first group are retained in order, and returned records are the original first-group objects.

At least two groups are required. After group count and settings validate, any empty operand makes the intersection successfully empty. The result is `[[]]`, attributes are `{}`, errors are empty, and `is_empty` is true. A single empty group is invalid rather than successful empty.

## Calls and errors

Check `exec_meta.errors` first. Fewer than two groups or an unsupported `match_option` produces `INVALID_INPUT` at `VALIDATE`. For validated JSON-like records, recursive signature matching has no separate declared execution-failure case. A malformed result produces `EXECUTION_RESULT_INVALID` at `NORMALIZE`, and a timeout produces `OPERATOR_TIMEOUT`. Failed structured calls return `[[]]`, `{}`, and `is_empty=False`.

`run()` returns `(output_data, output_attributes, exec_meta)`. Raw `apply()` returns only data and bypasses input validation; its body keeps the same empty-operand result. Raw `invoke()` validates first and returns `None` on rejection. Neither raw path returns `ExecMeta`.

Optional `exec_meta.traces["elapsed_ms"]` is finite and nonnegative. Missing traces are valid. See [examples](examples.md) for nested matching, duplicate preservation, and an empty operand.

For a structurally valid bundle, `run()` may also record `input_shape` before validation and
execution. The value has `groups` and `rows_per_group`; its counts do not change if the caller data
is later mutated. Invalid bundle structure omits this key.

After successful normalization, `output_shape` uses the same fields. Failures and timeouts omit it.
An all-empty successful output is normalized to `[[]]`, while a mixed multi-group output retains a
zero count for each empty group. Both shape keys are optional.

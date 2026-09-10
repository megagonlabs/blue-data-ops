# Average

`avg@3.0.0` calculates one arithmetic mean from the first input group. Later groups are ignored. Call `versioned_registry().resolve("avg@3.0.0").run(...)` to receive the average, its contribution count, and execution metadata.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `avg_key` | `attributes` | `yes` | `none` | attribute-spec:str; required non-empty string naming the field to average | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `output_key` | `attributes` | `yes` | `"avg"` | attribute-spec:str; names the result field | `scalar` |

## Result

Input is a list of record groups, `list[list[dict]]`. Integers and floats contribute directly, including `True` as 1 and `False` as 0. Other values try `int()` before `float()`: numeric bytes can convert, a fractional `Decimal` can truncate through `int()`, and `"3.5"` reaches `float()`. A missing field, `None`, or a value that fails both conversions is skipped. Only `ValueError` and `TypeError` conversion failures are suppressed; other exceptions are execution failures.

The average stays in `output_data` as `[[{"avg": value}]]`, or under the chosen `output_key`. When no values contribute, the result is `[[]]` with `errors=[]` and `is_empty=True`. A real average of zero is a record, with `is_empty=False`.

`output_attributes["num_values_used"]` is a nonnegative integer counting the accepted values used in the denominator, from the selected field in the first group. It is supplied on successful calls, including 0 for successful empty output. It does not count all input rows or only finite numbers. For example, `"nan"` is accepted, contributes to the count, and can produce a NaN average. A missing attribute means unavailable, not zero; callers should tolerate missing or unfamiliar keys.

| First-group values | Data with the default output key | `num_values_used` |
|---|---|---|
| `0, 0` | `[[{"avg": 0.0}]]` | `2` |
| `10, 20, "bad"` | `[[{"avg": 15.0}]]` | `2` |
| `True, False` | `[[{"avg": 0.5}]]` | `2` |
| `None, "bad"` | `[[]]` | `0` |

## Calls and errors

Check `exec_meta.errors` before using `is_empty` or the data. Missing or invalid `avg_key` is `INVALID_INPUT` at `VALIDATE`. Execution exceptions are contained by `run()`; malformed results use `EXECUTION_RESULT_INVALID` at `NORMALIZE`, and timeout uses `OPERATOR_TIMEOUT`. Failed calls return `[[]]`, `{}`, and `is_empty=False`.

`run()` returns `(output_data, output_attributes, exec_meta)` and materializes declared defaults. Raw `apply()` returns only data and bypasses input validation and the structured error/timeout boundary. Raw `invoke()` validates first and returns `None` on rejection; neither raw call returns the contribution count or `ExecMeta`. Existing exact IDs keep their own behavior: `avg@2.0.0` returns an average-zero record when there are no contributors.

Optional `exec_meta.traces["elapsed_ms"]` is nonnegative monotonic wall-clock time from entry into `run()` until that call's result is ready, including validation and waiting. On timeout it ends at the timeout result, not at the worker's eventual completion. Missing traces or logs are valid; do not use log text as a control signal.

See [examples](examples.md) for a standalone call and caller-side use of the result.

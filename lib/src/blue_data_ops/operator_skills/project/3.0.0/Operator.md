# Project fields

`project@3.0.0` copies selected fields from records in the first input group and can rename them. Later groups are ignored. Resolve the exact version with `versioned_registry().resolve("project@3.0.0")`.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `kept_keys` | `attributes` | `yes` | `[]` | attribute-spec:list[str]; required and non-empty | `structured` |
| `key_mapping` | `attributes` | `yes` | `{}` | attribute-spec:dict[str, str]; mapped sources must be kept and output names must not collide | `structured` |

## Result

Field order follows `kept_keys`. Missing fields are omitted, so a source record with none of the requested fields becomes `{}` in the output. That empty mapping is a data record and does not make the result empty. Each output record is new. A mapping can swap names, but it cannot make two selected fields use the same output name.

A valid call with no first-group rows is successful empty: output is `[[]]`, attributes are `{}`, errors are empty, and `is_empty` is true. An empty `kept_keys` list is invalid even when the first group is empty.

## Calls and errors

Check `exec_meta.errors` first. Missing or empty `kept_keys`, invalid key types, and conflicting mappings produce `INVALID_INPUT` at `VALIDATE`. For validated JSON-like records, projection performs field lookup and builds new mappings without a separate declared execution-failure case. A malformed result produces `EXECUTION_RESULT_INVALID` at `NORMALIZE`, and a timeout produces `OPERATOR_TIMEOUT`. Failed structured calls return `[[]]`, `{}`, and `is_empty=False`.

`run()` returns `(output_data, output_attributes, exec_meta)` and validates before determining successful empty. Raw `apply()` returns only data and bypasses structured validation; with an empty key list it keeps the compatibility result `[]`. Raw `invoke()` validates first and returns `None` on rejection. Neither raw path returns `ExecMeta`.

Optional `exec_meta.traces["elapsed_ms"]` is finite and nonnegative. Missing traces are valid. See [examples](examples.md) for renamed fields, a missing field, and an invalid empty key list.

For a structurally valid bundle, `run()` may also record `input_shape` before validation and
execution. The value has `groups` and `rows_per_group`; its counts do not change if the caller data
is later mutated. Invalid bundle structure omits this key.

After successful normalization, `output_shape` uses the same fields. Failures and timeouts omit it.
An all-empty successful output is normalized to `[[]]`, while a mixed multi-group output retains a
zero count for each empty group. Both shape keys are optional.

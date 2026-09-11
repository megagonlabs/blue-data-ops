# Insert records

`insert@3.0.0` inserts records into a shallow copy of the first input group. A nonempty second group is the insertion source and takes precedence over `insert_records`. Resolve the exact version with `versioned_registry().resolve("insert@3.0.0")`.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `insert_idx` | `attributes` | `yes` | `-1` | attribute-spec:Union[int, list[int]]; values below `-1` rejected; some non-list scalar values pass type validation but fail during execution | `structured` |
| `insert_records` | `attributes` | `yes` | `[]` | attribute-spec:list[dict]; used when no nonempty second group is present | `structured` |

## Result

An existing empty first group can be populated from `insert_records` or a nonempty second group. An empty second group falls back to `insert_records`. A missing outer group, `[]`, has no insertion target and remains successful empty. If no insertion records are supplied, the operator returns a shallow copy of the first group.

With a scalar position, `-1` appends, positions from zero through the current length insert there, and positions past the end append. With a position list, each entry applies to the corresponding inserted record; missing positions append the remaining records and extra positions are ignored. Repeated positions preserve insertion order. The output list is new, while source and inserted record objects are retained.

Successful empty output is `[[]]` with `{}`, no errors, and `is_empty=True`. A populated empty group is nonempty output. Tensor data and `output_attributes` remain separate; this operator adds no result attributes.

## Calls and errors

Check `exec_meta.errors` first. Invalid positions below `-1` produce `INVALID_INPUT` at `VALIDATE`. Settings admitted by the lax type boundary but unusable by the body, such as string `insert_idx="0"`, produce `EXECUTION_FAILED` at `EXECUTE`. A malformed result produces `EXECUTION_RESULT_INVALID` at `NORMALIZE`, and a timeout produces `OPERATOR_TIMEOUT`. Failed calls return `[[]]`, `{}`, and `is_empty=False`.

`run()` returns `(output_data, output_attributes, exec_meta)`. Raw `apply()` bypasses structured validation and returns only data; body exceptions propagate. Raw `invoke()` validates first and returns `None` on rejection, but body exceptions still propagate. Neither raw path returns `ExecMeta`.

Optional `exec_meta.traces["elapsed_ms"]` is finite and nonnegative. Missing traces are valid. See [examples](examples.md) for second-group precedence and a group-less successful-empty call.

For a structurally valid bundle, `run()` may also record `input_shape` before validation and
execution. The value has `groups` and `rows_per_group`; its counts do not change if the caller data
is later mutated. Invalid bundle structure omits this key.

After successful normalization, `output_shape` uses the same fields. Failures and timeouts omit it.
An all-empty successful output is normalized to `[[]]`, while a mixed multi-group output retains a
zero count for each empty group. Both shape keys are optional.

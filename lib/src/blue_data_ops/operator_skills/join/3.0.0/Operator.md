# Join groups

`join@3.0.0` joins two or more record groups using an ordered key list for each group. It supports composite keys and more than two inputs. Resolve the exact version with `versioned_registry().resolve("join@3.0.0")` and use `run()` to distinguish no matches from invalid settings.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `join_on` | `attributes` | `yes` | `[]` | attribute-spec:list[list[str]]; required non-empty key list per input group, with at least two groups | `structured` |
| `join_suffix` | `attributes` | `yes` | `[]` | attribute-spec:list[str]; omitted or [] uses _dsN; otherwise one distinct non-empty string per group | `structured` |
| `join_type` | `attributes` | `yes` | `"inner"` | attribute-spec:str; inner, left, right, or outer | `scalar` |
| `keep_keys` | `attributes` | `yes` | `"left"` | attribute-spec:str; left or both | `scalar` |

## Result

Input is a list of record groups, `list[list[dict]]`. Each group has one corresponding `join_on` list, whose entries are field-name strings. Supplied suffixes must have the same count as the groups and must be distinct non-empty strings. These checks still apply when groups are empty. Omitting `join_suffix` or passing `[]` uses `_ds0`, `_ds1`, and so on.

Output is one group of newly built joined records. Repeated matches produce every matching combination for that key. Colliding non-key field names receive suffixes. `keep_keys="left"` keeps the left key names; `"both"` retains both sources' keys, suffixing names that collide. Unmatched rows retained by an outer join have `None` for fields from the absent side. Key fields are read with `record.get()`, so missing fields contribute `None` and can match other missing keys.

A valid inner join with no matches returns `[[]]`, `errors=[]`, and `is_empty=True`. A valid join that produces records has `is_empty=False`. `output_attributes` is `{}`; the joined fields remain in the data and no provenance attribute is returned.

## Calls and errors

Check `exec_meta.errors` first. Fewer than two groups, a group/key-list count mismatch, invalid supplied suffixes, or unsupported settings produce `INVALID_INPUT` at `VALIDATE`, including when all groups are empty. These are different from a valid no-match result. Errors during joining, such as unhashable key values, are execution failures. `run()` contains them; malformed output uses `EXECUTION_RESULT_INVALID` at `NORMALIZE`, and timeout uses `OPERATOR_TIMEOUT`. Failure returns `[[]]`, `{}`, and `is_empty=False`.

`run()` returns `(output_data, output_attributes, exec_meta)` and materializes declared defaults. Raw `apply()` returns only data and bypasses input validation and the structured error/timeout boundary; its repeated-suffix guard still returns `[]`. Omitting `join_on` reaches the `[]` execution fallback in raw `apply()`, so it also returns `[]`. The same omission makes `invoke()` return `None` and makes `run()` report `INVALID_INPUT` at `VALIDATE`. Raw `invoke()` validates first and returns `None` on rejection, including repeated suffixes. Use `run()` when handling caller input. Existing exact IDs retain their behavior: with otherwise valid input, repeated suffixes can produce a successful-empty `run()` result in `join@2.0.0`.

Optional `exec_meta.traces["elapsed_ms"]` measures nonnegative monotonic wall-clock time from entry into `run()` until its result is ready, including validation and waiting. A timeout value ends at the returned timeout result, not the worker's eventual completion. Traces and logs may be empty; do not infer zero elapsed time from a missing key or parse logs to control execution.

See [examples](examples.md) for joined records flowing into an average and for no-match and invalid-input calls.

For a structurally valid bundle, `run()` may also record `input_shape` before validation and
execution. The value has `groups` and `rows_per_group`; its counts do not change if the caller data
is later mutated. Invalid bundle structure omits this key.

After successful normalization, `output_shape` uses the same fields. Failures and timeouts omit it.
An all-empty successful output is normalized to `[[]]`, while a mixed multi-group output retains a
zero count for each empty group. Both shape keys are optional.

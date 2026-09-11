# Insert table rows

`insert_table@3.0.0` writes record groups to an existing table through a `RegistrySeam` and returns the flowing records on success. Resolve it with `versioned_registry().resolve("insert_table@3.0.0")` and call `run()` to receive optional insertion counts and execution errors alongside the data.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `batch_size` | `attributes` | `yes` | `100` | attribute-spec:int; greater than zero; Boolean true passes because it is an integer | `scalar` |
| `collection` | `attributes` | `yes` | `"public"` | attribute-spec:str; retained in the schema but has no effect on insertion | `scalar` |
| `data_registry` | `properties` | `no` | `none` | helper:resolve_registry; RegistrySeam or raw DataRegistry; another value falls through to naming keys | `seam` |
| `data_registry.name` | `properties` | `no` | `none` | helper:resolve_registry; used only with a truthy platform.name; converted to string | `seam` |
| `database` | `attributes` | `yes` | `"default"` | attribute-spec:str; required non-blank string | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `platform.name` | `properties` | `no` | `none` | helper:resolve_registry; used only with a truthy data_registry.name; converted to string | `seam` |
| `source` | `attributes` | `yes` | `"default_source"` | attribute-spec:str; required non-blank string | `scalar` |
| `table` | `attributes` | `yes` | `""` | attribute-spec:str; required non-blank string | `scalar` |

## Result

Input is a list of record groups, `list[list[dict]]`. Every record must be a non-empty mapping, and all records across the call must have the same set of columns. Empty mappings, non-record entries, and mismatched column sets are rejected before any write. Column order may differ. The operator processes every non-empty group, including groups after an empty first group, and splits writes by `batch_size`.

On successful nonempty output, `output_data` preserves the input groups and rows for downstream use. The optional `output_attributes["num_rows_insert"]` is a nonnegative integer covering the entire successful call when the backend supplies a reliable count. It is not the input row count or a partial-batch receipt. If a successful write's count is unknown, the key is absent; this does not fail the write. A missing count never means zero.

When all groups are empty and the settings and registry setup are valid, the call performs no insert and normalizes the output to `[[]]`, with `num_rows_insert=0`, `errors=[]`, and `is_empty=True`. Attribute validation and registry resolution precede this no-write result. Even an empty call fails when the registry binding is missing.

## Calls and errors

Check `exec_meta.errors` before consuming returned rows or counts. Invalid records or attributes produce `INVALID_INPUT` at `VALIDATE`. Missing registry setup, connection failures, or database write errors are execution failures. `run()` contains failures in `ExecMeta.errors`; invalid returned data uses `EXECUTION_RESULT_INVALID` at `NORMALIZE`, and timeout uses `OPERATOR_TIMEOUT`. Failed calls return `[[]]`, `{}`, and `is_empty=False`, without a partial count.

A write may partly complete before an error or timeout. Earlier batches may already be committed, and a timed-out worker may still be running. Inspect the target before repeating a write; an error category or `retryable` flag does not establish that a retry is safe. A count from ordinary successful SQLite inserts does not establish behavior for every backend, conflict policy, or trigger.

`run()` returns `(output_data, output_attributes, exec_meta)` and materializes declared defaults. Raw `apply()` returns only data and bypasses input validation and the structured error/timeout boundary. Raw `invoke()` validates first and returns `None` on rejection. Neither raw call supplies insertion attributes or `ExecMeta`. In this version, a missing registry raises `RuntimeError` from raw `apply()`; database exceptions also propagate. In pinned `insert_table@2.0.0`, raw `apply()` can pass rows through after a missing-registry or outer-operation failure, or return `[[]]` on a connection/batch failure. Use `run()` to handle write failures through metadata.

The configured database receives the generated insert statement and row values. `collection` is validated as a string but has no effect on insertion. Optional `exec_meta.traces["elapsed_ms"]` measures nonnegative monotonic wall-clock time from entry into `run()` until its result is ready, including validation and waiting. On timeout it measures until the timeout result, not the worker's eventual completion. Missing traces or logs do not establish that no write occurred.

See the [disposable SQLite example](examples.md) for source setup, count comparison with stored rows, and downstream use of the returned data.

For a structurally valid bundle, `run()` may also record `input_shape` before validation and
execution. The value has `groups` and `rows_per_group`; its counts do not change if the caller data
is later mutated. Invalid bundle structure omits this key.

After successful normalization, `output_shape` uses the same fields. Failures and timeouts omit it.
An all-empty successful output is normalized to `[[]]`, while a mixed multi-group output retains a
zero count for each empty group. Both shape keys are optional.

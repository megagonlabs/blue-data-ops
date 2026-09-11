# Vector embed

`vector_embed@3.0.0` converts record text into embeddings and processes every supplied group. Resolve this exact version explicitly; ordinary planner and MCP selection remains on version 2.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `add_meta_data` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `append` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `batch_size` | `properties` | `no` | `32` | runtime-check; positive integer | `scalar` |
| `delimiter` | `attributes` | `yes` | `"\n"` | `attribute-spec:str` | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `model_ref` | `attributes` | `yes` | `"all-MiniLM-L6-v2"` | `attribute-spec:str` | `scalar` |
| `normalize` | `properties` | `no` | `false` | runtime-check; Boolean | `scalar` |
| `on_missing_fields` | `attributes` | `yes` | `"raise"` | attribute-spec:str; `raise` or `use_empty` | `scalar` |
| `text_field` | `attributes` | `yes` | `[]` | attribute-spec:list[str]; list of strings | `structured` |

## Groups and records

Each nonempty group is encoded separately and remains in its input position. Empty groups beside nonempty groups are preserved. One model is constructed for the call, then `encode` runs once for each nonempty group. Fallback IDs start at `index_0` in each group.

When every group is empty, or the outer bundle is empty, `run()` returns the normalized successful-empty result `[[]]` without importing the model package. Attribute and property validation still runs first.

With `text_field`, the selected values are converted to strings and joined with `delimiter`. Missing fields raise by default; `use_empty` substitutes an empty string. With no selected fields, values from all record keys are joined in sorted-key order.

`append=true` copies each input record before adding `id` and `embedding`. Otherwise each output record contains those two keys only. `add_meta_data=true` also adds `embed.model`, `embed.dim`, and `embed.fields` to each record. These keys remain tensor data. `output_attributes` is `{}`.

## Dependencies and calls

A nonempty call imports `sentence_transformers` and constructs `model_ref`. Model availability and any download behavior belong to that installed library and its configuration. The base package alone is enough for the all-empty example.

Check `exec_meta.errors` before `is_empty` or output records. Invalid settings produce structured validation errors. Missing dependencies, model failures, record-field errors, and unusable embedding results are execution errors. Failed calls return `[[]]`, `{}`, and `is_empty=False`.

`run()` materializes declared defaults and returns `(output_data, output_attributes, exec_meta)`. Raw `apply()` returns data only, skips the structured validation and error boundary, and exposes execution exceptions. Raw `invoke()` validates first, returns `None` on rejection, and also exposes later execution exceptions. Neither raw method returns `ExecMeta`.

Successful structured calls may include a finite, nonnegative `exec_meta.traces["elapsed_ms"]`. The trace is optional. See [examples](examples.md) for a dependency-free empty-path check.

For a structurally valid bundle, `run()` may also record `input_shape` before validation and
execution. The value has `groups` and `rows_per_group`; its counts do not change if the caller data
is later mutated. Invalid bundle structure omits this key.

After successful normalization, `output_shape` uses the same fields. Failures and timeouts omit it.
An all-empty successful output is normalized to `[[]]`, while a mixed multi-group output retains a
zero count for each empty group. Both shape keys are optional.

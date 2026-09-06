# Vector embed

`vector_embed@2.0.0` converts record text into embeddings. A nonempty call imports `sentence_transformers` and constructs the selected model before it validates individual group records.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `add_meta_data` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `append` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `batch_size` | `properties` | `no` | `32` | `runtime-check` | `scalar` |
| `delimiter` | `attributes` | `yes` | `"\n"` | `attribute-spec:str` | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | `finite-positive-number` | `scalar` |
| `model_ref` | `attributes` | `yes` | `"all-MiniLM-L6-v2"` | `attribute-spec:str` | `scalar` |
| `normalize` | `properties` | `no` | `false` | `runtime-check` | `scalar` |
| `on_missing_fields` | `attributes` | `yes` | `"raise"` | `attribute-spec:str` | `scalar` |
| `text_field` | `attributes` | `yes` | `[]` | `attribute-spec:list[str]` | `structured` |

## Input and output

When `text_field` is nonempty, the selected values are converted to text and joined with `delimiter`. Missing fields raise by default; `use_empty` substitutes an empty string. With no selected fields, values from all record keys are joined in sorted-key order.

`append=true` shallow-copies the input record before adding `embedding`; otherwise the result contains only `id` and `embedding`. A missing ID becomes `index_<n>`. `add_meta_data=true` adds `embed.model`, `embed.dim`, and `embed.fields`. The output records are new objects, and `output_attributes` is empty.

## Empty, dependency, and model behavior

Empty input or an empty first group returns the successful-empty shape `[[]]` without importing the model package. If the first group is empty, later groups are not processed. Empty later groups are retained after a nonempty first group.

Nonempty execution needs the `vector` extra and may download model files under the model library's configuration. `apply()` and `invoke()` expose missing dependencies, model-load failures, missing fields, and malformed embedding results. `run()` contains them as execution errors; missing vector modules use the generic `EXECUTION_FAILED` result. The shared timeout does not guarantee cancellation of model work.

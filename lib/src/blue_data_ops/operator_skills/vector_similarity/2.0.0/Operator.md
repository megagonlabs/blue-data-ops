# Vector similarity

`vector_similarity@2.0.0` compares records from exactly two input groups. `cartesian` mode returns every left-right pair. `pairwise` mode requires equal group lengths and compares matching positions.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `add_meta_data` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `comparison_mode` | `attributes` | `yes` | `"cartesian"` | `attribute-spec:str` | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | `finite-positive-number` | `scalar` |
| `fields` | `attributes` | `yes` | `none` | `attribute-spec:list[str]` | `structured` |
| `metric` | `attributes` | `yes` | `"cosine"` | `attribute-spec:str` | `scalar` |
| `model_ref` | `attributes` | `yes` | `"all-MiniLM-L6-v2"` | `attribute-spec:str` | `scalar` |
| `normalize` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `on_missing_embedding` | `attributes` | `yes` | `"raise"` | `attribute-spec:str` | `scalar` |
| `on_missing_fields` | `attributes` | `yes` | `"raise"` | `attribute-spec:str` | `scalar` |
| `threshold` | `attributes` | `yes` | `none` | `attribute-spec:float` | `scalar` |

## Embeddings and results

Existing one-dimensional embeddings avoid model construction, and `fields` may then be omitted. With `on_missing_embedding=embed_missing`, `fields` names one text field for each side. This path needs the `vector` extra and may download model files under the model library's configuration.

The `cosine`, `dot`, and `l2` metrics are supported. `l2` is negative distance, so a larger value remains more similar. A zero vector produces a cosine score of zero. `normalize=true` normalizes each embedding before scoring.

Each result contains `id`, `left_id`, `right_id`, and `similarity.score`. Metadata mode adds metric and comparison mode, and adds the model only when the call generated an embedding. A threshold adds `similarity.threshold` and `similarity.passed`. Missing IDs use `left_<n>` and `right_<n>`.

## Failure behavior

`run()` contains validation and execution failures as `[[]]` with metadata. `invoke()` returns `None` when validation fails, while later shape or embedding errors remain visible. Direct `apply()` exposes those errors and missing optional dependencies.

Two empty groups pass validation but fail during embedding preparation because their dimensions cannot be established. Successful output is a new result group. The current `output_attributes` mapping is empty, and the operator has no registry, provider, or data-store side effect.

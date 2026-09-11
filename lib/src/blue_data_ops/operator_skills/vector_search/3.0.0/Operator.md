# Vector search

`vector_search@3.0.0` ranks records in each input group against a text query or an embedding query. Resolve this exact version explicitly; ordinary planner and MCP selection remains on version 2.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `add_meta_data` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `batch_size` | `properties` | `no` | `32` | runtime-check; positive integer | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `metric` | `attributes` | `yes` | `"cosine"` | attribute-spec:str; `cosine`, `dot`, or `l2` | `scalar` |
| `min_score` | `attributes` | `yes` | `none` | attribute-spec:float; explicit attribute `None` is invalid | `scalar` |
| `model_ref` | `attributes` | `yes` | `"all-MiniLM-L6-v2"` | `attribute-spec:str` | `scalar` |
| `normalize` | `attributes` | `yes` | `false` | attribute-spec:bool; explicit attribute `None` is invalid | `scalar` |
| `normalize` | `properties` | `no` | `none` | runtime-check; `None` is false-like | `scalar` |
| `on_missing_embedding` | `attributes` | `yes` | `"embed_missing"` | attribute-spec:str; `embed_missing` or `raise` | `scalar` |
| `on_missing_fields` | `attributes` | `yes` | `"raise"` | attribute-spec:str; `raise` or `use_empty` | `scalar` |
| `query` | `attributes` | `yes` | `none` | attribute-spec:str \| dict; required string or embedding object | `structured` |
| `search_fields` | `attributes` | `yes` | `[]` | attribute-spec:list[str]; list of strings | `structured` |
| `top_k` | `attributes` | `yes` | `10` | attribute-spec:int; explicit attribute `None` is invalid | `scalar` |
| `top_k` | `properties` | `no` | `none` | runtime-check; `None` is unbounded | `scalar` |

## Search-control precedence

The table's Validation column describes structured `run()` and validated `invoke()`. Raw `apply()` bypasses these checks.

`top_k`, `min_score`, and `normalize` use the same selection rule in `run()` and raw `apply()`: a present property wins, then a present attribute, then the declared attribute default. A property is present even when its value is `None`.

For `run()` and validated `invoke()`, the defaults are `top_k=10`, `min_score=None`, and `normalize=false`. Property `top_k=None` is unbounded, while attribute `top_k=None` is invalid. Property `normalize=None` is false-like, while attribute `normalize=None` is invalid. An explicit attribute `min_score=None` fails declared-type validation; a present property `min_score=None` disables filtering. Strings are not converted for any selected control, and `top_k=0` is invalid. The existing Python integer check continues to treat `True` as an integer.

A selected property can override a lower-priority attribute value that has the right declared type, including an attribute `top_k=0`. Declared attribute-type validation runs before selection, so a property does not rescue an attribute with the wrong type.

## Queries and results

An embedding query avoids model construction when every candidate already has an embedding. The query should carry `model`; otherwise `model_ref` must establish the embedding space. Existing candidate embeddings require `embed.model`, and a group's model labels must agree with the effective query model.

A text query and any candidate without an embedding use sentence-transformers. The supported text-embedding model names are `all-MiniLM-L6-v2` and `paraphrase-MiniLM-L6-v2`. This path needs the `vector` extra and may download model files under the model library's configuration. Missing search fields raise by default; `use_empty` supplies empty text. `on_missing_embedding=raise` rejects a candidate without an embedding.

`cosine` and `dot` rank larger scores first. `l2` stores negative distance, so larger remains closer. Filtering by `min_score` happens before sorting and per-group `top_k` truncation. Each copied result record gets `search.score` and one-based `search.rank`. With `add_meta_data=false`, neither optional metadata key is added. With `add_meta_data=true`, `search.metric` is always added, while `search.model` is added only when the effective model is truthy. When an embedding query omits its model and `model_ref` is empty, the normal fallback is `all-MiniLM-L6-v2`, so successful ordinary calls still have a truthy effective model. `output_attributes` remains `{}`.

An empty outer bundle and a valid search with no hits are successful empty results. Invalid controls, malformed candidates, model failures, incompatible embedding spaces, and scoring failures are errors rather than no-hit results. Check `exec_meta.errors` before `is_empty`.

`run()` returns structured errors and may add finite, nonnegative `exec_meta.traces["elapsed_ms"]`. Raw `apply()` returns data only and exposes exceptions. It uses the same control precedence and declared defaults but does not enforce the structured restrictions above; an attribute `None` can therefore reach the body with the same false-like or unbounded effect as a property `None`. Raw `invoke()` returns `None` on validation rejection and exposes later exceptions. See [examples](examples.md) for a precomputed-vector call with no model work.

For a structurally valid bundle, `run()` may also record `input_shape` before validation and
execution. The value has `groups` and `rows_per_group`; its counts do not change if the caller data
is later mutated. Invalid bundle structure omits this key.

After successful normalization, `output_shape` uses the same fields. Failures and timeouts omit it.
An all-empty successful output is normalized to `[[]]`, while a mixed multi-group output retains a
zero count for each empty group. Both shape keys are optional.

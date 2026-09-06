# Vector search

`vector_search@2.0.0` ranks each input group against a text query or an embedding query. Results are copied records with `search.score` and one-based `search.rank`.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `add_meta_data` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `batch_size` | `properties` | `no` | `32` | `runtime-check` | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | `finite-positive-number` | `scalar` |
| `metric` | `attributes` | `yes` | `"cosine"` | `attribute-spec:str` | `scalar` |
| `min_score` | `attributes` | `yes` | `none` | `attribute-spec:float` | `scalar` |
| `min_score` | `properties` | `no` | `none` | `none` | `scalar` |
| `model_ref` | `attributes` | `yes` | `"all-MiniLM-L6-v2"` | `attribute-spec:str` | `scalar` |
| `normalize` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `normalize` | `properties` | `no` | `false` | `runtime-check` | `scalar` |
| `on_missing_embedding` | `attributes` | `yes` | `"embed_missing"` | `attribute-spec:str` | `scalar` |
| `on_missing_fields` | `attributes` | `yes` | `"raise"` | `attribute-spec:str` | `scalar` |
| `query` | `attributes` | `yes` | `none` | `attribute-spec:str \| dict` | `structured` |
| `search_fields` | `attributes` | `yes` | `[]` | `attribute-spec:list[str]` | `structured` |
| `top_k` | `attributes` | `yes` | `10` | `attribute-spec:int` | `scalar` |
| `top_k` | `properties` | `no` | `10` | `runtime-check` | `scalar` |

## Query and candidate embeddings

A text query constructs one of the two supported models, embeds the query, and embeds candidate records that lack `embedding`. An embedding query avoids model construction when every candidate already has an embedding. It should carry `model`; otherwise `model_ref` must establish the embedding space. Existing candidate embeddings require `embed.model`, all values in a group must agree, and the effective query model must match.

The supported model names are `all-MiniLM-L6-v2` and `paraphrase-MiniLM-L6-v2`. Text embedding needs the `vector` extra and may download model files. Missing search fields raise by default; `use_empty` embeds an empty string. `on_missing_embedding=raise` rejects a candidate without an embedding.

`cosine` and `dot` rank larger scores first. `l2` uses negative distance, so larger still means closer. The property `min_score` filters before sorting, and `top_k` truncates each sorted group. Metadata mode adds `search.metric` and `search.model`.

## Contract discrepancy and failures

The card declares `top_k`, `min_score`, and `normalize` as attributes, but this version reads all three only from call-time properties. Attribute values validate and then have no effect. The undeclared `batch_size` property controls model encoding. Callers must use properties for these four controls in this version.

Empty outer input returns `[]` before NumPy or model loading. A text query over an empty group still embeds the query once, then returns `[[]]`. `run()` contains validation, dependency, model, shape, and compatibility failures and returns an empty `output_attributes` mapping. Raw calls expose execution errors.

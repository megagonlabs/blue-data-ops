# Semantic join

`semantic_join@2.0.0` joins the first two input groups by asking the configured LLM client whether record pairs satisfy a natural-language predicate.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `<service_prefix>.*` | `properties:<service_prefix>.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `batch_size` | `attributes` | `yes` | `10` | `attribute-spec:int` | `scalar` |
| `batch_size` | `properties` | `no` | `discarded` | `write-and-discard` | `scalar` |
| `context` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `demonstrations` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `embedding_threshold` | `attributes` | `yes` | `0.7` | `attribute-spec:float` | `scalar` |
| `embedding_threshold` | `properties` | `no` | `discarded` | `write-and-discard` | `scalar` |
| `embeddings_model` | `properties` | `no` | `"paraphrase-MiniLM-L6-v2"` | `none` | `scalar` |
| `estimate_cost` | `attributes` | `yes` | `true` | `attribute-spec:bool` | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | `finite-positive-number` | `scalar` |
| `failure_probability` | `attributes` | `yes` | `0.2` | `attribute-spec:float` | `scalar` |
| `failure_probability` | `properties` | `no` | `0.2` | `attribute-overwrites-property:float` | `scalar` |
| `input_context` | `properties` | `no` | `"$[0]"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_template` | `properties` | `no` | `source-sha256:0a59949299cad5c6b6da04fc9f96046ad564fae39686d55b9fe952fdb0e92f59` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `join_predicate` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `join_suffix` | `attributes` | `no` | `[]` | `none` | `structured` |
| `join_type` | `attributes` | `yes` | `"inner"` | `attribute-spec:str` | `scalar` |
| `keep_keys` | `attributes` | `yes` | `"left"` | `attribute-spec:str` | `scalar` |
| `left_fields` | `attributes` | `yes` | `[]` | `attribute-spec:list[str]` | `structured` |
| `left_suffix` | `attributes` | `yes` | `"_left"` | `attribute-spec:str` | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `llm_client` | `properties` | `no` | `none` | `helper:resolve_llm_client` | `seam` |
| `max_llm_calls` | `attributes` | `yes` | `1000` | `attribute-spec:int` | `scalar` |
| `openai.api` | `properties` | `no` | `"ChatCompletion"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `openai.max_tokens` | `properties` | `no` | `1024` | `none` | `scalar` |
| `openai.model` | `properties` | `no` | `"gpt-6-luna"` | `none` | `scalar` |
| `openai.service_url` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `openai.stream` | `properties` | `no` | `false` | `none` | `scalar` |
| `openai.temperature` | `properties` | `no` | `0` | `none` | `scalar` |
| `optimize_thresholds` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `optimize_thresholds` | `properties` | `no` | `false` | `attribute-overwrites-property:bool` | `scalar` |
| `output_cast` | `properties` | `no` | `"bool"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_path` | `properties` | `no` | `"$.choices[0].message.content"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_strip` | `properties` | `no` | `true` | reserved; Reserved in caller properties; configure trusted operator defaults. | `presence` |
| `output_template` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_transformations` | `properties` | `no` | `source-sha256:c6aba812d55427f013ea4096192a330a9984bff294ea41b48982ba0894185b21` | reserved; Reserved in caller properties; configure trusted operator defaults. | `structured` |
| `precision_target` | `attributes` | `yes` | `0.8` | `attribute-spec:float` | `scalar` |
| `precision_target` | `properties` | `no` | `0.8` | `attribute-overwrites-property:float` | `scalar` |
| `recall_target` | `attributes` | `yes` | `0.8` | `attribute-spec:float` | `scalar` |
| `recall_target` | `properties` | `no` | `0.8` | `attribute-overwrites-property:float` | `scalar` |
| `right_fields` | `attributes` | `yes` | `[]` | `attribute-spec:list[str]` | `structured` |
| `right_suffix` | `attributes` | `yes` | `"_right"` | `attribute-spec:str` | `scalar` |
| `sampling_percentage` | `attributes` | `yes` | `0.1` | `attribute-spec:float` | `scalar` |
| `sampling_percentage` | `properties` | `no` | `0.1` | `attribute-overwrites-property:float` | `scalar` |
| `service_prefix` | `properties` | `no` | `"openai"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `template_syntax` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `use_cache` | `attributes` | `yes` | `true` | `attribute-spec:bool` | `scalar` |
| `use_embedding_filter` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `use_embedding_filter` | `properties` | `no` | `false` | `attribute-overwrites-property:bool` | `scalar` |

## Pair evaluation and join results

Fewer than two input groups returns raw `[]`. Only the first two groups supply records. The undeclared `join_suffix` list is used only as an input-count guard; `left_suffix` and `right_suffix` control actual conflict names.

The operator batches Cartesian-product pairs. Each provider request contains the selected left and right fields, pair indices, predicate, context, and demonstrations. Its cache lasts only for the current invocation. `estimate_cost` writes the estimate to the operator's INFO logger and can raise before client resolution when the predicted call count exceeds `max_llm_calls`.

Inner, left, right, and outer joins return newly constructed records. Conflicting field names receive side-specific suffixes. With `keep_keys=left`, selected right join keys are omitted; `both` retains both sides. A valid join with no matches returns `[[]]` for an inner join.

## Embedding filter and precedence

The optional filter needs the `vector` extra and may download `embeddings_model`. Attribute values overwrite caller properties after the property merge for `use_embedding_filter`, `optimize_thresholds`, `recall_target`, `precision_target`, `sampling_percentage`, and `failure_probability`. The same write also occurs for `embedding_threshold` and `batch_size`, but their property entries are not read back: execution uses the separately passed attribute values.

When embedding setup fails, the operator warns and evaluates all Cartesian pairs. See Strict response handling for the fallback call cost. Threshold optimization can also print diagnostics and tracebacks.

`run()` contains validation, LLM dependency, provider, model, and join failures. Missing LLM modules receive the dependency suggestion; missing vector modules use the generic execution failure. Raw calls expose failures. The current `output_attributes` mapping is empty.

Caller prompt, extraction, and transport controls are reserved, including null or
copied defaults. Dollar placeholders are substituted once; inserted data and Jinja
syntax stay literal. Define custom prompts in trusted operator defaults. Injected
clients retain generation settings, while operator prompt/extraction defaults win.

### Strict response handling

Batch replies must contain exactly `pair_1` through `pair_N`, with native booleans or trimmed, case-insensitive strings. `true`, `yes`, `1`, `match` and `join` mean match; `false`, `no`, `0` and `exclude` mean non-match. `include` is rejected: the previous join parser did not accept it as a positive answer. Positional arrays, numeric values and unknown strings are rejected. Active `@3.0.0` still requires native booleans. All-false replies remain valid. An embedding preparation exception falls back to all Cartesian pairs, requiring ceil(N*M/batch) model calls, where N and M are the two group sizes and batch is `batch_size`. A failure after optimization sampling can add the sample call to that fallback. The `estimate_cost`/`max_llm_calls` check uses the up-front estimate; a fallback can make more calls than the limit. Successful all-low-score embedding passes still make zero model calls. Malformed replies fail through `run()` with `exec_meta.errors`; raw `apply()`/`invoke()` raise.

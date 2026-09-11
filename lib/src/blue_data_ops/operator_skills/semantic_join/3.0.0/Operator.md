# Semantic join

`semantic_join@3.0.0` joins two record groups under a natural-language predicate evaluated by the configured LLM client.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `<service_prefix>.*` | `properties:<service_prefix>.*` | `no` | `none` | helper:resolve_llm_client; Adapter and provider settings passed through client resolution. | `namespace` |
| `batch_size` | `attributes` | `yes` | `10` | attribute-spec:int; optional; Pair count per provider call. This version requires a positive non-Boolean integer. | `scalar` |
| `batch_size` | `properties` | `no` | `discarded` | `write-and-discard` | `scalar` |
| `context` | `attributes` | `yes` | `""` | attribute-spec:str; optional; Domain context sent with each batch. | `scalar` |
| `demonstrations` | `attributes` | `yes` | `""` | attribute-spec:str; optional; In-context examples sent with each batch. | `scalar` |
| `embedding_threshold` | `attributes` | `yes` | `0.7` | attribute-spec:float; optional; Threshold used by embedding filtering. | `scalar` |
| `embedding_threshold` | `properties` | `no` | `discarded` | `write-and-discard` | `scalar` |
| `estimate_cost` | `attributes` | `yes` | `true` | attribute-spec:bool; optional; Compute the existing pair/call estimate before execution. | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Optional finite, positive timeout for `run()`. | `scalar` |
| `failure_probability` | `attributes` | `yes` | `0.2` | attribute-spec:float; optional; Failure-probability input for threshold learning. | `scalar` |
| `failure_probability` | `properties` | `no` | `discarded` | `write-and-discard` | `scalar` |
| `input_context` | `properties` | `no` | `"$[0]"` | none; Controls request templating or response extraction. | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | none; Controls request templating or response extraction. | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | none; Controls request templating or response extraction. | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | none; Controls request templating or response extraction. | `scalar` |
| `input_template` | `properties` | `no` | `source-sha256:0a59949299cad5c6b6da04fc9f96046ad564fae39686d55b9fe952fdb0e92f59` | none; Controls request templating or response extraction. | `scalar` |
| `join_predicate` | `attributes` | `yes` | `""` | attribute-spec:str; optional; Natural-language match condition; blank uses the operator's semantic-equivalence prompt. | `scalar` |
| `join_suffix` | `attributes` | `no` | `[]` | none; no declared `AttributeSpec`; structured validation accepts omission, `None`, `[]`, or a list of exactly two strings; output field names use `left_suffix` and `right_suffix` | `structured` |
| `join_type` | `attributes` | `yes` | `"inner"` | attribute-spec:str; optional; `inner`, `left`, `right`, or `outer`. | `scalar` |
| `keep_keys` | `attributes` | `yes` | `"left"` | attribute-spec:str; optional; `left` omits selected right join fields; `both` retains them. | `scalar` |
| `left_fields` | `attributes` | `yes` | `[]` | attribute-spec:list[str]; required; Left fields sent for matching. An empty list resolves from the first left record. | `structured` |
| `left_suffix` | `attributes` | `yes` | `"_left"` | attribute-spec:str; optional; Suffix for conflicting left fields. | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | helper:resolve_llm_client; Adapter and provider settings passed through client resolution. | `namespace` |
| `llm_client` | `properties` | `no` | `none` | helper:resolve_llm_client; Injects an LLM client. Otherwise the client is resolved from the configured service. | `seam` |
| `max_llm_calls` | `attributes` | `yes` | `1000` | attribute-spec:int; optional; Abort before provider resolution when the estimated upper bound is higher. | `scalar` |
| `openai.api` | `properties` | `no` | `"ChatCompletion"` | none; Provider setting used during client resolution. | `scalar` |
| `openai.max_tokens` | `properties` | `no` | `1024` | none; Provider setting used during client resolution. | `scalar` |
| `openai.model` | `properties` | `no` | `"gpt-4o"` | none; Default model under the default service prefix. | `scalar` |
| `openai.stream` | `properties` | `no` | `false` | none; Provider setting used during client resolution. | `scalar` |
| `openai.temperature` | `properties` | `no` | `0` | none; Provider setting used during client resolution. | `scalar` |
| `optimize_thresholds` | `attributes` | `yes` | `false` | attribute-spec:bool; optional; Learn embedding thresholds from a sample. | `scalar` |
| `optimize_thresholds` | `properties` | `no` | `discarded` | `write-and-discard` | `scalar` |
| `output_cast` | `properties` | `no` | `"bool"` | none; Controls request templating or response extraction. | `scalar` |
| `output_path` | `properties` | `no` | `"$.choices[0].message.content"` | none; Controls request templating or response extraction. | `scalar` |
| `output_strip` | `properties` | `no` | `true` | helper:resolve_llm_client; Controls request templating or response extraction. | `presence` |
| `output_template` | `properties` | `no` | `none` | helper:resolve_llm_client; Controls request templating or response extraction. | `scalar` |
| `output_transformations` | `properties` | `no` | `source-sha256:4c5590a88361773f2b559375ccaed622ddaab9adeb52b16482d5b2ea9d10255b` | none; Controls request templating or response extraction. | `structured` |
| `precision_target` | `attributes` | `yes` | `0.8` | attribute-spec:float; optional; Precision input for threshold learning. | `scalar` |
| `precision_target` | `properties` | `no` | `discarded` | `write-and-discard` | `scalar` |
| `recall_target` | `attributes` | `yes` | `0.8` | attribute-spec:float; optional; Recall input for threshold learning. | `scalar` |
| `recall_target` | `properties` | `no` | `discarded` | `write-and-discard` | `scalar` |
| `right_fields` | `attributes` | `yes` | `[]` | attribute-spec:list[str]; required; Right fields sent for matching. An empty list resolves from the first right record. | `structured` |
| `right_suffix` | `attributes` | `yes` | `"_right"` | attribute-spec:str; optional; Suffix for conflicting right fields. | `scalar` |
| `sampling_percentage` | `attributes` | `yes` | `0.1` | attribute-spec:float; optional; Fraction used by threshold sampling. | `scalar` |
| `sampling_percentage` | `properties` | `no` | `discarded` | `write-and-discard` | `scalar` |
| `service_prefix` | `properties` | `no` | `"openai"` | none; Selects the provider-property namespace. | `scalar` |
| `use_cache` | `attributes` | `yes` | `true` | attribute-spec:bool; optional; Reuse results for identical pairs within this call. | `scalar` |
| `use_embedding_filter` | `attributes` | `yes` | `false` | attribute-spec:bool; optional; Prefilter pairs with embeddings; requires the optional embedding dependency. | `scalar` |
| `use_embedding_filter` | `properties` | `no` | `discarded` | `write-and-discard` | `scalar` |

## Matching and merge behavior

`run()` requires exactly two groups. Candidate pairs are evaluated in batches; each provider response must be an object with exactly `pair_1` through `pair_N`, and every value must be a JSON Boolean. A missing key, extra key, string Boolean, malformed JSON, embedding-filter failure, or threshold-optimization failure fails the whole call with `EXECUTION_FAILED` at `EXECUTE`. There is no partial join result or automatic all-pairs fallback after an enabled optimization fails.

An inner join with no matches produces a successful empty result. Left, right, and outer joins retain their unmatched side. Field conflicts use the configured suffixes. With `keep_keys="left"`, the resolved `right_fields` are omitted from joined records; use `keep_keys="both"` when both selected key sets are needed.

The undeclared `join_suffix` input is a compatibility guard and does not select output names. Structured `run()` and validated `invoke()` accept omission, `None`, `[]`, or exactly two strings in a list; empty and equal strings are allowed. Other values make `run()` report `INVALID_INPUT` at `VALIDATE` before provider or embedding work, while `invoke()` returns `None`. Raw `apply()` bypasses this check and keeps its prior behavior, including returning `[]` for a nonempty list whose length is not two.

The cost estimate is a static calculation, not a provider invoice or safety guarantee. Embedding filtering and optimization are opt-in and may load optional local dependencies; ordinary LLM matching does not use them. On the embedding path, the `embeddings_model` property selects the local model and defaults to `"paraphrase-MiniLM-L6-v2"`. Semantic join reuses its first successfully constructed embedding model on later calls.

Successful results have empty `output_attributes`; `meta.traces` may contain a nonnegative `elapsed_ms`. Raw `apply()` bypasses structured validation, so invalid group arity can raise instead of returning metadata. Validated `invoke()` runs the same input checks as `run()`, returns `None` when they reject the call, and exposes later execution exceptions; it returns data without `ExecMeta`.

For a structurally valid bundle, `run()` may also record `input_shape` before validation and
execution. The value has `groups` and `rows_per_group`; its counts do not change if the caller data
is later mutated. Invalid bundle structure omits this key.

After successful normalization, `output_shape` uses the same fields. Failures and timeouts omit it.
An all-empty successful output is normalized to `[[]]`, while a mixed multi-group output retains a
zero count for each empty group. Both shape keys are optional.

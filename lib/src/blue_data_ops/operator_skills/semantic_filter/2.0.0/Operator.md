# Semantic filter

`semantic_filter@2.0.0` evaluates natural-language conditions against each record through the configured LLM client.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `<service_prefix>.*` | `properties:<service_prefix>.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `context` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `demonstrations` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | `finite-positive-number` | `scalar` |
| `filter_conditions` | `attributes` | `yes` | `{}` | `attribute-spec:dict[str, str]` | `structured` |
| `input_context` | `properties` | `no` | `"$[0]"` | `none` | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | `none` | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | `none` | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | `none` | `scalar` |
| `input_template` | `properties` | `no` | `source-sha256:96e2380051831af1dfd8eeeebcc07773454f4c01b2498ac1b19b385518736a05` | `none` | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `llm_client` | `properties` | `no` | `none` | `helper:resolve_llm_client` | `seam` |
| `openai.api` | `properties` | `no` | `"ChatCompletion"` | `none` | `scalar` |
| `openai.max_tokens` | `properties` | `no` | `1024` | `none` | `scalar` |
| `openai.model` | `properties` | `no` | `"gpt-4o"` | `none` | `scalar` |
| `openai.stream` | `properties` | `no` | `false` | `none` | `scalar` |
| `openai.temperature` | `properties` | `no` | `0` | `none` | `scalar` |
| `output_cast` | `properties` | `no` | `"bool"` | `none` | `scalar` |
| `output_path` | `properties` | `no` | `"$.choices[0].message.content"` | `none` | `scalar` |
| `output_strip` | `properties` | `no` | `true` | `helper:resolve_llm_client; presence only: any value enables stripping` | `presence` |
| `output_template` | `properties` | `no` | `none` | `helper:resolve_llm_client` | `scalar` |
| `output_transformations` | `properties` | `no` | `source-sha256:4c5590a88361773f2b559375ccaed622ddaab9adeb52b16482d5b2ea9d10255b` | `none` | `structured` |
| `return_idx` | `attributes` | `yes` | `false` | `attribute-spec:boolean` | `scalar` |
| `service_prefix` | `properties` | `no` | `"openai"` | `none` | `scalar` |

## Filtering behavior

The operator makes one client call per record. Each request contains the full record, a numbered rendering of every condition, `context`, and `demonstrations`. Provider strings `true`, `yes`, `1`, and `include`, ignoring case and surrounding space, count as a match; other strings do not. Non-Boolean results use Python truthiness.

By default, matching input records are returned by identity. A truthy `return_idx` instead returns one new `{"indices": [...]}` record per input group. A valid request with empty input returns a successful empty result without a client call. Missing or empty conditions fail validation at `run()` and `invoke()`; raw `apply()` returns `[]` before validation.

`run()` contains LLM dependency, provider, templating, and parsing failures. Raw calls expose them after retries. The current `output_attributes` mapping is empty, and the operator has no registry or data-store side effect.

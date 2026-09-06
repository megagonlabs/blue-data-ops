# Semantic transform

`semantic_transform@2.0.0` asks the configured LLM client for a field-level transformation plan, then executes that plan over each input group.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `<service_prefix>.*` | `properties:<service_prefix>.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | `finite-positive-number` | `scalar` |
| `input_context` | `properties` | `no` | `"$[0]"` | `none` | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | `none` | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | `none` | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | `none` | `scalar` |
| `input_meta` | `attributes` | `yes` | `{}` | `attribute-spec:dict` | `structured` |
| `input_template` | `properties` | `no` | `source-sha256:2644c0c4ea34e99fe97194d89dda0b5de99aa67c75ca6090869b2b1a53691839` | `none` | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `llm_client` | `properties` | `no` | `none` | `helper:resolve_llm_client` | `seam` |
| `openai.api` | `properties` | `no` | `"ChatCompletion"` | `none` | `scalar` |
| `openai.max_tokens` | `properties` | `no` | `1024` | `none` | `scalar` |
| `openai.model` | `properties` | `no` | `"gpt-4o"` | `none` | `scalar` |
| `openai.stream` | `properties` | `no` | `false` | `none` | `scalar` |
| `openai.temperature` | `properties` | `no` | `0.0` | `none` | `scalar` |
| `output_cast` | `properties` | `no` | `"json"` | `none` | `scalar` |
| `output_desc` | `attributes` | `yes` | `{}` | `attribute-spec:dict` | `structured` |
| `output_path` | `properties` | `no` | `"$.choices[0].message.content"` | `none` | `scalar` |
| `output_strip` | `properties` | `no` | `true` | `helper:resolve_llm_client; presence only: any value enables stripping` | `presence` |
| `output_template` | `properties` | `no` | `none` | `helper:resolve_llm_client` | `scalar` |
| `output_transformations` | `properties` | `no` | `source-sha256:4c5590a88361773f2b559375ccaed622ddaab9adeb52b16482d5b2ea9d10255b` | `none` | `structured` |
| `service_prefix` | `properties` | `no` | `"openai"` | `none` | `scalar` |
| `strategy` | `attributes` | `yes` | `"auto"` | `attribute-spec:str` | `scalar` |

## Planning and execution

The planning request includes the input schema or `input_meta`, the requested output descriptions, and up to five sample records. It classifies each target as a direct field mapping or a value-changing transformation. `auto` chooses among simple rename, per-record calls, distinct-value calls, and a merged distinct-value path. The other strategy names force the corresponding path.

Simple mappings copy selected values into new output records and preserve nested value identity. Complex mappings can send source values, field descriptions, and individual records to the provider. Every nonempty group begins with a planning call. The implementation also prints the selected plan and strategy to standard output.

The planning result is merged into a shallow copy of `output_desc`. Its nested field mappings are shared, so plan keys such as `source_fields` and `transformation_type` are written into the caller's nested dictionaries. Copy the nested mappings before the call when that mutation is not wanted.

Empty outer input, an empty first group, or an empty output description returns raw `[]` without a client. `run()` contains validation, LLM dependency, provider, templating, and parsing failures; raw calls expose them after retries. The current `output_attributes` mapping is empty.

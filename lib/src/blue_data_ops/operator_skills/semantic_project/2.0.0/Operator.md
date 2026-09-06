# Semantic projection

`semantic_project@2.0.0` asks the configured LLM client which fields to keep and how to rename them, then applies that mapping to each input group.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `<service_prefix>.*` | `properties:<service_prefix>.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | `finite-positive-number` | `scalar` |
| `input_context` | `properties` | `no` | `"$[0]"` | `none` | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | `none` | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | `none` | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | `none` | `scalar` |
| `input_template` | `properties` | `no` | `source-sha256:81e0ed9ee4d7dea90e9f1e189cf3424db8a62527c21831062d6658f5148ad7b1` | `none` | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `llm_client` | `properties` | `no` | `none` | `helper:resolve_llm_client` | `seam` |
| `openai.api` | `properties` | `no` | `"ChatCompletion"` | `none` | `scalar` |
| `openai.max_tokens` | `properties` | `no` | `1024` | `none` | `scalar` |
| `openai.model` | `properties` | `no` | `"gpt-4o"` | `none` | `scalar` |
| `openai.stream` | `properties` | `no` | `false` | `none` | `scalar` |
| `openai.temperature` | `properties` | `no` | `0` | `none` | `scalar` |
| `output_cast` | `properties` | `no` | `"json"` | `none` | `scalar` |
| `output_path` | `properties` | `no` | `"$.choices[0].message.content"` | `none` | `scalar` |
| `output_strip` | `properties` | `no` | `true` | `helper:resolve_llm_client; presence only: any value enables stripping` | `presence` |
| `output_template` | `properties` | `no` | `none` | `helper:resolve_llm_client` | `scalar` |
| `output_transformations` | `properties` | `no` | `source-sha256:4c5590a88361773f2b559375ccaed622ddaab9adeb52b16482d5b2ea9d10255b` | `none` | `structured` |
| `projection_instructions` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `service_prefix` | `properties` | `no` | `"openai"` | `none` | `scalar` |

## Projection behavior

Each nonempty group produces a typed union of the fields found in its records. The schema and `projection_instructions` leave the process when a real provider is used. The response must be a nonempty mapping from input names to output names. A non-mapping or empty mapping returns an empty group. Missing input fields are omitted, and when two selected fields map to the same output name, the later mapping entry wins.

Output records are new dictionaries. Selected nested values retain their identity. Empty outer input, an empty first group, or blank instructions returns raw `[]` without resolving a client. Later empty groups remain empty. `run()` contains provider and parsing failures; raw calls expose them after retries. The current `output_attributes` mapping is empty.

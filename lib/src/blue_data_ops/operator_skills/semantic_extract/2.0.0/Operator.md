# Semantic extraction

`semantic_extract@2.0.0` extracts named entities from record fields through the configured LLM client.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `<service_prefix>.*` | `properties:<service_prefix>.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `context` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `demonstrations` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `entities` | `attributes` | `yes` | `[]` | `attribute-spec:list[dict]` | `structured` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | `finite-positive-number` | `scalar` |
| `extract_with_single_prompt` | `attributes` | `yes` | `true` | `attribute-spec:bool` | `scalar` |
| `input_context` | `properties` | `no` | `"$[0]"` | `none` | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | `none` | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | `none` | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | `none` | `scalar` |
| `input_template` | `properties` | `no` | `source-sha256:65eb83452525e28c33655748b65cd67400eaa80a3138a37be63a1749df690863` | `none` | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `llm_client` | `properties` | `no` | `none` | `helper:resolve_llm_client` | `seam` |
| `openai.api` | `properties` | `no` | `"ChatCompletion"` | `none` | `scalar` |
| `openai.max_tokens` | `properties` | `no` | `4096` | `none` | `scalar` |
| `openai.model` | `properties` | `no` | `"gpt-4o"` | `none` | `scalar` |
| `openai.stream` | `properties` | `no` | `false` | `none` | `scalar` |
| `openai.temperature` | `properties` | `no` | `0` | `none` | `scalar` |
| `output_cast` | `properties` | `no` | `"json"` | `none` | `scalar` |
| `output_path` | `properties` | `no` | `"$.choices[0].message.content"` | `none` | `scalar` |
| `output_strip` | `properties` | `no` | `true` | `helper:resolve_llm_client; presence only: any value enables stripping` | `presence` |
| `output_template` | `properties` | `no` | `none` | `helper:resolve_llm_client` | `scalar` |
| `output_transformations` | `properties` | `no` | `source-sha256:4c5590a88361773f2b559375ccaed622ddaab9adeb52b16482d5b2ea9d10255b` | `none` | `structured` |
| `service_prefix` | `properties` | `no` | `"openai"` | `none` | `scalar` |

## Extraction modes

Single-prompt mode makes one call per record. It sends the selected record fields, every entity description, `context`, and `demonstrations`. A non-mapping response becomes an output record with an empty list for every entity.

Individual mode makes at most one call per entity and record. It sends only nonempty selected fields and skips the call when none are available. List responses remain lists; other truthy responses are wrapped in a list. Each output record is newly constructed.

Empty outer input, an empty first group, or an empty entity list returns raw `[]` without client resolution. Later empty groups remain empty. `run()` contains validation, LLM dependency, provider, templating, and parsing failures. Raw calls expose execution failures after retries. The current `output_attributes` mapping is empty, and no input record is mutated.

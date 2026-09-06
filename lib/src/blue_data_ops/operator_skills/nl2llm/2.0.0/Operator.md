# Natural-language generation

`nl2llm@2.0.0` sends a natural-language request to the configured LLM client and returns its parsed structured response.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `<service_prefix>.*` | `properties:<service_prefix>.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `attrs` | `attributes` | `yes` | `[]` | `attribute-spec:list[dict]` | `structured` |
| `context` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | `finite-positive-number` | `scalar` |
| `input_context` | `properties` | `no` | `"$[0]"` | `none` | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | `none` | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | `none` | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | `none` | `scalar` |
| `input_template` | `properties` | `no` | `source-sha256:2b6d3c9bbf1494dca65079a906fbabd2f7856155734751f0703552fbcffff94c` | `none` | `scalar` |
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
| `query` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `service_prefix` | `properties` | `no` | `"openai"` | `none` | `scalar` |

## Request and result

The request sends `query`, `context`, and a formatted description of `attrs`. Each attribute description includes its name and optional type. A blank query returns raw `[]` before client resolution. Otherwise the parsed client value is wrapped as one output group. The default cleanup removes Markdown fences and every literal lowercase `json` substring before JSON conversion, including occurrences inside keys and values.

`run()` contains validation, dependency, templating, parsing, and provider failures in `ExecMeta`; the raw paths expose them after the client's retry policy. Missing LLM-extra modules receive the LLM dependency suggestion. The current `output_attributes` mapping is empty.

The operator does not mutate input records. It may contact the selected provider and, when enabled through `llm.*`, use a disk cache or apply process-local concurrency and rate controls.

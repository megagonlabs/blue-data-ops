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
| `input_context` | `properties` | `no` | `"$[0]"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_template` | `properties` | `no` | `source-sha256:96e2380051831af1dfd8eeeebcc07773454f4c01b2498ac1b19b385518736a05` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `llm_client` | `properties` | `no` | `none` | `helper:resolve_llm_client` | `seam` |
| `openai.api` | `properties` | `no` | `"ChatCompletion"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `openai.max_tokens` | `properties` | `no` | `1024` | `none` | `scalar` |
| `openai.model` | `properties` | `no` | `"gpt-6-luna"` | `none` | `scalar` |
| `openai.service_url` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `openai.stream` | `properties` | `no` | `false` | `none` | `scalar` |
| `openai.temperature` | `properties` | `no` | `0` | `none` | `scalar` |
| `output_cast` | `properties` | `no` | `"bool"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_path` | `properties` | `no` | `"$.choices[0].message.content"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_strip` | `properties` | `no` | `true` | reserved; Reserved in caller properties; configure trusted operator defaults. | `presence` |
| `output_template` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_transformations` | `properties` | `no` | `source-sha256:c6aba812d55427f013ea4096192a330a9984bff294ea41b48982ba0894185b21` | reserved; Reserved in caller properties; configure trusted operator defaults. | `structured` |
| `return_idx` | `attributes` | `yes` | `false` | `attribute-spec:boolean` | `scalar` |
| `service_prefix` | `properties` | `no` | `"openai"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `template_syntax` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |

## Filtering behavior

The operator makes one client call per record. Each request contains the full record, a numbered rendering of every condition, `context`, and `demonstrations`. The reply must be a boolean or a recognized string, ignoring case and surrounding space: `true`, `yes`, `1` and `include` include the record; `false`, `no`, `0` and `exclude` exclude it. Other values fail as malformed replies; see Response handling.

By default, matching input records are returned by identity. A truthy `return_idx` instead returns one new `{"indices": [...]}` record per input group. A valid request with empty input returns a successful empty result without a client call. Missing or empty conditions fail validation at `run()` and `invoke()`; raw `apply()` returns `[]` before validation.

`run()` contains LLM dependency, provider, templating, and parsing failures. Raw calls expose them after retries. The current `output_attributes` mapping is empty, and the operator has no registry or data-store side effect.

Caller prompt, extraction, and transport controls are reserved, including null or
copied defaults. Dollar placeholders are substituted once; inserted data and Jinja
syntax stay literal. Define custom prompts in trusted operator defaults. Injected
clients retain generation settings, while operator prompt/extraction defaults win.

### Response handling

Accept booleans and the strings listed above. Numeric values, punctuated strings such as `Yes.`, empty text and unrecognized replies are rejected. A false decision remains a successful exclusion. Malformed replies fail through `run()` with `exec_meta.errors`; raw `apply()`/`invoke()` raise.

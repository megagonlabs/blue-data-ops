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
| `input_context` | `properties` | `no` | `"$[0]"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_template` | `properties` | `no` | `source-sha256:65eb83452525e28c33655748b65cd67400eaa80a3138a37be63a1749df690863` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `llm_client` | `properties` | `no` | `none` | `helper:resolve_llm_client` | `seam` |
| `openai.api` | `properties` | `no` | `"ChatCompletion"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `openai.max_tokens` | `properties` | `no` | `4096` | `none` | `scalar` |
| `openai.model` | `properties` | `no` | `"gpt-6-luna"` | `none` | `scalar` |
| `openai.service_url` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `openai.stream` | `properties` | `no` | `false` | `none` | `scalar` |
| `openai.temperature` | `properties` | `no` | `0` | `none` | `scalar` |
| `output_cast` | `properties` | `no` | `"json"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_path` | `properties` | `no` | `"$.choices[0].message.content"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_strip` | `properties` | `no` | `true` | reserved; Reserved in caller properties; configure trusted operator defaults. | `presence` |
| `output_template` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_transformations` | `properties` | `no` | `source-sha256:c6aba812d55427f013ea4096192a330a9984bff294ea41b48982ba0894185b21` | reserved; Reserved in caller properties; configure trusted operator defaults. | `structured` |
| `service_prefix` | `properties` | `no` | `"openai"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `template_syntax` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |

## Extraction modes

Single-prompt mode makes one call per record. It sends the selected record fields, every entity description, `context`, and `demonstrations`. The reply must contain exactly the requested entity names, each with a list value. Malformed replies fail instead of becoming empty entities.

Individual mode makes at most one call per entity and record. It sends only nonempty selected fields and skips the call when none are available. Each reply must be a list of strings; an empty list is valid. Other values fail instead of being wrapped in a list. Each output record is newly constructed.

Empty outer input, an empty first group, or an empty entity list returns raw `[]` without client resolution. Later empty groups remain empty. `run()` contains validation, LLM dependency, provider, templating, and parsing failures. Raw calls expose execution failures after retries. The current `output_attributes` mapping is empty, and no input record is mutated.

Caller prompt, extraction, and transport controls are reserved, including null or
copied defaults. Dollar placeholders are substituted once; inserted data and Jinja
syntax stay literal. Define custom prompts in trusted operator defaults. Injected
clients retain generation settings, while operator prompt/extraction defaults win.

### Strict response handling

Combined replies must contain exactly the requested entity names, with list values; list elements retain their existing types. Individual replies must be string lists. Empty lists remain valid. Malformed replies fail through `run()` with `exec_meta.errors`; raw `apply()`/`invoke()` raise.

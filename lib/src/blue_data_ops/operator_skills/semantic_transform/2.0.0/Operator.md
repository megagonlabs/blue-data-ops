# Semantic transform

`semantic_transform@2.0.0` asks the configured LLM client for a field-level transformation plan, then executes that plan over each input group.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `<service_prefix>.*` | `properties:<service_prefix>.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | `finite-positive-number` | `scalar` |
| `input_context` | `properties` | `no` | `"$[0]"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_meta` | `attributes` | `yes` | `{}` | `attribute-spec:dict` | `structured` |
| `input_template` | `properties` | `no` | `source-sha256:9f1066125ab81b1debc18b8179ca03daed7abbae08d7f38a609dfd84550c0c22` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `llm_client` | `properties` | `no` | `none` | `helper:resolve_llm_client` | `seam` |
| `openai.api` | `properties` | `no` | `"ChatCompletion"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `openai.max_tokens` | `properties` | `no` | `1024` | `none` | `scalar` |
| `openai.model` | `properties` | `no` | `"gpt-6-luna"` | `none` | `scalar` |
| `openai.service_url` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `openai.stream` | `properties` | `no` | `false` | `none` | `scalar` |
| `openai.temperature` | `properties` | `no` | `0.0` | `none` | `scalar` |
| `output_cast` | `properties` | `no` | `"json"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_desc` | `attributes` | `yes` | `{}` | `attribute-spec:dict` | `structured` |
| `output_path` | `properties` | `no` | `"$.choices[0].message.content"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_strip` | `properties` | `no` | `true` | reserved; Reserved in caller properties; configure trusted operator defaults. | `presence` |
| `output_template` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_transformations` | `properties` | `no` | `source-sha256:c6aba812d55427f013ea4096192a330a9984bff294ea41b48982ba0894185b21` | reserved; Reserved in caller properties; configure trusted operator defaults. | `structured` |
| `service_prefix` | `properties` | `no` | `"openai"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `strategy` | `attributes` | `yes` | `"auto"` | `attribute-spec:str` | `scalar` |
| `template_syntax` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |

## Planning and execution

The planning request includes the input schema or `input_meta`, the requested output descriptions, and up to five sample records. It classifies each target as a direct field mapping or a value-changing transformation. `auto` chooses among simple rename, per-record calls, distinct-value calls, and a merged distinct-value path. The other strategy names force the corresponding path.

Simple mappings copy selected values into new output records and preserve nested value identity. Complex mappings can send source values, field descriptions, and individual records to the provider. Every nonempty group begins with a planning call. The implementation also prints the selected plan and strategy to standard output.

The planning result is merged into a shallow copy of `output_desc`. Its nested field mappings are shared, so plan keys such as `source_fields` and `transformation_type` are written into the caller's nested dictionaries. Copy the nested mappings before the call when that mutation is not wanted.

Empty outer input, an empty first group, or an empty output description returns raw `[]` without a client. `run()` contains validation, LLM dependency, provider, templating, and parsing failures; raw calls expose them after retries. The current `output_attributes` mapping is empty.

Caller prompt, extraction, and transport controls are reserved, including null or
copied defaults. Dollar placeholders are substituted once; inserted data and Jinja
syntax stay literal. Define custom prompts in trusted operator defaults. Injected
clients retain generation settings, while operator prompt/extraction defaults win.

### Strict response handling

Plans must include every requested target, string-list `source_fields`, and a known `transformation_type`. Missing classifications and invalid extra plan values are rejected. Extra valid plan keys are allowed. Generated objects must include fields marked `required is True` only when requested in that call. Optional omissions and explicit nulls remain valid. Malformed replies fail through `run()` with `exec_meta.errors`; raw `apply()`/`invoke()` raise.

# Semantic extraction

`semantic_extract@3.0.0` extracts named entities from record fields through the configured LLM client. It processes every supplied group, including a nonempty group after an empty one.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `<service_prefix>.*` | `properties:<service_prefix>.*` | `no` | `none` | helper:resolve_llm_client; Adapter and provider settings passed through client resolution. | `namespace` |
| `context` | `attributes` | `yes` | `""` | attribute-spec:str; optional; Domain context sent with each extraction request. | `scalar` |
| `demonstrations` | `attributes` | `yes` | `""` | attribute-spec:str; optional; In-context examples sent with each request. | `scalar` |
| `entities` | `attributes` | `yes` | `[]` | attribute-spec:list[dict]; required; Entity specifications. Each item names the entity and may include `description`, `extract_on_fields`, and `type`. | `structured` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Optional finite, positive timeout for `run()`. | `scalar` |
| `extract_with_single_prompt` | `attributes` | `yes` | `true` | attribute-spec:bool; optional; Extract all named entities together when true; use one request per entity when false. | `scalar` |
| `input_context` | `properties` | `no` | `"$[0]"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_template` | `properties` | `no` | `source-sha256:65eb83452525e28c33655748b65cd67400eaa80a3138a37be63a1749df690863` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | helper:resolve_llm_client; Adapter and provider settings passed through client resolution. | `namespace` |
| `llm_client` | `properties` | `no` | `none` | helper:resolve_llm_client; Injects an LLM client. Otherwise the client is resolved from the configured service. | `seam` |
| `openai.api` | `properties` | `no` | `"ChatCompletion"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `openai.max_tokens` | `properties` | `no` | `4096` | none; Provider setting used during client resolution. | `scalar` |
| `openai.model` | `properties` | `no` | `"gpt-6-luna"` | none; Default model under the default service prefix. | `scalar` |
| `openai.service_url` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `openai.stream` | `properties` | `no` | `false` | none; Provider setting used during client resolution. | `scalar` |
| `openai.temperature` | `properties` | `no` | `0` | none; Provider setting used during client resolution. | `scalar` |
| `output_cast` | `properties` | `no` | `"json"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_path` | `properties` | `no` | `"$.choices[0].message.content"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_strip` | `properties` | `no` | `true` | reserved; Reserved in caller properties; configure trusted operator defaults. | `presence` |
| `output_template` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_transformations` | `properties` | `no` | `source-sha256:c6aba812d55427f013ea4096192a330a9984bff294ea41b48982ba0894185b21` | reserved; Reserved in caller properties; configure trusted operator defaults. | `structured` |
| `service_prefix` | `properties` | `no` | `"openai"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `template_syntax` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |

## Result and calls

Single-prompt mode makes one provider call per record and requires an object whose keys exactly match the requested entity names; every value must be a list. Individual mode makes at most one call per entity and record, skips an entity unless at least one selected field is present with a truthy value, and requires each response to be a string array. A valid empty entity list inside a response remains data.

Empty groups keep their positions when another group contains records. If the whole bundle is empty or every group is empty, the result is a successful empty bundle without client resolution. An empty or malformed `entities` value is `INVALID_INPUT` at `VALIDATE`. Any malformed response fails the whole `run()` call with `EXECUTION_FAILED` at `EXECUTE`; partial output is not returned.

Successful results have empty `output_attributes`. `meta.is_empty` distinguishes a normalized empty result, and `meta.traces` may contain a nonnegative `elapsed_ms`. Raw `apply()` returns data directly and does not provide structured validation or error metadata. Validated `invoke()` runs the operator's input checks first, returns `None` on rejection, and exposes later execution exceptions; it also returns data without `ExecMeta`.

For a structurally valid bundle, `run()` may also record `input_shape` before validation and
execution. The value has `groups` and `rows_per_group`; its counts do not change if the caller data
is later mutated. Invalid bundle structure omits this key.

After successful normalization, `output_shape` uses the same fields. Failures and timeouts omit it.
An all-empty successful output is normalized to `[[]]`, while a mixed multi-group output retains a
zero count for each empty group. Both shape keys are optional.

Caller prompt, extraction, and transport controls are reserved, including null or
copied defaults. Dollar placeholders are substituted once; inserted data and Jinja
syntax stay literal. Define custom prompts in trusted operator defaults. Injected
clients retain generation settings, while operator prompt/extraction defaults win.

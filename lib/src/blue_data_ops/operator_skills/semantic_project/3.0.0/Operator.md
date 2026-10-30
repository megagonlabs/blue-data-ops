# Semantic projection

`semantic_project@3.0.0` asks the configured LLM client to select and rename fields. It resolves a separate mapping for every nonempty input group.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `<service_prefix>.*` | `properties:<service_prefix>.*` | `no` | `none` | helper:resolve_llm_client; Adapter and provider settings passed through client resolution. | `namespace` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Optional finite, positive timeout for `run()`. | `scalar` |
| `input_context` | `properties` | `no` | `"$[0]"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_template` | `properties` | `no` | `source-sha256:81e0ed9ee4d7dea90e9f1e189cf3424db8a62527c21831062d6658f5148ad7b1` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | helper:resolve_llm_client; Adapter and provider settings passed through client resolution. | `namespace` |
| `llm_client` | `properties` | `no` | `none` | helper:resolve_llm_client; Injects an LLM client. Otherwise the client is resolved from the configured service. | `seam` |
| `openai.api` | `properties` | `no` | `"ChatCompletion"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `openai.max_tokens` | `properties` | `no` | `1024` | none; Provider setting used during client resolution. | `scalar` |
| `openai.model` | `properties` | `no` | `"gpt-6-luna"` | none; Default model under the default service prefix. | `scalar` |
| `openai.service_url` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `openai.stream` | `properties` | `no` | `false` | none; Provider setting used during client resolution. | `scalar` |
| `openai.temperature` | `properties` | `no` | `0` | none; Provider setting used during client resolution. | `scalar` |
| `output_cast` | `properties` | `no` | `"json"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_path` | `properties` | `no` | `"$.choices[0].message.content"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_strip` | `properties` | `no` | `true` | reserved; Reserved in caller properties; configure trusted operator defaults. | `presence` |
| `output_template` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_transformations` | `properties` | `no` | `source-sha256:c6aba812d55427f013ea4096192a330a9984bff294ea41b48982ba0894185b21` | reserved; Reserved in caller properties; configure trusted operator defaults. | `structured` |
| `projection_instructions` | `attributes` | `yes` | `""` | attribute-spec:str; required; Nonblank natural-language instructions describing fields to keep and names to use. | `scalar` |
| `service_prefix` | `properties` | `no` | `"openai"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `template_syntax` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |

## Result and calls

Each nonempty group produces one provider call containing that group's inferred field schema and the projection instructions. The response must be an object mapping existing input field names to nonblank, unique output names. Records are newly constructed from that mapping; a source field absent from a particular record is skipped.

An explicit empty mapping is a valid drop-all answer and produces a successful empty group. Empty groups keep their positions when another group is nonempty. If the outer bundle is empty or every group is empty, no provider is resolved and the result is successfully empty. Blank or non-string instructions are `INVALID_INPUT` at `VALIDATE`. A non-object response, unknown source field, blank target name, or duplicate target name fails the whole call with `EXECUTION_FAILED` at `EXECUTE`.

Successful results have empty `output_attributes`; `meta.traces` may contain a nonnegative `elapsed_ms`. Raw `apply()` returns data directly and exposes execution failures. Validated `invoke()` runs the same input checks first, returns `None` on rejection, and exposes later execution exceptions; it returns data without `ExecMeta`.

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

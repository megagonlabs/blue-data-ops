# Natural language to Bayesian-network query

`nl2bn@2.0.0` translates a question into a Bayesian-network query, validates it against an optional structured schema, executes it through the registry, and returns the probability.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `<service_prefix>.*` | `properties:<service_prefix>.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `collection` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `context` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `data_registry` | `properties` | `no` | `none` | `helper:resolve_registry` | `seam` |
| `data_registry.name` | `properties` | `no` | `none` | `helper:resolve_registry` | `seam` |
| `database` | `attributes` | `yes` | `"default"` | `attribute-spec:str` | `scalar` |
| `execute_query` | `properties` | `no` | `true` | `none` | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | `finite-positive-number` | `scalar` |
| `explanation` | `attributes` | `yes` | `true` | `attribute-spec:bool` | `scalar` |
| `input_context` | `properties` | `no` | `"$[0]"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_template` | `properties` | `no` | `source-sha256:87420873e763ac26481f76dacdb9910314e3f55a1c7d96b3a28781472e68b485` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `llm_client` | `properties` | `no` | `none` | `helper:resolve_llm_client` | `seam` |
| `max_corrections` | `attributes` | `yes` | `2` | `attribute-spec:int` | `scalar` |
| `max_num_paths` | `attributes` | `yes` | `50` | `attribute-spec:int` | `scalar` |
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
| `platform.name` | `properties` | `no` | `none` | `helper:resolve_registry` | `seam` |
| `protocol_variant` | `attributes` | `yes` | `"pgmpy"` | `attribute-spec:str` | `scalar` |
| `question` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `schema` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `service_prefix` | `properties` | `no` | `"openai"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `source` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `structured_explanation` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `template_syntax` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |

## Query, correction, and execution

With no supplied schema, the operator fetches one from the registry. A string containing `nodes` and `edges`, or a raw mapping passed to `apply()`, enables node, state, and evidence validation. Unstructured schema content still reaches the generation prompt but does not receive graph validation.

The first provider request includes the question, context, and schema section. A malformed or invalid query can trigger up to `max_corrections` additional calls. Every correction request includes the original query, validation errors, and the same schema section again. Owners must account for that repeated disclosure when the schema is sensitive.

A valid query is executed through the registry. The output is one record containing `prob`, the parsed `query`, and an explanation when requested and returned. An empty registry result gives `prob=None`, not a successful-empty bundle. A blank question returns `[[]]` before registry or provider work. Compatibility `apply()` also returns `[[]]` when no registry resolves.

`run()` contains validation, LLM dependency, provider, parsing, graph-validation, and registry failures. Raw correction-call failures and exhausted corrections remain exceptions. The current `output_attributes` mapping is empty.

Caller prompt, extraction, and transport controls are reserved, including null or
copied defaults. Dollar placeholders are substituted once; inserted data and Jinja
syntax stay literal. Define custom prompts in trusted operator defaults. Injected
clients retain generation settings, while operator prompt/extraction defaults win.

Bayesian inference still runs; the legacy `execute_query` property is ignored and is not an SQL safety switch.

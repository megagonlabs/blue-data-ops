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
| `input_context` | `properties` | `no` | `"$[0]"` | `none` | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | `none` | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | `none` | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | `none` | `scalar` |
| `input_template` | `properties` | `no` | `source-sha256:87420873e763ac26481f76dacdb9910314e3f55a1c7d96b3a28781472e68b485` | `none` | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `llm_client` | `properties` | `no` | `none` | `helper:resolve_llm_client` | `seam` |
| `max_corrections` | `attributes` | `yes` | `2` | `attribute-spec:int` | `scalar` |
| `max_num_paths` | `attributes` | `yes` | `50` | `attribute-spec:int` | `scalar` |
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
| `platform.name` | `properties` | `no` | `none` | `helper:resolve_registry` | `seam` |
| `protocol_variant` | `attributes` | `yes` | `"pgmpy"` | `attribute-spec:str` | `scalar` |
| `question` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `schema` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `service_prefix` | `properties` | `no` | `"openai"` | `none` | `scalar` |
| `source` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `structured_explanation` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |

## Query, correction, and execution

With no supplied schema, the operator fetches one from the registry. A string containing `nodes` and `edges`, or a raw mapping passed to `apply()`, enables node, state, and evidence validation. Unstructured schema content still reaches the generation prompt but does not receive graph validation.

The first provider request includes the question, context, and schema section. A malformed or invalid query can trigger up to `max_corrections` additional calls. Every correction request includes the original query, validation errors, and the same schema section again. Owners must account for that repeated disclosure when the schema is sensitive.

A valid query is executed through the registry. The output is one record containing `prob`, the parsed `query`, and an explanation when requested and returned. An empty registry result gives `prob=None`, not a successful-empty bundle. A blank question returns `[[]]` before registry or provider work. Compatibility `apply()` also returns `[[]]` when no registry resolves.

`run()` contains validation, LLM dependency, provider, parsing, graph-validation, and registry failures. Raw correction-call failures and exhausted corrections remain exceptions. The current `output_attributes` mapping is empty.

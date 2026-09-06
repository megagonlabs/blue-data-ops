# Natural language to SQL

`nl2sql@2.0.0` translates a natural-language question into SQL and can execute the generated statement through the configured data registry.

The live `io.attributes` mapping lists the declared settings: `additional_requirements`, `attr_names`, `case_insensitive`, `collection`, `context`, `database`, `protocol`, `question`, `schema`, and `source`. The Settings table also records compatibility inputs read outside that mapping.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `<service_prefix>.*` | `properties:<service_prefix>.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `additional_requirements` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `attr_names` | `attributes` | `yes` | `[]` | `attribute-spec:list[str]` | `structured` |
| `case_insensitive` | `attributes` | `yes` | `true` | `attribute-spec:bool` | `scalar` |
| `collection` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `context` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `data_registry` | `properties` | `no` | `none` | `helper:resolve_registry` | `seam` |
| `data_registry.name` | `properties` | `no` | `none` | `helper:resolve_registry` | `seam` |
| `database` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `execute_query` | `properties` | `no` | `true` | `none` | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | `finite-positive-number` | `scalar` |
| `force_query_prefixes` | `attributes` | `no` | `"SELECT"` | `none` | `scalar` |
| `input_context` | `properties` | `no` | `"$[0]"` | `none` | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | `none` | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | `none` | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | `none` | `scalar` |
| `input_template` | `properties` | `no` | `source-sha256:26b282e53a7f7853d7fea2974ff5b6039742f9370d156894166a66e3ea0b01b9` | `none` | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `llm_client` | `properties` | `no` | `none` | `helper:resolve_llm_client` | `seam` |
| `openai.api` | `properties` | `no` | `"ChatCompletion"` | `none` | `scalar` |
| `openai.max_tokens` | `properties` | `no` | `512` | `none` | `scalar` |
| `openai.model` | `properties` | `no` | `"gpt-4o"` | `none` | `scalar` |
| `openai.stream` | `properties` | `no` | `false` | `none` | `scalar` |
| `openai.temperature` | `properties` | `no` | `0` | `none` | `scalar` |
| `output_cast` | `properties` | `no` | `"json"` | `none` | `scalar` |
| `output_path` | `properties` | `no` | `"$.choices[0].message.content"` | `none` | `scalar` |
| `output_strip` | `properties` | `no` | `true` | `helper:resolve_llm_client; presence only: any value enables stripping` | `presence` |
| `output_template` | `properties` | `no` | `none` | `helper:resolve_llm_client` | `scalar` |
| `output_transformations` | `properties` | `no` | `source-sha256:4c5590a88361773f2b559375ccaed622ddaab9adeb52b16482d5b2ea9d10255b` | `none` | `structured` |
| `platform.name` | `properties` | `no` | `none` | `helper:resolve_registry` | `seam` |
| `protocol` | `attributes` | `yes` | `"postgres"` | `attribute-spec:str` | `scalar` |
| `question` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `schema` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `service_prefix` | `properties` | `no` | `"openai"` | `none` | `scalar` |
| `source` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `validate_query_prefixes` | `properties` | `no` | `["SELECT"]` | `none` | `structured` |

## Data and safety boundaries

The operator always obtains the live schema from the registry; the declared `schema` attribute does not replace that lookup. It sends the question, schema, protocol, context, requested aliases, and additional requirements to the LLM client. The undeclared `force_query_prefixes` attribute changes that prompt only. The returned SQL is independently checked against `validate_query_prefixes`.

With `execute_query=true`, the registry result is normalized and returned. With execution disabled, the result is `[[{"sql": "..."}]]`. A blank question returns `[[]]` before registry or client resolution. Missing registry configuration makes compatibility `apply()` return `[[]]`. Invalid addressing, protocol, provider response, SQL prefix, or registry execution remains an error.

Use `run()` for contained validation and execution failures. Missing LLM-extra modules receive the dependency suggestion. The current `output_attributes` mapping is empty. Schema lookup and query execution are registry side effects; provider generation may use network access unless a client is injected.

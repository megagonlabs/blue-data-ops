# Natural language to SQL

`nl2sql@3.0.0` translates a natural-language question into SQL and returns SQL by default and can execute through a host-bound read-only executor.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `<service_prefix>.*` | `properties:<service_prefix>.*` | `no` | `none` | helper:resolve_llm_client; Adapter and provider settings passed through client resolution. | `namespace` |
| `additional_requirements` | `attributes` | `yes` | `""` | attribute-spec:str; optional; Additional SQL-generation instructions. | `scalar` |
| `attr_names` | `attributes` | `yes` | `[]` | attribute-spec:list[str]; optional; Requested output aliases included in the generation prompt. | `structured` |
| `case_insensitive` | `attributes` | `yes` | `true` | attribute-spec:bool; optional; Requests case-insensitive string matching in generated SQL. | `scalar` |
| `collection` | `attributes` | `yes` | `""` | attribute-spec:str; required; Nonblank collection or schema name. | `scalar` |
| `context` | `attributes` | `yes` | `""` | attribute-spec:str; optional; Domain context included in generation. | `scalar` |
| `data_registry` | `properties` | `no` | `none` | denied-for-execution; Registry selection is available for generation only; presence is denied for execution. | `seam` |
| `data_registry.name` | `properties` | `no` | `none` | denied-for-execution; Registry selection is available for generation only; presence is denied for execution. | `seam` |
| `database` | `attributes` | `yes` | `""` | attribute-spec:str; required; Nonblank database name. | `scalar` |
| `execute_query` | `properties` | `no` | `false` | boolean-host-capability; False generates SQL; true requires a host-bound read-only executor. | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Optional finite, positive timeout for `run()`. | `scalar` |
| `force_query_prefixes` | `attributes` | `no` | `"SELECT"` | none; undeclared compatibility input that changes the prefixes requested from the model | `scalar` |
| `input_context` | `properties` | `no` | `"$[0]"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_template` | `properties` | `no` | `source-sha256:26b282e53a7f7853d7fea2974ff5b6039742f9370d156894166a66e3ea0b01b9` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | helper:resolve_llm_client; Adapter and provider settings passed through client resolution. | `namespace` |
| `llm_client` | `properties` | `no` | `none` | helper:resolve_llm_client; Injects an LLM client. Otherwise the client is resolved from provider settings. | `seam` |
| `openai.api` | `properties` | `no` | `"ChatCompletion"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `openai.max_tokens` | `properties` | `no` | `512` | none; Provider setting used during client resolution. | `scalar` |
| `openai.model` | `properties` | `no` | `"gpt-6-luna"` | none; Default model under the default service prefix. | `scalar` |
| `openai.service_url` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `openai.stream` | `properties` | `no` | `false` | none; Provider setting used during client resolution. | `scalar` |
| `openai.temperature` | `properties` | `no` | `0` | none; Provider setting used during client resolution. | `scalar` |
| `output_cast` | `properties` | `no` | `"json"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_path` | `properties` | `no` | `"$.choices[0].message.content"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_strip` | `properties` | `no` | `true` | reserved; Reserved in caller properties; configure trusted operator defaults. | `presence` |
| `output_template` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_transformations` | `properties` | `no` | `source-sha256:c6aba812d55427f013ea4096192a330a9984bff294ea41b48982ba0894185b21` | reserved; Reserved in caller properties; configure trusted operator defaults. | `structured` |
| `platform.name` | `properties` | `no` | `none` | denied-for-execution; Registry selection is available for generation only; presence is denied for execution. | `seam` |
| `protocol` | `attributes` | `yes` | `"postgres"` | attribute-spec:str; required; `postgres`, `mysql`, or `sqlite`. | `scalar` |
| `question` | `attributes` | `yes` | `""` | attribute-spec:str; required; Nonblank question to translate. | `scalar` |
| `read_only_executor` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `presence` |
| `schema` | `attributes` | `yes` | `""` | attribute-spec:str; optional; Declared compatibility input; the operator still fetches registered column schema. | `scalar` |
| `service_prefix` | `properties` | `no` | `"openai"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `source` | `attributes` | `yes` | `""` | attribute-spec:str; required; Nonblank data-source name. | `scalar` |
| `template_syntax` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `validate_query_prefixes` | `properties` | `no` | `["SELECT"]` | ascii-select-list; Only a one-item ASCII SELECT list is accepted, ignoring case without trimming. | `structured` |

## Required addressing fields

The table combines declared defaults with execution fallbacks. For `question`, `""` is the body fallback rather than a declared default. Callers must still pass all five required fields explicitly; structured validation rejects a missing or blank value before registry or client resolution.

## Generation, execution, and errors

Generation is the default and returns `[[{"sql": "..."}]]`. Schema lookup uses the
configured registry; the `schema` attribute remains a compatibility input. Caller
controls and SQL policy are checked before schema, client, cache, or provider work,
even on a blank-question raw path. Structured addressing validation still applies.

Execution requires a constructor-bound `ReadOnlySQLExecutor`, an exact existing
target, and boolean `execute_query=True`. Caller registry selectors cannot grant
access; stock CLI/MCP instances have no executor. The guard supports the inspected
concrete SQLite, PostgreSQL, and MySQL source classes and calls them with
`commit=False`. Connections open before guard installation. SQLite path resolution
may create a directory, so use pre-existing approved targets. Read-only SELECT does
not constrain stored functions, privileged file/network access, or resource use;
use least-privilege principals. See the library SQL execution guide for the query
syntax boundary and host setup.

No rows is a successful empty result. Raw `apply()` returns `[[]]` for a blank
question or missing generation registry; policy errors raise typed `LLMError`.
Structured calls contain failures in the existing result schema. SQL policy and
execution failures use fixed diagnostics without SQL or driver text.

Successful `run()` results have empty `output_attributes`; `meta.traces` may contain a nonnegative `elapsed_ms`. Schema lookup and SQL execution are registry side effects, and an uninjected client may make provider calls.

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

Schema prompts use registered names and declared types, without row samples or
connection properties. Registered schema may be stale; lookup failures are errors.
The public executor accepts one SELECT and may refuse valid dialect syntax. Target
collections constrain routing, not the tables SQL can read.

# Natural language to SQL

`nl2sql@3.0.0` translates a natural-language question into SQL and can execute the generated statement through the configured data registry.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `<service_prefix>.*` | `properties:<service_prefix>.*` | `no` | `none` | helper:resolve_llm_client; Adapter and provider settings passed through client resolution. | `namespace` |
| `additional_requirements` | `attributes` | `yes` | `""` | attribute-spec:str; optional; Additional SQL-generation instructions. | `scalar` |
| `attr_names` | `attributes` | `yes` | `[]` | attribute-spec:list[str]; optional; Requested output aliases included in the generation prompt. | `structured` |
| `case_insensitive` | `attributes` | `yes` | `true` | attribute-spec:bool; optional; Requests case-insensitive string matching in generated SQL. | `scalar` |
| `collection` | `attributes` | `yes` | `""` | attribute-spec:str; required; Nonblank collection or schema name. | `scalar` |
| `context` | `attributes` | `yes` | `""` | attribute-spec:str; optional; Domain context included in generation. | `scalar` |
| `data_registry` | `properties` | `no` | `none` | helper:resolve_registry; Injects a registry seam. Otherwise `platform.name` and `data_registry.name` may resolve one. | `seam` |
| `data_registry.name` | `properties` | `no` | `none` | helper:resolve_registry; Selects a configured registry when no registry seam is injected. | `seam` |
| `database` | `attributes` | `yes` | `""` | attribute-spec:str; required; Nonblank database name. | `scalar` |
| `execute_query` | `properties` | `no` | `true` | none; Executes generated SQL through the registry; false returns `[[{"sql": "..."}]]`. | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Optional finite, positive timeout for `run()`. | `scalar` |
| `force_query_prefixes` | `attributes` | `no` | `"SELECT"` | none; undeclared compatibility input that changes the prefixes requested from the model | `scalar` |
| `input_context` | `properties` | `no` | `"$[0]"` | none; Controls request templating or response extraction. | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | none; Controls request templating or response extraction. | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | none; Controls request templating or response extraction. | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | none; Controls request templating or response extraction. | `scalar` |
| `input_template` | `properties` | `no` | `source-sha256:26b282e53a7f7853d7fea2974ff5b6039742f9370d156894166a66e3ea0b01b9` | none; Controls request templating or response extraction. | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | helper:resolve_llm_client; Adapter and provider settings passed through client resolution. | `namespace` |
| `llm_client` | `properties` | `no` | `none` | helper:resolve_llm_client; Injects an LLM client. Otherwise the client is resolved from provider settings. | `seam` |
| `openai.api` | `properties` | `no` | `"ChatCompletion"` | none; Provider setting used during client resolution. | `scalar` |
| `openai.max_tokens` | `properties` | `no` | `512` | none; Provider setting used during client resolution. | `scalar` |
| `openai.model` | `properties` | `no` | `"gpt-4o"` | none; Default model under the default service prefix. | `scalar` |
| `openai.stream` | `properties` | `no` | `false` | none; Provider setting used during client resolution. | `scalar` |
| `openai.temperature` | `properties` | `no` | `0` | none; Provider setting used during client resolution. | `scalar` |
| `output_cast` | `properties` | `no` | `"json"` | none; Controls request templating or response extraction. | `scalar` |
| `output_path` | `properties` | `no` | `"$.choices[0].message.content"` | none; Controls request templating or response extraction. | `scalar` |
| `output_strip` | `properties` | `no` | `true` | helper:resolve_llm_client; Controls request templating or response extraction. | `presence` |
| `output_template` | `properties` | `no` | `none` | helper:resolve_llm_client; Controls request templating or response extraction. | `scalar` |
| `output_transformations` | `properties` | `no` | `source-sha256:4c5590a88361773f2b559375ccaed622ddaab9adeb52b16482d5b2ea9d10255b` | none; Controls request templating or response extraction. | `structured` |
| `platform.name` | `properties` | `no` | `none` | helper:resolve_registry; Selects a configured registry when no registry seam is injected. | `seam` |
| `protocol` | `attributes` | `yes` | `"postgres"` | attribute-spec:str; required; `postgres`, `mysql`, or `sqlite`. | `scalar` |
| `question` | `attributes` | `yes` | `""` | attribute-spec:str; required; Nonblank question to translate. | `scalar` |
| `schema` | `attributes` | `yes` | `""` | attribute-spec:str; optional; Declared compatibility input; the operator still fetches the live schema from the registry. | `scalar` |
| `service_prefix` | `properties` | `no` | `"openai"` | none; Selects the provider-property namespace. | `scalar` |
| `source` | `attributes` | `yes` | `""` | attribute-spec:str; required; Nonblank data-source name. | `scalar` |
| `validate_query_prefixes` | `properties` | `no` | `["SELECT"]` | none; Accepts generated SQL only when it starts with one of these prefixes, ignoring case. | `structured` |

## Required addressing fields

The table combines declared defaults with execution fallbacks. For `question`, `""` is the body fallback rather than a declared default. Callers must still pass all five required fields explicitly; structured validation rejects a missing or blank value before registry or client resolution.

## Generation, execution, and errors

`run()` validates the five addressing fields and protocol before registry or client resolution. It always obtains the schema from the registry, then makes one provider call. The generation response must be an object whose `query` field holds the SQL string. The undeclared compatibility attribute `force_query_prefixes` changes the generation prompt; `validate_query_prefixes` performs the independent prefix check. That prefix check is not a SQL safety guarantee.

With execution enabled, native registry results are normalized into record groups. No rows is a successful empty result. If the formatter returns no bundle for a list of lists containing non-record items, `run()` reports `EXECUTION_RESULT_INVALID` at `NORMALIZE`; generation, prefix, registry-call, and formatter exceptions are `EXECUTION_FAILED` at `EXECUTE`. With execution disabled, the generated SQL record is returned without a registry execution call, though schema lookup still occurs.

Raw `apply()` bypasses structured validation: a blank question and a missing registry each return `[[]]`, while an unsupported protocol, rejected query prefix, or malformed generation response raises. Inherited `invoke()` checks the declared attribute schema, but it does not run this version's nonblank addressing or protocol validation. It returns `None` for a declared-schema rejection; otherwise it calls `apply()` and inherits those raw returns and exceptions. Neither entry point returns `ExecMeta`.

Successful `run()` results have empty `output_attributes`; `meta.traces` may contain a nonnegative `elapsed_ms`. Schema lookup and SQL execution are registry side effects, and an uninjected client may make provider calls.

For a structurally valid bundle, `run()` may also record `input_shape` before validation and
execution. The value has `groups` and `rows_per_group`; its counts do not change if the caller data
is later mutated. Invalid bundle structure omits this key.

After successful normalization, `output_shape` uses the same fields. Failures and timeouts omit it.
An all-empty successful output is normalized to `[[]]`, while a mixed multi-group output retains a
zero count for each empty group. Both shape keys are optional.

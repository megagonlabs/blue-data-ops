# Natural language to Bayesian-network query

`nl2bn@3.0.0` translates a question into a Bayesian-network query, validates it against an optional structured schema, executes it through the registry, and returns the probability.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `<service_prefix>.*` | `properties:<service_prefix>.*` | `no` | `none` | helper:resolve_llm_client; Adapter and provider settings passed through client resolution. | `namespace` |
| `collection` | `attributes` | `yes` | `""` | attribute-spec:str; required; Nonblank model or collection name. | `scalar` |
| `context` | `attributes` | `yes` | `""` | attribute-spec:str; optional; Domain context included in generation. | `scalar` |
| `data_registry` | `properties` | `no` | `none` | helper:resolve_registry; Injects a registry seam. Otherwise `platform.name` and `data_registry.name` may resolve one. | `seam` |
| `data_registry.name` | `properties` | `no` | `none` | helper:resolve_registry; Selects a configured registry when no registry seam is injected. | `seam` |
| `database` | `attributes` | `yes` | `"default"` | attribute-spec:str; required; Nonblank database name. | `scalar` |
| `execute_query` | `properties` | `no` | `true` | none; Retained compatibility property; this operator always executes a valid generated query. | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Optional finite, positive timeout for `run()`. | `scalar` |
| `explanation` | `attributes` | `yes` | `true` | attribute-spec:bool; optional; Requests an explanation from the query backend. | `scalar` |
| `input_context` | `properties` | `no` | `"$[0]"` | none; Controls request templating or response extraction. | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | none; Controls request templating or response extraction. | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | none; Controls request templating or response extraction. | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | none; Controls request templating or response extraction. | `scalar` |
| `input_template` | `properties` | `no` | `source-sha256:87420873e763ac26481f76dacdb9910314e3f55a1c7d96b3a28781472e68b485` | none; Controls request templating or response extraction. | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | helper:resolve_llm_client; Adapter and provider settings passed through client resolution. | `namespace` |
| `llm_client` | `properties` | `no` | `none` | helper:resolve_llm_client; Injects an LLM client. Otherwise the client is resolved from provider settings. | `seam` |
| `max_corrections` | `attributes` | `yes` | `2` | attribute-spec:int; optional; Maximum provider correction attempts after an invalid generated query. | `scalar` |
| `max_num_paths` | `attributes` | `yes` | `50` | attribute-spec:int; optional; Path limit forwarded when explanations are enabled. | `scalar` |
| `openai.api` | `properties` | `no` | `"ChatCompletion"` | none; Provider setting used during client resolution. | `scalar` |
| `openai.max_tokens` | `properties` | `no` | `4096` | none; Provider setting used during client resolution. | `scalar` |
| `openai.model` | `properties` | `no` | `"gpt-4o"` | none; Default model under the default service prefix. | `scalar` |
| `openai.stream` | `properties` | `no` | `false` | none; Provider setting used during client resolution. | `scalar` |
| `openai.temperature` | `properties` | `no` | `0` | none; Provider setting used during client resolution. | `scalar` |
| `output_cast` | `properties` | `no` | `"json"` | none; Controls request templating or response extraction. | `scalar` |
| `output_path` | `properties` | `no` | `"$.choices[0].message.content"` | none; Controls request templating or response extraction. | `scalar` |
| `output_strip` | `properties` | `no` | `true` | helper:resolve_llm_client; Controls request templating or response extraction. | `presence` |
| `output_template` | `properties` | `no` | `none` | helper:resolve_llm_client; Controls request templating or response extraction. | `scalar` |
| `output_transformations` | `properties` | `no` | `source-sha256:4c5590a88361773f2b559375ccaed622ddaab9adeb52b16482d5b2ea9d10255b` | none; Controls request templating or response extraction. | `structured` |
| `platform.name` | `properties` | `no` | `none` | helper:resolve_registry; Selects a configured registry when no registry seam is injected. | `seam` |
| `protocol_variant` | `attributes` | `yes` | `"pgmpy"` | attribute-spec:str; required; Must be `pgmpy`. | `scalar` |
| `question` | `attributes` | `yes` | `""` | attribute-spec:str; required; Nonblank question to translate. | `scalar` |
| `schema` | `attributes` | `yes` | `""` | attribute-spec:str; optional; Optional schema text or JSON graph with `nodes` and `edges`. Blank fetches the schema from the registry. | `scalar` |
| `service_prefix` | `properties` | `no` | `"openai"` | none; Selects the provider-property namespace. | `scalar` |
| `source` | `attributes` | `yes` | `""` | attribute-spec:str; required; Nonblank Bayesian-network source name. | `scalar` |
| `structured_explanation` | `attributes` | `yes` | `false` | attribute-spec:bool; optional; Requests structured explanation when explanations are enabled. | `scalar` |

## Required addressing fields

The table combines declared defaults with execution fallbacks. For `question`, `""` is the body fallback rather than a declared default. Callers must still pass all five required fields explicitly; structured validation rejects a missing or blank value before registry or client resolution.

## Query, correction, and result

`run()` validates the question, source, database, collection, and protocol before registry or client resolution. A structured graph schema enables node, state, and evidence validation. An invalid first response can make up to `max_corrections` more provider calls; correction requests include the original query, validation errors, and schema section.

The registry executes the validated query. The first normalized record must contain `probability` or `prob`; zero is a valid probability. A true no-row result is a successful empty bundle. An unformattable result or a record without either probability key fails with `EXECUTION_FAILED` at `EXECUTE`. This differs from `nl2sql@3.0.0`, whose unformattable native result is contained later at `NORMALIZE`.

Raw `apply()` bypasses structured validation: a blank question and a missing registry each return `[[]]`; other invalid addressing values can raise. Inherited `invoke()` checks the declared attribute schema, but it does not run this version's nonblank addressing or protocol validation. It returns `None` for a declared-schema rejection; otherwise it calls `apply()` and inherits those raw returns and exceptions. Neither entry point returns `ExecMeta`.

Successful `run()` results have empty `output_attributes`; `meta.traces` may contain a nonnegative `elapsed_ms`. Schema lookup and query execution are registry side effects, and an uninjected client may make provider calls.

For a structurally valid bundle, `run()` may also record `input_shape` before validation and
execution. The value has `groups` and `rows_per_group`; its counts do not change if the caller data
is later mutated. Invalid bundle structure omits this key.

After successful normalization, `output_shape` uses the same fields. Failures and timeouts omit it.
An all-empty successful output is normalized to `[[]]`, while a mixed multi-group output retains a
zero count for each empty group. Both shape keys are optional.

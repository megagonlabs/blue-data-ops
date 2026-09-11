# Semantic filtering

`semantic_filter@3.0.0` evaluates natural-language conditions through the configured LLM client. It processes every supplied group and accepts only booleans or the strings `true` and `false`, ignoring case and surrounding whitespace.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `<service_prefix>.*` | `properties:<service_prefix>.*` | `no` | `none` | helper:resolve_llm_client; Adapter and provider settings passed through client resolution. | `namespace` |
| `context` | `attributes` | `yes` | `""` | attribute-spec:str; optional; Domain context sent with each record. | `scalar` |
| `demonstrations` | `attributes` | `yes` | `""` | attribute-spec:str; optional; In-context examples sent with each record. | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Optional finite, positive timeout for `run()`. | `scalar` |
| `filter_conditions` | `attributes` | `yes` | `{}` | attribute-spec:dict[str, str]; required; Maps record fields to nonblank natural-language conditions. | `structured` |
| `input_context` | `properties` | `no` | `"$[0]"` | none; Controls request templating or response extraction. | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | none; Controls request templating or response extraction. | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | none; Controls request templating or response extraction. | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | none; Controls request templating or response extraction. | `scalar` |
| `input_template` | `properties` | `no` | `source-sha256:96e2380051831af1dfd8eeeebcc07773454f4c01b2498ac1b19b385518736a05` | none; Controls request templating or response extraction. | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | helper:resolve_llm_client; Adapter and provider settings passed through client resolution. | `namespace` |
| `llm_client` | `properties` | `no` | `none` | helper:resolve_llm_client; Injects an LLM client. Otherwise the client is resolved from the configured service. | `seam` |
| `openai.api` | `properties` | `no` | `"ChatCompletion"` | none; Provider setting used during client resolution. | `scalar` |
| `openai.max_tokens` | `properties` | `no` | `1024` | none; Provider setting used during client resolution. | `scalar` |
| `openai.model` | `properties` | `no` | `"gpt-4o"` | none; Default model under the default service prefix. | `scalar` |
| `openai.stream` | `properties` | `no` | `false` | none; Provider setting used during client resolution. | `scalar` |
| `openai.temperature` | `properties` | `no` | `0` | none; Provider setting used during client resolution. | `scalar` |
| `output_cast` | `properties` | `no` | `"bool"` | none; Controls request templating or response extraction. | `scalar` |
| `output_path` | `properties` | `no` | `"$.choices[0].message.content"` | none; Controls request templating or response extraction. | `scalar` |
| `output_strip` | `properties` | `no` | `true` | helper:resolve_llm_client; Controls request templating or response extraction. | `presence` |
| `output_template` | `properties` | `no` | `none` | helper:resolve_llm_client; Controls request templating or response extraction. | `scalar` |
| `output_transformations` | `properties` | `no` | `source-sha256:4c5590a88361773f2b559375ccaed622ddaab9adeb52b16482d5b2ea9d10255b` | none; Controls request templating or response extraction. | `structured` |
| `return_idx` | `attributes` | `yes` | `false` | attribute-spec:boolean; optional; Return one `{"indices": [...]}` record per group instead of selected records. This version requires an actual Python `bool`. | `scalar` |
| `service_prefix` | `properties` | `no` | `"openai"` | none; Selects the provider-property namespace. | `scalar` |

## Result and calls

The operator makes one provider call per input record. Record mode returns the records whose responses are true. Index mode returns one record per supplied group, with zero-based indices into that group. An empty group therefore becomes `[]` in record mode or `[{"indices": []}]` in index mode.

When every group is empty, record mode normalizes to a successful empty bundle, while index mode still emits one indices record per group. An empty outer bundle is also a successful empty result without client resolution. Empty or malformed `filter_conditions`, or a non-Boolean `return_idx`, is `INVALID_INPUT` at `VALIDATE`. A malformed provider response fails the whole call with `EXECUTION_FAILED` at `EXECUTE`.

Successful results have empty `output_attributes`; `meta.traces` may contain a nonnegative `elapsed_ms`. Raw `apply()` returns data directly and exposes provider or response errors instead of containing them. Validated `invoke()` runs the same input checks first, returns `None` on rejection, and exposes later execution exceptions; it returns data without `ExecMeta`.

For a structurally valid bundle, `run()` may also record `input_shape` before validation and
execution. The value has `groups` and `rows_per_group`; its counts do not change if the caller data
is later mutated. Invalid bundle structure omits this key.

After successful normalization, `output_shape` uses the same fields. Failures and timeouts omit it.
An all-empty successful output is normalized to `[[]]`, while a mixed multi-group output retains a
zero count for each empty group. Both shape keys are optional.

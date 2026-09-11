# Natural language to structured data

`nl2llm@3.0.0` sends a natural-language request to the configured LLM client and returns its structured records.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `<service_prefix>.*` | `properties:<service_prefix>.*` | `no` | `none` | helper:resolve_llm_client; Adapter and provider settings passed through client resolution. | `namespace` |
| `attrs` | `attributes` | `yes` | `[]` | attribute-spec:list[dict]; optional; Requested output fields. Each item must include `name` and may include `type`. | `structured` |
| `context` | `attributes` | `yes` | `""` | attribute-spec:str; optional; Domain context included in the request. | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Optional finite, positive timeout for `run()`. | `scalar` |
| `input_context` | `properties` | `no` | `"$[0]"` | none; Controls request templating or response extraction. | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | none; Controls request templating or response extraction. | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | none; Controls request templating or response extraction. | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | none; Controls request templating or response extraction. | `scalar` |
| `input_template` | `properties` | `no` | `source-sha256:2b6d3c9bbf1494dca65079a906fbabd2f7856155734751f0703552fbcffff94c` | none; Controls request templating or response extraction. | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | helper:resolve_llm_client; Adapter and provider settings passed through client resolution. | `namespace` |
| `llm_client` | `properties` | `no` | `none` | helper:resolve_llm_client; Injects an LLM client. Otherwise the client is resolved from the configured service. | `seam` |
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
| `query` | `attributes` | `yes` | `""` | attribute-spec:str; required; Nonblank request to process. | `scalar` |
| `service_prefix` | `properties` | `no` | `"openai"` | none; Selects the provider-property namespace. | `scalar` |

## Result and errors

The operator makes one provider call and expects a JSON array of records. An empty array is a successful empty result. A top-level object or another non-bundle shape is `EXECUTION_RESULT_INVALID` at `NORMALIZE`, while provider and parsing failures are `EXECUTION_FAILED` at `EXECUTE`.

`run()` rejects a blank or whitespace-only `query` before client resolution with `INVALID_INPUT` at `VALIDATE`. Raw `apply()` preserves the compatibility behavior and returns raw `[]` for a blank query. Validated `invoke()` runs the same input checks as `run()`, returns `None` on rejection, and exposes later execution exceptions; it returns data without `ExecMeta`.

Successful results have empty `output_attributes`; `meta.traces` may contain a nonnegative `elapsed_ms`. A synchronous call through the built-in client also includes numeric `cost` in USD and `cost_basis="estimated"` when LiteLLM provides a finite nonnegative price for exactly one provider attempt. A proven local response-cache hit reports `cost=0.0`; provider prompt caching remains a provider attempt. Both cost fields are absent when pricing is unknown, the client retries, the result fails, the call times out, or the caller supplies `llm_client`. Treat a missing cost as unavailable rather than zero. The declared `attrs` guide the request; they do not validate provider quality or guarantee that a live model follows the requested schema.

For a structurally valid bundle, `run()` may also record `input_shape` before validation and
execution. The value has `groups` and `rows_per_group`; its counts do not change if the caller data
is later mutated. Invalid bundle structure omits this key.

After successful normalization, `output_shape` uses the same fields. Failures and timeouts omit it.
An all-empty successful output is normalized to `[[]]`, while a mixed multi-group output retains a
zero count for each empty group. Both shape keys are optional.

# Semantic transformation

`semantic_transform@3.0.0` resolves an LLM-generated transformation plan and applies it to every supplied group.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `<service_prefix>.*` | `properties:<service_prefix>.*` | `no` | `none` | helper:resolve_llm_client; Adapter and provider settings passed through client resolution. | `namespace` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Optional finite, positive timeout for `run()`. | `scalar` |
| `input_context` | `properties` | `no` | `"$[0]"` | none; Controls request templating or response extraction. | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | none; Controls request templating or response extraction. | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | none; Controls request templating or response extraction. | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | none; Controls request templating or response extraction. | `scalar` |
| `input_meta` | `attributes` | `yes` | `{}` | attribute-spec:dict; optional; Optional descriptions, types, or hints for input fields. | `structured` |
| `input_template` | `properties` | `no` | `source-sha256:2644c0c4ea34e99fe97194d89dda0b5de99aa67c75ca6090869b2b1a53691839` | none; Controls request templating or response extraction. | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | helper:resolve_llm_client; Adapter and provider settings passed through client resolution. | `namespace` |
| `llm_client` | `properties` | `no` | `none` | helper:resolve_llm_client; Injects an LLM client. Otherwise the client is resolved from the configured service. | `seam` |
| `openai.api` | `properties` | `no` | `"ChatCompletion"` | none; Provider setting used during client resolution. | `scalar` |
| `openai.max_tokens` | `properties` | `no` | `1024` | none; Provider setting used during client resolution. | `scalar` |
| `openai.model` | `properties` | `no` | `"gpt-4o"` | none; Default model under the default service prefix. | `scalar` |
| `openai.stream` | `properties` | `no` | `false` | none; Provider setting used during client resolution. | `scalar` |
| `openai.temperature` | `properties` | `no` | `0.0` | none; Provider setting used during client resolution. | `scalar` |
| `output_cast` | `properties` | `no` | `"json"` | none; Controls request templating or response extraction. | `scalar` |
| `output_desc` | `attributes` | `yes` | `{}` | attribute-spec:dict; required; Describes target fields. Every target entry requires a string `description` and may set `required`. | `structured` |
| `output_path` | `properties` | `no` | `"$.choices[0].message.content"` | none; Controls request templating or response extraction. | `scalar` |
| `output_strip` | `properties` | `no` | `true` | helper:resolve_llm_client; Controls request templating or response extraction. | `presence` |
| `output_template` | `properties` | `no` | `none` | helper:resolve_llm_client; Controls request templating or response extraction. | `scalar` |
| `output_transformations` | `properties` | `no` | `source-sha256:4c5590a88361773f2b559375ccaed622ddaab9adeb52b16482d5b2ea9d10255b` | none; Controls request templating or response extraction. | `structured` |
| `service_prefix` | `properties` | `no` | `"openai"` | none; Selects the provider-property namespace. | `scalar` |
| `strategy` | `attributes` | `yes` | `"auto"` | attribute-spec:str; optional; `auto`, `per_record`, `distinct_required_values`, or `distinct_required_values_with_merged_fields`. | `scalar` |

## Plans, strategies, and results

Every nonempty group first makes a plan request. The response must be an object that covers every target in `output_desc`. Each plan entry must be an object with a string-array `source_fields` and a `transformation_type` of `field_mapping_without_value_change` or `field_mapping_with_value_change`. The selected strategy may then make additional provider calls. The distinct-value strategies reuse responses for repeated source values; the merged-fields variant may resolve several targets together.

Generated records must include every target marked `required` for that request. Optional targets may be absent. Plan fields are merged into the nested `output_desc` mappings. Structured `run()` deep-copies call attributes first, so the caller's dictionaries are unchanged. Raw `apply()` and a successful `invoke()` pass the caller's mappings through and can mutate them.

Empty groups keep their positions when another group is nonempty. Empty outer input or all-empty groups produce a successful empty result without client resolution. An empty or malformed `output_desc`, including an entry without a string `description`, is `INVALID_INPUT` at `VALIDATE`. A malformed or incomplete plan, or a generated record missing a required target, fails the whole call with `EXECUTION_FAILED` at `EXECUTE`. The required-target check follows the rendered prompt structure; unusual descriptions containing another target marker such as `- name:` can cause a false positive.

Successful results have empty `output_attributes`; `meta.traces` may contain a nonnegative `elapsed_ms`. Raw `apply()` returns data directly and exposes execution failures. Validated `invoke()` runs the same input checks first, returns `None` on rejection, and exposes later execution exceptions; it returns data without `ExecMeta`.

For a structurally valid bundle, `run()` may also record `input_shape` before validation and
execution. The value has `groups` and `rows_per_group`; its counts do not change if the caller data
is later mutated. Invalid bundle structure omits this key.

After successful normalization, `output_shape` uses the same fields. Failures and timeouts omit it.
An all-empty successful output is normalized to `[[]]`, while a mixed multi-group output retains a
zero count for each empty group. Both shape keys are optional.

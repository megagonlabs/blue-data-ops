# Semantic filter

`semantic_filter@2.0.0` asks an LLM client to decide whether each record satisfies natural-language conditions. It makes one client call per record in each nonempty group. Direct `apply()` returns `[]` without resolving a client for empty input, an empty first group, or an empty `filter_conditions` mapping.

## Provider disclosure and results

Each call receives the complete record, numbered condition text, `context`, and `demonstrations`. A condition whose field is missing is still sent, marked as not present. These values can therefore leave the process when the configured client uses an external provider. Loading this guide does not construct a client or make a call.

A true result retains the original record object. String results count as true only after stripping and lowercasing to `true`, `yes`, `1`, or `include`; other values use Python truthiness. With `return_idx=False`, the output contains matching records. With `return_idx=True`, each nonempty input group produces one record shaped as `{"indices": [...]}`.

The declared `return_idx` type is the compatibility spelling `boolean`. The base attribute parser does not recognize that spelling and treats it as `Any`, so callers should supply an actual `bool`. The live `io.attributes` mapping preserves this declaration. `output_attributes` is empty.

## Call boundaries

With valid conditions, `run()` normalizes empty input or an empty first group to a successful `[[]]` result without resolving a client. A missing, empty, or malformed `filter_conditions` mapping is instead a validation failure: `run()` returns `[[]]` with structured metadata and `invoke()` returns `None`. `run()` also contains provider failures as `[[]]` with execution metadata, while `apply()` exposes them directly. The operator has no separate timeout setting; the shared `run()` timeout property bounds the execution call.

The default path requires the `llm` extra and provider credentials. A caller can instead inject an `LLMClient` through `properties["llm_client"]`, as the owner check does without network access.

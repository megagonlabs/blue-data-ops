# Compatibility

`blue-data-ops` preserves the established Blue operator contracts while exposing them through the
standalone `Operator` API. The following deliberate differences are part of this package's current
behavior and should be changed only through a versioned compatibility decision.

## Maximum of non-numeric input

`MaxOperator` skips values that cannot be converted to a number and returns a null aggregate only
when no value coerces. The reference implementation can instead fail on mixed data whose first
value does not coerce; this keeps `max` consistent with the other aggregate operators.

## Vector similarity without field names

`VectorSimilarityOperator` accepts omitted `fields` when both inputs already contain embeddings.
Field names are required only when text must be embedded.

## Regular-expression substitution

The LLM output `sub` transformation passes its configured replacement string to the regular-expression
engine. It does not reuse the compiled search pattern as the replacement value.

## NL2LLM JSON cleanup

`NL2LLMOperator` removes the lowercase literal substring `json` while cleaning fenced responses,
including occurrences inside JSON keys or values. This compatibility behavior is intentionally
retained even though it can alter otherwise valid content.

## Registry injection accepts more types

`resolve_registry` accepts an injected `RegistrySeam` or a raw `blue_data` `DataRegistry` (which it
wraps); the reference resolver accepted only its own registry type. Invalid injected values still
fall through to keyed construction.

## LLM client injection and provider resolution are additions

`properties["llm_client"]` injection and the `provider` argument of `resolve_llm_client` are this
package's additions for testability and owner-scoped reuse. The default lifetime remains
construct-per-call with no shared client.

## Attribute validation is total

`Operator.validate` never raises: values the reference implementation would fail on after lax
coercion (e.g. incomparable types) validate as invalid here instead of raising.

## Tool-signature coupling is dropped

Operators expose only the declarative attribute metadata surface; the reference `Tool`
`get_signature()` dictionary coupling is intentionally not provided.

## Semantic transform grouping

`semantic_transform` keys value mappings by `(target_field, combination)`, so targets that share a
dependency combination do not overwrite each other; the reference implementation keys by
combination only. Merged-group lookups use the group's own dependency fields; the reference
implementation reuses the last target's source-field list, which can silently drop results.

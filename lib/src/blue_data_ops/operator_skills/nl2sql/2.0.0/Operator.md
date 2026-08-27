# NL-to-SQL

`nl2sql@2.0.0` translates a natural-language question into SQL and can optionally execute the generated query through the configured data registry. It reads the current database schema from that registry and sends the question, schema, protocol, context, and additional requirements to the configured LLM client.

## Inputs

Use the `io.attributes` mapping returned by `OperatorSkillLoader.load()` as the live, machine-readable schema for declared attributes. It is refreshed from the resolved operator when the view is loaded, but it is not an exhaustive inventory of compatibility inputs read by the implementation. The declared attributes include `source`, `database`, `collection`, `question`, and `protocol`, along with optional controls for case sensitivity, extra requirements, domain context, and requested output field names.

The implementation also reads the undeclared caller attribute `force_query_prefixes`. It changes only the prompt guidance sent to the LLM. The `validate_query_prefixes` property governs which prefixes the returned SQL is allowed to use.

The supported protocols are `postgres`, `mysql`, and `sqlite`. The operator fetches its schema from the data registry; the declared `schema` attribute does not replace that lookup in this version.

## Results

With query execution enabled, the operator returns the registry's normalized query result. With execution disabled, it returns `[[{"sql": "..."}]]`. The structured `run()` boundary adds execution metadata and currently returns an empty `output_attributes` mapping.

A blank question returns the successful-empty shape `[[]]` without a registry or provider call. For Blue compatibility, the execution check requires nonempty `protocol`, `database`, and `collection` values but deliberately does not require a nonempty `source`; an empty or omitted source is passed to the registry as an empty string. Missing registry configuration also produces the raw empty shape on the compatibility `apply()` path. Invalid protocols, missing database or collection addressing, malformed provider responses, invalid query prefixes, and provider failures remain errors; callers that need contained error records should use `run()`.

## Operational boundary

The default properties allow generated queries beginning with `SELECT` and execute the query. Owners should review both settings for their deployment. This guide describes the current operator; loading it does not execute the operator, contact a provider, change planner input, or grant the text authority over planning.

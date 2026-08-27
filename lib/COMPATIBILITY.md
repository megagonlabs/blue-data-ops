# Compatibility

`blue-data-ops` tracks the Blue operator contract while installing on its own. If you are porting code off Blue, the sections near the end on utilities, errors, the service client, and similarity tell you where behavior differs and what to use instead. The earlier sections record deliberate differences from Blue's reference behavior; maintainers should preserve them across upgrades and change them only through a versioned compatibility decision.

## Maximum of non-numeric input

`MaxOperator` skips values that cannot be converted to a number and returns a null aggregate only when no value coerces. The reference implementation can instead fail on mixed data whose first value does not coerce; this keeps `max` consistent with the other aggregate operators.

## Vector similarity without field names

`VectorSimilarityOperator` accepts omitted `fields` when both inputs already contain embeddings. Field names are required only when text must be embedded.

## Regular-expression substitution

The LLM output `sub` transformation passes its configured replacement string to the regular-expression engine. It does not reuse the compiled search pattern as the replacement value.

## NL2LLM JSON cleanup

`NL2LLMOperator` removes the lowercase literal substring `json` while cleaning fenced responses, including occurrences inside JSON keys or values. This compatibility behavior is intentionally retained even though it can alter otherwise valid content.

## Registry injection accepts more types

`resolve_registry` accepts an injected `RegistrySeam` or a raw `blue_data` `DataRegistry` (which it wraps); the reference resolver accepted only its own registry type. Invalid injected values still fall through to keyed construction.

## LLM client injection and provider resolution are additions

`properties["llm_client"]` injection and the `provider` argument of `resolve_llm_client` are this package's additions for testability and for reusing one client across calls. The default lifetime remains construct-per-call with no shared client.

## Attribute validation is total

`Operator.validate` never raises: values the reference implementation would fail on after lax coercion (e.g. incomparable types) validate as invalid here instead of raising.

## Raw and canonical execution

`apply()`, `validate()`, and `invoke()` preserve the raw Blue-compatible call shapes through v2.x. `apply()` calls the transform directly. `invoke()` runs boolean validation and returns `None` when validation is false; exceptions from the transform are not converted into execution metadata on these raw paths.

`run()` is the canonical v2 boundary. It materializes canonical defaults, validates, normalizes empty output to `[[]]`, and returns `(output_data, output_attributes, exec_meta)`. Recoverable, failed, and timed-out outcomes appear in `exec_meta.errors`. The same split applies to plan operators: raw `refiner()` returns serialized records, while normalized `refine()` returns `DataPipeline` objects and `ExecMeta`.

## Tool and operator metadata

Operators expose the Blue Tool/Operator metadata surface, including the signature dictionary from `get_signature()`, the parameter and return accessors, and live property access, alongside the declarative attribute schema. Signatures are generated with the same rules Blue uses, including the way it renders typing-annotated parameters and treats a falsy default as a required parameter.

## Semantic transform grouping

`semantic_transform` keys value mappings by `(target_field, combination)`, so targets that share a dependency combination do not overwrite each other; the reference implementation keys by combination only. Merged-group lookups use the group's own dependency fields; the reference implementation reuses the last target's source-field list, which can silently drop results.

## Portable plan boundaries

Portable data pipelines replace the reference runtime synchronizer with an optional injected `sync_backend`. The default is a no-op, so the plan package has no Redis, pubsub, stream, or connection dependency; the established `auto_sync` and per-call `sync` truth table is retained.

Operator entities store only pinned `operator_id` values in `name@<MAJOR.MINOR.PATCH>` form. Bare names, deployment routes, and host addresses are rejected so serialized plans remain deterministic and deployment-neutral.

Plan-producing operators emit the canonical live record through `to_dict()`. The reference implementation used the generic `get_data()` accessor for this emission path; both expose the same live record, but `to_dict()` is the portable serialization boundary.

`PipelineExecutor` is the package-local replacement for the smallest in-process part of Blue's `DataPlanner`: it validates a materialized graph, aggregates predecessor output, resolves exact operator IDs, calls `run()`, and updates node status and value. It intentionally does not reproduce Blue's Redis/pubsub synchronization, service clients, remote routing, recursive subplan merge, retry, or replanning. Refinement remains a separate step because the portable node record does not carry an alternative-selection policy.

## Planning boundaries

`PipelinePlanner` (2.2.0) builds a compiled `DataPipeline` from a goal or from one normalized refinement call. It is not a local port of Blue's `DataPlanner` and does not grow into one: it plans once and stops. There is no refinement loop, no replanning after a failed node, no remote dispatch, and no automatic choice among multiple alternatives under the default selector. A caller that wants a different plan builds a new `PlanningRequest`.

`plan_refinement()` accepts one explicit package-built `@2.0.0` refinement source. The request's nonempty exact-ID allowlist must admit the source and every child. The planner calls `refine()` once, rejects a bad batch as a whole, projects the complete portable graphs into drafts, and freshly compiles and preflights the selected draft. It does not collect a data-context snapshot or disclose packaged operator skill text. A scoped request remains anchored through compilation, including the source, database, and collection on an `nl2sql` child.

Two boundaries are deliberate and should survive upgrades.

The planner compiles only pinned `@2.0.0` operator ids that its own discovery returned, so a generator cannot introduce an operator the caller's discovery filters excluded. The compiler additionally requires an `nl2sql` step to address the same source, database, and collection the request scoped. That is an address-consistency check on the step's attributes, not a table authorization boundary: nothing constrains the tables the generated SQL reads, and `DataScope.entities` stays advisory planning context.

Planning raises `PlanningError` where operator execution returns errors inside `ExecMeta`. This is the one place the package reports a recoverable outcome by raising, and it is deliberate: planning either produces a compiled pipeline or produces nothing, so there is no partial result to carry a record. `PlanningError` subclasses `ValueError` and exposes `record`. It carries the same fields as the operator `ErrorRecord` apart from `operator_id`, which planning has no value for, and its `stage` is a `PlanningStage` rather than an `ErrorStage`.

## The OpenAI plan generator is a direct SDK seam

`OpenAIPlanGenerator` calls the official `openai` SDK directly rather than going through this package's litellm-backed `LLMClient`. The two seams stay separate on purpose. Operator-level LLM calls remain provider-agnostic through `LLMClient` and its `properties["llm_client"]` injection, while plan generation needs the provider's Structured Outputs guarantee, which the shared client does not model. Nothing else in the package imports the SDK, and the `openai` extra stays optional.

A data-context snapshot is disclosed to the provider only when the caller sets `send_data_context=True`. Absent that opt-in, a snapshot reaching `generate()` raises `DATA_CONTEXT_DISCLOSURE_REQUIRED` before the SDK import, the client, and any request. Preserve this failure rather than relaxing it to a silent drop: the caller asked for schema-aware planning, and quietly planning without the schema would answer a different question.

Provider failures map to codes that name the planning outcome (`GENERATOR_TIMEOUT`, `GENERATOR_RATE_LIMITED`, `GENERATOR_UNAVAILABLE`, and the rest) by exception class and HTTP status. No provider exception text, response body, request payload, credential, or provider identifier is interpolated into a record, so the record shape does not change if the SDK's messages do.

## Utility functions

`blue_data_ops.utils` provides the Blue helper functions operators depend on, under the same names (the README lists the import mapping). They match Blue's behavior, including the details that are easy to miss:

- `string_to_python_type` returns the same `typing` objects Blue returns. Examples include `typing.List[str]` and `typing.Optional[int]`, so code that compares the returned type object keeps working.
- `validate_parameter_type` applies the same lax Pydantic coercion. A malformed specification that cannot build a type (such as `union[]`) returns `False` rather than leaking a parser error, while an unknown or partial form can fall back to `Any` and validate as `True`; it raises `RuntimeError` only on an internal validation fault.
- `merge_json` uses `jsonmerge`, so merging an object onto a scalar base raises rather than silently replacing it, matching Blue.
- `extract_signature` produces the same parameter and return schema in both its plain and MCP forms, including an empty return schema for a `-> None` annotation.

Helpers outside the operator surface are not carried over: most of `json_utils`, the base64 helpers in `string_utils`, and the logging helpers are omitted.

## Errors: BlueError and ErrorLoom

This package does not provide `BlueError` or the `ErrorLoom` catching mixin. Both are tied to Blue's agent and service runtime, and the package reports failures through its own result model instead:

- `run()` (and `refine()` for plan-producing operators) returns execution metadata whose `errors` list holds structured records with a stable category, code, operator id, stage, message, retryability flag, and optional suggestion. A recoverable problem such as invalid input is reported this way, not raised.
- Resolving an unknown or malformed operator id raises `ResolveError` (from `blue_data_ops.operators`).
- The LLM client raises `LLMError` (from `blue_data_ops.llm`) for transport and provider failures.
- Planning raises `PlanningError` (from `blue_data_ops.plan`), which carries a structured `record` in place of a returned metadata object.

`run()` returns a `(output_data, output_attributes, meta)` tuple, so `except BlueError` becomes reading `meta.errors`:

```python
from blue_data_ops.operators import ResolveError, versioned_registry
from blue_data_ops.llm import LLMError

op = versioned_registry().resolve("select@2.0.0")
output_data, output_attributes, meta = op.run(data, attributes)
for error in meta.errors:            # structured records instead of a raised BlueError
    print(error.category, error.code, error.message)
```

Catch `ResolveError`, `LLMError`, and `PlanningError` at their boundaries. Classes that inherited `ErrorLoom` should adopt the same result-based reporting; there is no drop-in replacement for its automatic method wrapping.

## Service client

Blue's `ServiceClient` request and response surface (`get_properties`, `extract_input_params`, `extract_output_params`, `extract_api_properties`, `create_message`, `create_output`, `validate_input`, `process_output`, and `execute_api_call`) is not provided as a compatibility class in this release. LLM operators use this package's own client at the `execute_api_call` boundary, and injecting a client through `properties["llm_client"]` covers the common test and reuse cases. If you used `ServiceClient` for non-LLM service calls, there is no interim replacement here yet. Those callers wait for a Blue-shaped local client that mirrors the full method surface, planned for a later release.

## Similarity utilities

Blue's `similarity_utils` (BM25 scoring, score normalization, and vector similarity) is not reproduced here. Registry search and ranking come from the `blue-data` package, and its scoring is not a drop-in match for Blue's:

- BM25 scores use different tuning constants, so absolute scores differ and relative rankings can differ.
- Score normalization supports the same named methods (min-max, log, linear) but uses different formulas and a different unknown-method fallback, has no maximum-score parameter, and matches Blue only on ordinary min-max inputs. For an all-zero input, Blue returns `1.0` where `blue-data` returns `0.0`.
- Vector similarity clips an unnormalized score into `[0, 1]`, so a negative cosine value that Blue returns as-is is reported here as `0`.

Code that depended on Blue-exact similarity numbers should treat `blue-data`'s results as a different implementation, not an alias.

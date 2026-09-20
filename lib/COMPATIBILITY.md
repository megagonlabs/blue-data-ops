# Compatibility

`blue-data-ops` tracks the Blue operator contract while installing on its own. This file records the 3.0 migration boundary and deliberate differences from Blue's reference behavior. The utility, error, service-client, and similarity sections near the end cover porting details.

## Core 3.0 removals

Core 3.0 removes the four plan-producing operator names, all eight of their v1/v2 exact IDs, and the refinement API deprecated in 2.8.0. The removed API includes `refiner()`, `refine()`, `PipelinePlanner.plan_refinement()`, `RefinableOperator`, `DeclarativeOperator`, the module-level refiner helpers, and the four MCP `__refine` companions.

`BlueDataOpsDeprecationWarning` remains importable as a compatibility category. Package 3.0 no longer emits it because the package-owned deprecated surfaces that used it have been removed.

The registry now contains 87 historical cards: 33 at `@1.0.0`, 33 at `@2.0.0`, and 21 at `@3.0.0`. `active_registry()` selects the 33 ordinary exact IDs for current discovery and execution. The generated reference and MCP default use that same selection. Operator-skill resources contain 54 packages: 33 retained v2 packages and 21 v3 packages.

Exact resolution of `multipart_query`, `nl2query_router`, `plan_discover`, or `query_breakdown` at versions 1 or 2 through a package registry raises `ResolveError`. A stored `DataPipeline` containing one of those IDs still parses through `from_dict()`, then fails executor preflight at exact resolution.

The supported manual migration covers two cases. Replace a `DeclarativeOperator` used as an executable leaf with an ordinary `Operator` subclass. For one fixed graph, construct and execute a materialized `DataPipeline` directly, or implement `PlanGenerator.generate()` to return `Sequence[PlanDraft]` for `PipelinePlanner`.

Core 3.0 does not preserve automatic refinement or automatic expansion of old declarative plan definitions. The tested graph successor covers one fixed linear expansion. It does not preserve dynamic alternatives, malformed-plan normalization, raw v1 refiner behavior, or a general `DeclarativeOperator` subclass hierarchy. This supported manual subset is non-drop-in. Callers that need the removed semantics should remain on a compatible core 2.x/MCP 0.x pair, such as core 2.10.0 with MCP 0.12.0.

Nine tags used only by the retired cards leave the taxonomy, including `capability-query-routing`, `flow-plan`, and `produces-plan`. `domain-plan` remains on `data_discover`.

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

## Ordinary attribute validation

The ordinary three-argument `Operator.validate(input_data, attributes, properties)` path returns `False` for values the reference implementation would fail on after lax coercion, such as incomparable types.

## Raw and canonical execution

`apply()`, `validate()`, and `invoke()` preserve raw Blue-compatible call shapes. `apply()` calls the transform directly and `invoke()` runs boolean validation, returning `None` when validation is false. Exceptions from transforms are not converted into execution metadata on raw paths.

`run()` is the canonical structured boundary. It materializes canonical defaults, validates, normalizes empty output to `[[]]`, and returns `(output_data, output_attributes, exec_meta)`. Recoverable, failed, and timed-out outcomes appear in `exec_meta.errors`.

`PipelineExecutor.execute()` returns a `PipelineRun`. Its final data is in `output_data`, and its ordered `node_runs` tuple holds one `NodeRun` per completed operator node. Read `node_run.exec_meta` for that node's structured outcome. Operator failures after preflight remain in this metadata; `failed_node_id` identifies the first failed node and `succeeded` reports whether execution completed.

## Tool and operator metadata

Operators expose the Blue Tool/Operator metadata surface, including the signature dictionary from `get_signature()`, the parameter and return accessors, and live property access, alongside the declarative attribute schema. Signatures are generated with the same rules Blue uses, including the way it renders typing-annotated parameters and treats a falsy default as a required parameter.

## Semantic transform grouping

`semantic_transform` keys value mappings by `(target_field, combination)`, so targets that share a dependency combination do not overwrite each other; the reference implementation keys by combination only. Merged-group lookups use the group's own dependency fields; the reference implementation reuses the last target's source-field list, which can silently drop results.

## Portable plan boundaries

Portable data pipelines replace the reference runtime synchronizer with an optional injected `sync_backend`. The default is a no-op, so the plan package has no Redis, pubsub, stream, or connection dependency; the established `auto_sync` and per-call `sync` truth table is retained.

Operator entities store only pinned `operator_id` values in `name@<MAJOR.MINOR.PATCH>` form. Bare names, deployment routes, and host addresses are rejected so serialized plans remain deterministic and deployment-neutral.

`to_dict()` is the portable serialization boundary for a materialized plan.

`PipelineExecutor` is the package-local replacement for the smallest in-process part of Blue's `DataPlanner`: it validates a materialized graph, aggregates predecessor output, resolves exact operator IDs, calls `run()`, and updates node status and value. It does not reproduce Blue's Redis/pubsub synchronization, service clients, remote routing, recursive subplan merge, retry, or replanning.

## Planning boundaries

`PipelinePlanner` builds a compiled `DataPipeline` from a goal. It is not a local port of Blue's `DataPlanner`: it plans once and stops. There is no retry, replanning after a failed node, remote dispatch, or automatic choice among multiple alternatives under the default selector. A caller that wants a different plan builds a new `PlanningRequest`.

Two boundaries are deliberate and should survive upgrades.

The planner compiles only admitted, supported exact operator IDs that its own discovery returned, so a generator cannot introduce an operator excluded by the caller's filters. Admission may include the active built-in set, explicitly allowed retained v2/v3 built-ins, or caller-created v2 cards used with a caller-owned rule or generator. The compiler additionally requires an `nl2sql` step to address the source, database, and collection named by the request. This is an address-consistency check, not table authorization: generated SQL may still read tables outside `DataScope.entities`.

Planning raises `PlanningError` where operator execution returns errors inside `ExecMeta`. This is the one place the package reports a recoverable outcome by raising, and it is deliberate: planning either produces a compiled pipeline or produces nothing, so there is no partial result to carry a record. `PlanningError` subclasses `ValueError` and exposes `record`. It carries the same fields as the operator `ErrorRecord` apart from `operator_id`, which planning has no value for, and its `stage` is a `PlanningStage` rather than an `ErrorStage`.

## The OpenAI plan generator is a direct SDK seam

`OpenAIPlanGenerator` calls the official `openai` SDK directly rather than going through this package's litellm-backed `LLMClient`. The two seams stay separate on purpose. Operator-level LLM calls remain provider-agnostic through `LLMClient` and its `properties["llm_client"]` injection, while plan generation needs the provider's Structured Outputs guarantee, which the shared client does not model. Nothing else in the package imports the SDK, and the `openai` extra stays optional.

A data-context snapshot is disclosed to the provider only when the caller sets `send_data_context=True`. Absent that opt-in, a snapshot reaching `generate()` raises `DATA_CONTEXT_DISCLOSURE_REQUIRED` before the SDK import, the client, and any request. Preserve this failure rather than relaxing it to a silent drop: the caller asked for schema-aware planning, and quietly planning without the schema would answer a different question.

Provider failures map to codes that name the planning outcome (`GENERATOR_TIMEOUT`, `GENERATOR_RATE_LIMITED`, `GENERATOR_UNAVAILABLE`, and the rest) by exception class and HTTP status. No provider exception text, response body, request payload, credential, or provider identifier is interpolated into a record, so the record shape does not change if the SDK's messages do.

## Operator skill index validation

`OperatorSkillLoader` treats its package index as a closed exact-path map. A manifest name whose key carries a `.` or `..` path segment invalidates the whole index, so every index-backed entry point (`available_operator_ids()`, `describe()`, `load()`, and `read()`) raises `OperatorSkillLoadError` with code `MANIFEST_INVALID`. One poisoned row closes the index instead of being skipped, so a legitimate operator whose own row is intact fails the same way.

Direct calls keep their established precedence: `describe()`, `load()`, or `read()` given a malformed operator id such as `..@1.0.0` raises `OperatorSkillLoadError` with code `INVALID_OPERATOR_ID` before the index is read at all. A malformed id is never reported as a manifest problem.

## Utility functions

`blue_data_ops.utils` provides the Blue helper functions operators depend on, under the same names (the README lists the import mapping). They match Blue's behavior, including the details that are easy to miss:

- `string_to_python_type` returns the same `typing` objects Blue returns. Examples include `typing.List[str]` and `typing.Optional[int]`, so code that compares the returned type object keeps working.
- `validate_parameter_type` applies the same lax Pydantic coercion. A malformed specification that cannot build a type (such as `union[]`) returns `False` rather than leaking a parser error, while an unknown or partial form can fall back to `Any` and validate as `True`; it raises `RuntimeError` only on an internal validation fault.
- `merge_json` uses `jsonmerge`, so merging an object onto a scalar base raises rather than silently replacing it, matching Blue.
- `extract_signature` produces the same parameter and return schema in both its plain and MCP forms, including an empty return schema for a `-> None` annotation.

Helpers outside the operator surface are not carried over: most of `json_utils`, the base64 helpers in `string_utils`, and the logging helpers are omitted.

## Errors: BlueError and ErrorLoom

This package does not provide `BlueError` or the `ErrorLoom` catching mixin. Both are tied to Blue's agent and service runtime, and the package reports failures through its own result model instead:

- `run()` returns execution metadata whose `errors` list holds structured records with a stable category, code, operator id, stage, message, retryability flag, and optional suggestion. A recoverable problem such as invalid input is reported this way, not raised.
- Resolving an unknown or malformed operator id raises `ResolveError` (from `blue_data_ops.operators`).
- The LLM client raises `LLMError` (from `blue_data_ops.llm`) for transport and provider failures.
- Pipeline preflight and invalid execution input raise `PipelineError` (from `blue_data_ops.plan`). An operator failure after preflight is returned in `PipelineRun` instead.
- Planning raises `PlanningError` (from `blue_data_ops.plan`), which carries a structured `record` in place of a returned metadata object.

`run()` returns a `(output_data, output_attributes, meta)` tuple, so `except BlueError` becomes reading `meta.errors`:

```python
from blue_data_ops.operators import ResolveError, active_registry
from blue_data_ops.llm import LLMError

op = active_registry().resolve("select@2.0.0")
output_data, output_attributes, meta = op.run(data, attributes)
for error in meta.errors:  # structured records instead of a raised BlueError
    print(error.category, error.code, error.message)
```

Catch `ResolveError`, `LLMError`, `PipelineError`, and `PlanningError` at their boundaries. Classes that inherited `ErrorLoom` should adopt the same result-based reporting; there is no drop-in replacement for its automatic method wrapping.

## Service client

Blue's `ServiceClient` request and response surface (`get_properties`, `extract_input_params`, `extract_output_params`, `extract_api_properties`, `create_message`, `create_output`, `validate_input`, `process_output`, and `execute_api_call`) is not provided as a compatibility class. LLM operators use this package's own client at the `execute_api_call` boundary, and injecting a client through `properties["llm_client"]` covers the common test and reuse cases. For non-LLM service calls, keep using Blue's `ServiceClient` or provide an adapter for the methods your integration needs; `blue-data-ops` has no drop-in replacement.

## Similarity utilities

Blue's `similarity_utils` (BM25 scoring, score normalization, and vector similarity) is not reproduced here. Registry search and ranking come from the `blue-data` package, and its scoring is not a drop-in match for Blue's:

- BM25 scores use different tuning constants, so absolute scores differ and relative rankings can differ.
- Score normalization supports the same named methods (min-max, log, linear) but uses different formulas and a different unknown-method fallback, has no maximum-score parameter, and matches Blue only on ordinary min-max inputs. For an all-zero input, Blue returns `1.0` where `blue-data` returns `0.0`.
- Vector similarity clips an unnormalized score into `[0, 1]`, so a negative cosine value that Blue returns as-is is reported here as `0`.

Code that depended on Blue-exact similarity numbers should treat `blue-data`'s results as a different implementation, not an alias.

## One concept, six attribute names

The reduce key is spelled six ways across the arithmetic operators: `argmax_key`, `argmin_key`, `avg_key`, `max_key`, `min_key` and `sum_key`. They name the same thing — the key whose values an operator reduces — and a caller moving between two of those operators has to change the attribute name as well as the operator.

They stay as they are in 3.1, and that is a decision rather than an oversight.

Attribute names are part of the operator contract. They appear in the card each operator publishes, in the generated reference, in the resource package that documents each exact version, in the schema every MCP client reads, and in the attributes map of every existing caller. Collapsing six names to one `key` is a breaking change to all of those at once, and a breaking change to an operator contract belongs in a major release with a migration, not in a minor release whose subject is packaging and documentation.

When it happens, the shape is already decided: accept both spellings for one release with the old name undocumented and the new one published, then drop the old name in the release after. That gives a caller a version in which either spelling works, which a straight rename does not.

Until then, the mapping is the obvious one — each operator's reduce key is its own name followed by `_key`, and `operator inspect` on the command line or the tool schema over MCP will show it.

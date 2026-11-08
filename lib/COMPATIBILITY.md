# Compatibility

`blue-data-ops` tracks the Blue operator contract while installing on its own. This file records the 3.0 migration boundary and deliberate differences from Blue's reference behavior. The utility, error, service-client, and similarity sections near the end cover porting details.

## Core 3.0 removals

Core 3.0 removes the four plan-producing operator names, all eight of their v1/v2 exact IDs, and the refinement API deprecated in 2.8.0. The removed API includes `refiner()`, `refine()`, `PipelinePlanner.plan_refinement()`, `RefinableOperator`, `DeclarativeOperator`, the module-level refiner helpers, and the four MCP `__refine` companions.

`BlueDataOpsDeprecationWarning` remains importable as a compatibility category. Package 3.0 no longer emits it because the package-owned deprecated surfaces that used it have been removed.

The registry now contains 88 historical cards: 33 at `@1.0.0`, 33 at `@2.0.0`, 21 at `@3.0.0`, and `nl2sql@4.0.0`. `active_registry()` selects the 33 ordinary exact IDs for current discovery and execution. The generated reference and MCP default use that same selection. Operator-skill resources contain 55 packages: 33 retained v2 packages, 21 v3 packages, and the nl2sql v4 package.

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

## Legacy semantic response handling

Default v1 and explicit v1/v2 semantic operators now reject malformed replies at runtime. This intentionally removes legacy coercions; operator IDs, schemas and version selection remain unchanged. Active v3 keeps its existing validation.

- `semantic_filter`: Accept booleans or trimmed, case-insensitive strings: `true`/`false`, `yes`/`no`, `1`/`0` and `include`/`exclude` select or exclude a record. Numeric values, punctuated strings such as `Yes.` and other replies are rejected. A false decision remains a successful exclusion. Active `@3.0.0` accepts only booleans and `true`/`false` strings.
- `semantic_extract`: Combined replies must contain exactly the requested entity names, with list values; list elements retain their existing types. Individual replies must be string lists. Empty lists remain valid.
- `semantic_project`: Replies must map existing schema names to unique nonblank string destinations. Unknown source names and duplicate destinations are rejected. An empty object selects no columns and remains valid.
- `semantic_transform`: Plans must include every requested target, string-list `source_fields`, and a known `transformation_type`. Missing classifications and invalid extra plan values are rejected. Extra valid plan keys are allowed. Generated objects must include fields marked `required is True` only when requested in that call. Optional omissions and explicit nulls remain valid.
- `semantic_join`: Batch replies must contain exactly `pair_1` through `pair_N`, with native booleans or trimmed, case-insensitive strings. `true`, `yes`, `1`, `match` and `join` mean match; `false`, `no`, `0` and `exclude` mean non-match. `include` is rejected: the previous join parser did not accept it as a positive answer. Positional arrays, numeric values and unknown strings are rejected. Active `@3.0.0` still requires native booleans. All-false replies remain valid. An embedding preparation exception falls back to all Cartesian pairs, requiring ceil(N*M/batch) model calls, where N and M are the two group sizes and batch is `batch_size`. A failure after optimization sampling can add the sample call to that fallback. The `estimate_cost`/`max_llm_calls` check uses the up-front estimate; a fallback can make more calls than the limit. Successful all-low-score embedding passes still make zero model calls.

Inspect `exec_meta.errors` after `run()` and each pipeline node. A malformed reply fails the whole call without partial output; raw `apply()` and valid-input `invoke()` raise the operator's format exception. Arbitrary provider exceptions retain their existing diagnostic contract. Validation checks reply shape. A well-formed empty reply passes even when the model did not provide useful data.

## Operator deadlines and registry configuration

The bare `timeout: 300` instance seed has been removed, so it no longer appears in `get_properties()`. Operator execution reads only finite positive `execution.timeout_seconds`; absent or legacy-only controls leave the call unbounded. A timeout stops waiting without terminating the worker or rolling back backend effects. The LLM client's provider `timeout` is separate, and raw `apply()`/`invoke()` do not acquire a deadline.

MCP uses one deployment registry per server and refuses unconfigured registry calls with an operator failure. Configure it through `data_registry=` or the shared environment builder. Ordinary Python default-provider resolution remains unchanged. See [MCP setup](../docs/mcp.md#deployment-data-registry) for initialization effects, async admission and the timeout drain. The CLI also uses the shared builder but retains an empty-memory default and its ephemeral warning. Unsupported store selectors, surrounding selector whitespace and explicit missing source files now fail instead of silently falling back or doing nothing.

## Semantic transform grouping

`semantic_transform` keys value mappings by `(target_field, combination)`, so targets that share a dependency combination do not overwrite each other; the reference implementation keys by combination only. Merged-group lookups use the group's own dependency fields; the reference implementation reuses the last target's source-field list, which can silently drop results.

## Portable plan boundaries

Portable data pipelines replace the reference runtime synchronizer with an optional injected `sync_backend`. The default is a no-op, so the plan package has no Redis, pubsub, stream, or connection dependency; the established `auto_sync` and per-call `sync` truth table is retained.

Operator entities store only pinned `operator_id` values in `name@<MAJOR.MINOR.PATCH>` form. Bare names, deployment routes, and host addresses are rejected so serialized plans remain deterministic and deployment-neutral.

`to_dict()` is the portable serialization boundary for a materialized plan.

`PipelineExecutor` is the package-local replacement for the smallest in-process part of Blue's `DataPlanner`: it validates a materialized graph, aggregates predecessor output, resolves exact operator IDs, calls `run()`, and updates node status and value. It does not reproduce Blue's Redis/pubsub synchronization, service clients, remote routing, recursive subplan merge, retry, or replanning.

### Pipeline property precedence

Ordinary property layers keep their existing precedence: stored pipeline, current invocation, then
the individual operator node. Operator defaults remain below all three.

The model-generation aliases are the exception. For those keys, the current invocation is the
lowest layer, the stored pipeline is next, and the individual operator node is highest. Move an LLM
value that must vary per execution out of the stored pipeline. Put it on a node when that operator
must differ from the pipeline-wide value. The neutral `llm.*` keys and the namespace selected by
`service_prefix` follow this LLM-specific order. Invocation-supplied execution seams such as
`execution.timeout_seconds` and `data_registry` continue to override stored pipeline values.

## Planning boundaries

`PipelinePlanner` builds a compiled `DataPipeline` from a goal. It is not a local port of Blue's `DataPlanner`: it plans once and stops. There is no retry, replanning after a failed node, remote dispatch, or automatic choice among multiple alternatives under the default selector. A caller that wants a different plan builds a new `PlanningRequest`.

Two boundaries are deliberate and should survive upgrades.

The planner compiles only admitted, supported exact operator IDs that its own discovery returned, so a generator cannot introduce an operator excluded by the caller's filters. Admission may include the active built-in set, explicitly allowed retained v2/v3 built-ins and exactly nl2sql@4.0.0, or caller-created v2 cards used with a caller-owned rule or generator. The compiler additionally requires an `nl2sql` step to address the source, database, and collection named by the request. This is an address-consistency check, not table authorization: generated SQL may still read tables outside `DataScope.entities`.

Planning raises `PlanningError` where operator execution returns errors inside `ExecMeta`. This is the one place the package reports a recoverable outcome by raising, and it is deliberate: planning either produces a compiled pipeline or produces nothing, so there is no partial result to carry a record. `PlanningError` subclasses `ValueError` and exposes `record`. It carries the same fields as the operator `ErrorRecord` apart from `operator_id`, which planning has no value for, and its `stage` is a `PlanningStage` rather than an `ErrorStage`.

## The OpenAI plan generator is a direct SDK seam

`OpenAIPlanGenerator` calls the official `openai` SDK directly rather than going through this package's litellm-backed `LLMClient`. The two seams stay separate on purpose. Operator-level LLM calls remain provider-agnostic through `LLMClient` and its `properties["llm_client"]` injection, while plan generation needs the provider's Structured Outputs guarantee, which the shared client does not model. Nothing else in the package imports the SDK, and the `openai` extra stays optional.

A data-context snapshot is disclosed to the provider only when the caller sets `send_data_context=True`. Absent that opt-in, a snapshot reaching `generate()` raises `DATA_CONTEXT_DISCLOSURE_REQUIRED` before the SDK import, the client, and any request. Preserve this failure rather than relaxing it to a silent drop: the caller asked for schema-aware planning, and quietly planning without the schema would answer a different question.

Provider failures map to codes that name the planning outcome (`GENERATOR_TIMEOUT`, `GENERATOR_RATE_LIMITED`, `GENERATOR_UNAVAILABLE`, and the rest) by exception class and HTTP status. No provider exception text, response body, request payload, credential, or provider identifier is interpolated into a record, so the record shape does not change if the SDK's messages do.

## Operator skill index validation

`OperatorSkillLoader` treats its package index as a closed exact-path map. A manifest name whose key carries a `.` or `..` path segment invalidates the whole index, so every index-backed entry point (`available_operator_ids()`, `describe()`, `load()`, and `read()`) raises `OperatorSkillLoadError` with code `MANIFEST_INVALID`. A single invalid row invalidates the entire index rather than being skipped, so a legitimate operator whose own row is intact fails the same way.

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
data = [[{"total": 2}, {"total": 5}]]
attributes = {"operand_key": "total", "operand": ">", "operand_val": 3}
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

These names remain unchanged in this release.

Attribute names are part of the operator contract. They appear in the card each operator publishes, in the generated reference, in the resource package that documents each exact version, in the schema every MCP client reads, and in the attributes map of every existing caller. Collapsing six names to one `key` is a breaking change to all of those at once, and a breaking change to an operator contract belongs in a major release with a migration, not in a minor release whose subject is packaging and documentation.

When it happens, the shape is already decided: accept both spellings for one release with the old name undocumented and the new one published, then drop the old name in the release after. That gives a caller a version in which either spelling works, which a straight rename does not.

Until then, the mapping is the obvious one — each operator's reduce key is its own name followed by `_key`, and `operator inspect` on the command line or the tool schema over MCP will show it.

## LLM prompt and SQL execution security changes

`utils.safe_substitute(template, **kwargs)` keeps its public import and signature
but now applies one dollar-placeholder pass. Unknown names, inserted dollar tokens,
Jinja syntax, and line endings remain literal. Chained and Jinja evaluation from
Blue's older helper is no longer supported.

Operator callers cannot override prompt, extraction, or transport controls. Define
custom prompts in trusted operator defaults. An injected client's stored prompt
and `output_template` cannot replace another operator's defaults.

NL2SQL generates SQL by default. Execution requires a host-bound
`ReadOnlySQLExecutor`, an approved target, and `execute_query=True`. Caller registry
selectors cannot grant access. Stock CLI/MCP instances have no executor; see the
[SQL execution guide](../docs/llm-settings.md#sql-execution) for host setup and limits.


## Execution diagnostics

Malformed built-in model replies now produce fixed format diagnostics. Shared decoder failures
remain catchable as `JSONDecodeError`, `ValueError` or `TypeError`, with fixed arguments and no
linked original exception. Legacy v1/v2 semantic coercions now fail validation; raw calls raise operator format errors;
structured v2 calls gain the diagnostic when their existing shared decoder rejects a reply.
Invalid `nl2llm@3.0.0` record shapes still use `EXECUTION_RESULT_INVALID / NORMALIZE`.

Structured `nl2sql@3.0.0` and `nl2sql@4.0.0` check the declared database and collection before generation.
On PostgreSQL and MySQL sources, a name missing from a nonempty registered list is refused without a
model call. On SQLite, generation is refused only when populated registered peers and a directory name
listing prove absence; missing or unavailable directories remain inconclusive. Custom source classes,
registries that supply their own `get_data_source_schema` or are not blue-data `DataRegistry` objects,
and empty registered lists are not checked; the `schema` attribute does not change the check. A
populated list is enforced even when it is stale: a database or collection created after the last sync
is refused until the source is synced, and on MySQL until the source and its registry are recreated.
Raw `apply()`, v1/v2 and host-bound SQL execution retain their routing and capability checks.

Genuine loaded database/provider classes receive fixed diagnostics. Classifiers do not load drivers
or providers. Transient provider records may advise another call; client retry attempts and delays
are unchanged. Pipeline CLI summaries retain a stopped node's recoverable record. Escaped custom
`run()` exceptions in MCP receive the same generic metadata as PipelineExecutor, while deadlines,
cancellation and worker admission keep their existing behavior.

Custom authors may explicitly publish fixed constants with `OperatorExecutionError`; see
[the authoring contract](../docs/extending.md#intentional-public-execution-diagnostics). This is a
trusted-author channel, not a redaction mechanism. It cannot detect deliberate dynamic text.

## SQL execution and dialects

`nl2sql@4.0.0` is active; @1/@2/@3 resolve through `versioned_registry()` or CLI
`--catalog history` with current host-only restrictions. @3 and @4 share the same
implementation. Adapters must resolve exactly @4 and bind host-approved targets
through the public host constructor. Card IDs are independent of distribution
versions. Caller registry selectors grant no authority.
Install the current `blue-data-ops` 1.0.0 source;
a package version range alone cannot distinguish builds with the same label.

Schema generation uses registered entity and attribute names and declared types,
plus relation names and source/target endpoints (`source`, `target`, `source_entity`,
`target_entity`). The optional `foreign_keys_source_columns` and
`foreign_keys_target_columns` fields are copied only as validated string lists;
other shapes fail closed. Missing types are omitted. Row samples,
connection properties and arbitrary metadata are excluded. Registered schema may
be stale; run `sync_source` before generation because an unsynced source can return
an empty schema. Lookup failures are errors rather than an empty-schema fallback.

The public executor admits one exact-string SELECT and rejects unquoted INTO tokens
and ambiguous syntax before driver execution. It may refuse valid dialect syntax;
generation alone does not grant execution. Numeric-looking identifiers may need
quoting because dialects tokenize them differently. See the execution guide for the syntax
boundary and supported-source details.

Use a least-privilege principal without FILE or equivalent file/network privileges.
SELECT functions such as LOAD_FILE, SLEEP, lo_export and pg_read_file remain subject
to database grants and resource controls; this executor is not a general SQL sandbox.
Target collections constrain routing, not which tables generated SQL can read.

Both insert cards use the resolved backend: SQLite/unknown sources retain qmark
parameters and double quotes; PostgreSQL uses %s and escaped double quotes; MySQL
uses %s and escaped backticks. MySQL uses its normal batch API for ordinary names
and a separate prepared statement when an identifier contains %s. Percent-containing
identifiers are preserved through each driver's binding rules. A failed batch rolls back and closes
resources while earlier committed batches remain committed. Unknown counts remain
omitted at @3. Collection does not qualify a table identifier; PostgreSQL uses the
connection search path.


SQL execution accepts DataRegistry instances and subclasses through `isinstance`; proxy or wrapped registries are refused. Sources must be the supported concrete SQLiteDBSource, PostgresDBSource or MySQLDBSource classes; source subclasses and wrappers are refused.

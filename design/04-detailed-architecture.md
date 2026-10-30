# blue-data-ops — Detailed Architecture

Here the components from [03-high-level-architecture.md](03-high-level-architecture.md) are wired together: which path a call takes, what each stage hands the next, and where a failure lands.
The class and function inventory is [06-library.md](06-library.md); the data shapes are [10-data-model.md](10-data-model.md).

## External Interfaces

Every implemented interface ends at the same place: `Operator.run()` on an instance resolved from a registry.

| Interface | Technology | Primary use | Status |
|---|---|---|---|
| Python Library | native Python API | embedding operators, pipelines, and planning in a Python process | Implemented |
| MCP Server | MCP over streamable HTTP, `FastMCP` | LLM agent tool use | Implemented, separate distribution |
| CLI | `blue-ops`, Click over the library | running and inspecting operators, catalogs, and pipelines from a shell | Implemented, separate distribution |
| REST API | — | — | **Not built.** No `platform/api/`, no HTTP framework in any dependency set |

### Python Library

Direct method calls with no serialization step.
A caller resolves an operator and calls it, or builds a `DataPipeline` and hands it to an executor, or states a goal and hands it to a planner.
Everything below describes this path; the MCP adapter is a projection of it.

### MCP Server

A translation layer, and deliberately a thin one.
Tool registration is frozen at server construction, the arguments are the same three the Python call takes, and the result is the same triple projected onto JSON once.

## Information flow overview

Nine paths, grouped by what the caller is trying to do.

| Path | Entry point | What it produces |
|---|---|---|
| Raw call | `Operator.apply()`, `Operator.invoke()` | an output bundle, or `None` from `invoke()` on failed validation; exceptions propagate |
| Canonical call | `Operator.run()` | `(output_data, output_attributes, exec_meta)`, always |
| Registry resolution | `OperatorRegistry.resolve()` | the exact operator bound to one pinned ID |
| Discovery | `OperatorRegistry.find()`, `OperatorEmbeddingIndex.find()` | ranked, already-pinned cards |
| Pipeline execution | `PipelineExecutor.preflight()`, `.execute()` | a `PipelinePreflight`, or a `PipelineRun` with one `NodeRun` per operator node |
| Planning | `PipelinePlanner.plan()`, `.run()` | a `PlanningResult`, or a raised `PlanningError` |
| Data context | `DataContextProvider.collect()` | a validated `DataContextSnapshot` carrying schema and no rows |
| Skill load | `OperatorSkillLoader.load()`, `.read()`, `.describe()` | verified resource text plus the live attribute schema |
| Registry-backed data work | `resolve_registry()` inside an operator | a `RegistrySeam`, then side effects on the caller's data source |

---

## Raw call path

The shapes a v1 caller already wrote, kept working.

1. Caller holds a concrete operator instance, by construction or from a registry.
2. `apply(input_data, attributes, properties)` calls the transform directly. Declared defaults are not materialized, and the attributes the transform reads are exactly what the caller passed.
3. `invoke(input_data, attributes, properties)` calls `validate()` first, returns `None` when it is false, and otherwise calls `apply()`.
4. `validate(input_data, attributes, properties)` checks values against the live attribute definitions and returns a bool. The base implementation is total and never raises; an operator that overrides it adds its own checks on top.
5. An exception from the transform propagates to the caller unchanged. Nothing on this path converts it into an error record.

This path is why the canonical boundary is a separate method rather than a change to `apply()`.
A caller that wants containment opts into it.

---

## Canonical call path

`run()` is the structured boundary.
In addition to calling the transform, it ensures that the caller receives a usable result triple for every outcome.

### Deadline wrapper

1. `run()` reads `properties["execution.timeout_seconds"]`. A missing key means no deadline.
2. A value that is not a finite number greater than zero — including a bool, a string, or `inf` — returns immediately with a `RECOVERABLE` / `INVALID_INPUT` record at the `VALIDATE` stage, carrying the suggestion `execution.timeout_seconds must be a finite number greater than zero`.
3. With no deadline, `run()` calls the five stages inline on the caller's thread.
4. With a deadline, it submits them to a single-worker thread pool and waits. Expiry returns `TIMEOUT` / `OPERATOR_TIMEOUT` at the `EXECUTE` stage and cancels the future; the worker is not killed, so a transform that ignores cancellation keeps running until it finishes on its own.
5. The wrapper never retries. The legacy `properties["timeout"]` field stays observable in properties and does not set the deadline.

### Five stages

| Stage | What happens | Failure record |
|---|---|---|
| projection | the live attribute definitions are projected back into frozen `AttributeSpec` values | `FAILED` / `VALIDATION_FAILED` / `VALIDATE` |
| defaults | declared optional defaults are deep-copied into a copy of the call attributes, unless the spec sets `materialize_default=False` | `FAILED` / `DEFAULTS_FAILED` / `DEFAULTS` |
| validate | `_validate_input()` returns a `ValidationResult`. A raise is one outcome; a wrong return type and a false result with no usable reason share a second; an ordinary false result with a reason is the third | `FAILED` / `VALIDATION_FAILED`, `FAILED` / `VALIDATION_RESULT_INVALID`, or `RECOVERABLE` / `INVALID_INPUT` carrying the validator's reason as the suggestion |
| execute | `_execute()` returns `FunctionResult(output_data, output_attributes)` | `FAILED` / `EXECUTION_FAILED` / `EXECUTE`, or `RECOVERABLE` / `EXECUTION_FAILED` when the cause is a missing LLM extra |
| normalize | the bundle is checked, an all-empty bundle becomes `[[]]` with `is_empty=True`, and the output attributes are deep-copied into a fresh mapping | `FAILED` / `EXECUTION_RESULT_INVALID` / `NORMALIZE` |

Two details of that table do real work downstream.

A missing LLM extra is `RECOVERABLE` rather than `FAILED`, because the caller can fix it.
The runtime inspects the exception and its `__cause__` for a `ModuleNotFoundError` naming `litellm`, `diskcache`, or `jinja2`, and returns the message `LLM dependency is unavailable` with the suggestion `Install blue-data-ops[llm] on Python 3.12 or 3.13.`

Every error record carries the operator's own exact ID.
For a registered instance that is the pinned ID it was bound to; for a directly constructed instance it is `name@2.0.0`, the direct-call identity.

### Outcome operators

The 21 `@3.0.0` cards wrap the same five stages and add measurement around them.

1. Before calling the base `run()`, the outcome operator reads a monotonic clock and computes the input bundle's shallow shape: group count and row count per group.
2. `_validate_input()` rejects a value that is not a list of record groups with the reason `supply a list of record groups`, ahead of the attribute checks.
3. The base `run()` executes normally.
4. Afterwards, `elapsed_ms` and `input_shape` are attached to `ExecMeta.traces`, and `output_shape` is attached only when the call produced no errors.
5. Every measurement step is wrapped so that a failure to measure cannot fail the call. A missing measurement means unavailable, not zero.

The counts are computed rather than aliased, so a caller mutating the bundle afterwards does not change what the traces say.
Attaching `elapsed_ms` happens after the base `run()` returns, which keeps it outside any worker that timed out.

A raw `@2.0.0` card in the same pipeline leaves `traces` empty. That asymmetry is visible in a `PipelineRun` and is the clearest way to tell which card a node resolved.

### Output attributes

An outcome operator's `_execute()` returns a second value alongside the bundle, and that is where the per-call facts a caller would otherwise have to recompute live: `avg@3.0.0` reports `num_values_used`, `insert_table@3.0.0` reports `num_rows_insert` when every batch supplied a row count and omits it when one did not.
`run()` gives every call a fresh output-attributes mapping, so two calls never share one.

---

## Registry resolution and admission

### Building a registry

1. A factory reads every built-in's module-level `DISCOVERY` constant in one pre-pass and validates it against the closed vocabularies. An invalid spec fails there, so no partial catalog is ever registered.
2. For each entry in the catalog tuple, the factory constructs an instance and registers it at the version that view calls for. `active_registry()` walks an explicit name-and-version table; `versioned_registry()` registers `1.0.0` and `2.0.0` for every name and `3.0.0` for the 21 with an outcome class.
3. `register()` validates the name and the semver, rejects an already-registered ID, and binds the instance to that pinned identity.
4. When one instance is registered twice — the same class at two versions — the second registration cannot rebind it, so the registry wraps it in a version-bound delegate instead. The delegate shares the target's properties and attributes and forwards every hook through a context variable that makes `operator_id` report the pinned identity for the duration of the call. One implementation, two identities, no copy.
5. A built-in registration also records the pinned ID in a private provenance set on the registry instance, and the reviewed ones additionally record the exact card and operator objects.

### Resolving

1. `resolve(operator_id)` splits on `@` and requires a `MAJOR.MINOR.PATCH` remainder. A bare name, a path, or a malformed version is a `ResolveError` before any lookup.
2. A dictionary lookup returns the bound operator, or raises `ResolveError` naming the ID.
3. There is no fallback. `find_latest(name)` exists, lives in discovery, and returns a card rather than an operator.

### Admission

Resolution answers "does this ID exist here". Admission answers "may this card be planned with", and it is a different question with a different answer.

- `is_builtin_card(registry, card)` is true only when the registry's own card for that ID is the identical object and the ID sits in the provenance set. Identity alone is not enough, because `register()` accepts anything a caller hands it and an equal-looking custom card would otherwise pass.
- `is_reviewed_builtin_card(registry, card)` additionally requires the card and the resolved operator to still match the reviewed registration recorded at build time.
- Both are integrity controls for ordinary planner admission. They are not an isolation boundary against same-process code that reaches into private registry state.

---

## Discovery path

### Lexical

1. Caller calls `find(query, tags=...)`.
2. Each requested tag is stripped and case-folded. A token that is empty, contains any whitespace, or has no hyphen raises `DiscoveryError` instead of returning an empty match set.
3. Candidates are filtered by exact AND tag membership. `None` or `[]` means no filter.
4. A blank query with tags returns the tag-matching cards ordered by name ascending then version descending. A blank query without tags returns nothing.
5. A nonblank query scores each candidate case-insensitively: name 10, any tag 8, `when_to_invoke` 6, description 5, each field counted at most once. Only positive scores are kept, and ties order by name then descending version.
6. Shape validation does not check taxonomy membership. `domain-`, `-vector`, and `domain_-vector` are well-formed filters that match no built-in card.

### Embedding

1. `OperatorEmbeddingIndex.build(registry, embedder)` reads the embedder's `space_id`, snapshots the registry's cards, and renders each card into one document from its name, invocation guidance, description, and ordered tags.
2. All documents go to the embedder in a single batch. The returned vectors are validated for shape, dimension consistency, and finiteness; anything else raises `EmbeddingDiscoveryError("INVALID_RESULT")`.
3. The index records a fingerprint over the space ID, the card objects, and the document hashes.
4. `find(query, tags=...)` first re-checks continuity: same `space_id`, same card objects in the same order, same documents, same hashes, same fingerprint. Any difference raises `EmbeddingDiscoveryError("STALE_INDEX")` rather than answering from a snapshot the registry has moved past.
5. The query is embedded, tag-matching cards are ranked by cosine similarity, and every match is returned. There is no threshold and no limit; the caller truncates.

A planner holding an index checks that `index.registry is registry` at construction and raises `EmbeddingDiscoveryError("BACKEND_MISMATCH")` otherwise, so an index built over a different registry cannot feed discovery for this one.

---

## Pipeline execution path

### Preflight

`preflight()` and `execute()` share one preparation step, so a graph that preflights clean is a graph that will reach its first operator.

1. Read the `nodes` record. An empty or non-mapping value is a `PipelineError`.
2. Confirm the declared input and output IDs exist, and that exactly one node carries each of those types.
3. Validate every node record: a matching `id` field, a supported type, list-valued `prev` and `next`, string members, no duplicates, no dangling references, and reciprocity in both directions.
4. Topologically sort the nodes. A cycle is a `PipelineError`.
5. Confirm every node lies on a path from the declared input and on a path to the declared output, by walking forward from the input and backward from the output.
6. For each operator node in topological order: reject a node whose status is already executing, executed, or failed; read its operator entity; require a string `operator_id`, a mapping `attributes`, and a mapping `properties`; resolve the pinned ID against the executor's registry; deep-copy the attributes.
7. Layer ordinary properties from stored plan to caller invocation to node entity, preserving the
   existing invocation-over-plan behavior for execution seams. For the LLM aliases, layer caller
   invocation, stored plan, then node entity so stored model and effort values override invocation
   defaults and the node's own LLM settings win over both.

`preflight()` returns the node order and the resolved operator IDs, having run nothing.

### Execution

1. Deep-copy the caller's input bundle and write it onto the declared input node, marking it executed.
2. For each node in topological order, skipping the input and output nodes: gather the predecessors' values into one bundle by extending in predecessor order, mark the node executing, and call `run()`.
3. An exception escaping `run()` — which the boundary is built to prevent — is still caught here and turned into a synthetic `FAILED` / `EXECUTION_FAILED` record, so the executor's own contract holds even if an operator's does not.
4. Record a `NodeRun` carrying the node ID, operator ID, status, output data, output attributes, and execution metadata. Write the output onto the node and set its status.
5. On the first node whose metadata carries errors: mark every unfinished node failed, and return a `PipelineRun` with `output_data` of `[[]]`, the node runs so far, and `failed_node_id` set. Downstream nodes do not run.
6. On success, aggregate the terminal node's output onto the declared output node and return a `PipelineRun` with `failed_node_id` of `None`.

Execution mutates node values and statuses on the plan it was given.
A caller that needs the original record untouched round-trips a copy through `DataPipeline.from_dict(plan.to_dict())`, which is what `PipelinePlanner.execute()` does internally.

The split between raising and returning is consistent: an unusable graph or an unusable input bundle raises `PipelineError`, and an operator failure after preflight is returned inside the run.

---

## Planning path

`plan()` runs seven stages and re-checks its inputs between them, because several of those stages hand an object to caller-supplied code and then keep using it.

### Stage order

1. **Validate the request.** Every field is re-checked against its expected exact type, not trusted from construction — a frozen dataclass still yields to `object.__setattr__`, and the scope decides which collection gets read and which addresses the compiler will accept. Attributes must be portable JSON data: finite floats, string keys, no cycles, depth under 64.
2. **Anchor the scope.** An immutable copy of the request's `DataScope` is taken once and re-compared after every step that could have let caller code mutate the original. A mismatch is `DATA_CONTEXT_SCOPE_MISMATCH`.
3. **Validate an explicit allowlist**, when one is present. Each ID must be pinned at a supported version, registered, name- and version-consistent with its card, resolve to itself, and — when it is a built-in — still match its reviewed registration. A `@3.0.0` ID must be a built-in.
4. **Discover.** Without an allowlist, the planner first validates the exact package active policy: all 33 IDs present, reviewed, not deprecated, and resolving to themselves. Built-in cards outside that policy are then skipped during discovery. Deprecated cards are skipped. Every card that survives is resolved and checked to resolve to its own ID.
5. **Capture admission.** Every discovered card is resolved once more, and the card object, the operator object, the ID, name, version, and lifecycle flag are snapshotted. Two separate `DiscoverySnapshot` copies are built from that snapshot — one for the generator, one retained for the result — so the generator and the caller's result are never the same object.
6. **Collect data context**, when the request carries a scope. Covered below.
7. **Generate, select, compile, preflight.** Covered below.

Between stage 6 and stage 7 the request is validated again and the scope anchor re-compared, because the generator has by then run caller code.

### Generation

1. The planner calls `generator.generate(request, discovery, data_context)`.
2. A `PlanningError` from the generator surfaces as it is. Anything else becomes `GENERATION_FAILED`.
3. The return value must be a `Sequence` and must not be a string or bytes. The planner takes at most `max_candidates + 1` items from it, so an unbounded iterator cannot run away; one item over the limit is `CANDIDATE_LIMIT_EXCEEDED`.
4. Every candidate is normalized: exact `PlanDraft` type, exact `PlanStep` types, string step IDs and operator IDs, tuple dependencies, and portable attributes. The attributes are deep-copied, so the drafts the planner goes on to use are its own.

`RulePlanGenerator` evaluates its rules in order and keeps the drafts they return.
A `RulePlanTemplate` is stricter than a rule: for each slot it requires discovery to have returned exactly one card with that operator name, and it compares that card's ID, name, version, and full ordered tag tuple against what the template expects.
A template that no longer matches the catalog refuses to build rather than planning against a card it does not recognize.

### Selection

1. Candidates are normalized again before the selector sees them, under selection-stage error codes.
2. `RequireSinglePlan` raises `NO_CANDIDATES` for an empty sequence and `AMBIGUOUS_CANDIDATES` for more than one. A caller wanting a different policy injects its own selector.
3. The selected draft is normalized once more on the way back, because the selector is caller code.

### Compilation

The compiler re-derives everything from the live registry. The admission snapshot from stage 5 is the reference it checks against, not a fact it trusts.

1. Reject an empty step list, a non-`PlanStep` member, more steps than `max_steps`, or more nodes than `max_nodes`.
2. Require nonempty unique step IDs.
3. For each step: require a pinned supported operator ID; require allowlist membership when an allowlist exists; require the ID to have been discovered; require exactly one matching admitted entry.
4. Then re-read the live registry for that ID and require all of it to line up: the current card is the identical object the admission snapshot captured, the name and version match, the card is not deprecated, the resolved operator is the identical object, it resolves to its own ID, a built-in card still matches its reviewed registration, and a `@3.0.0` ID is a built-in.
5. An `nl2sql` step must name the request's own `source`, `database`, and `collection` in its attributes. This stops a draft from collecting schema context for one collection and querying another. It is an address-consistency check on the step's attributes, not table authorization — the generated SQL may still read tables outside `DataScope.entities`.
6. Validate dependencies: no duplicates, every reference a known step. Topologically sort. Require exactly one root and exactly one terminal step, and check the edge limit.
7. Build the pipeline: define the input node, define one operator node per step with deep-copied attributes, connect dependencies — or the input node for a root step — define the output node, connect the terminal step to it, and set the declared input and output.

### Preflight and result

1. `PipelineExecutor.preflight()` runs on the compiled pipeline. A `PipelineError` becomes `PREFLIGHT_FAILED` with the executor's own message.
2. The scope anchor is compared one last time.
3. The request is deep-copied for the result. A request that cannot be copied is `RESULT_COPY_FAILED`.
4. `PlanningResult` carries the request copy, the retained discovery snapshot, the candidates, the selected draft, the compiled pipeline, the preflight result, and the retained data context.

`run(request, input_data)` calls `plan()` and then `execute()`, and `execute(planning, input_data)` re-materializes the pipeline from its serialized form first, so a prior planning result can be executed more than once.

---

## Data context path

A snapshot is advisory schema context for a plan generator. The payload shape is closed, so there is no field an unexpected value could travel in.

### Collection

1. No scope on the request means no provider call at all, whether or not a provider was configured.
2. A scope with no provider is `DATA_CONTEXT_REQUIRED`.
3. The planner hands the provider a fresh `DataScope` copy and keeps a second copy that never leaves the frame. The provider is free to mutate what it was given; the comparison is against the copy it never saw.
4. Trust follows the code path rather than the object's type. When the provider is exactly a `RegistryDataContextProvider`, the planner calls the class implementation directly, so an instance-level `collect` shadow is never invoked. A `PlanningError` out of that branch was raised by package code and surfaces with its own specific record — a limit violation stays recoverable, an unregistered entity stays actionable. A foreign provider's failure becomes one generic record instead.
5. The returned value must be exactly a `DataContextSnapshot`. A subclass could have overridden `to_dict()` or skipped the validating constructor, so it carries none of the guarantees the planner is about to rely on.
6. `detached_snapshots()` thaws the document into package-owned containers and rebuilds it twice through `DataScope` and `DataContextSnapshot` construction, which revalidates from scratch. Nothing the caller supplied survives into either copy, so a shadowed `to_dict`, a replacement proxy, or a field swapped in afterwards has nothing left to act on.
7. The rebuilt scope is compared against the copy from step 3. Only now is that comparison safe, because both sides are package-owned objects holding exact strings.

### What the registry provider reads

1. Validate the scope's field values, not just its class. An exact `DataScope` whose `source` was replaced with a `str` subclass after construction is about to be sent to the registry and serialized.
2. Pin the registry and the limits into local package-owned state. Those are the only two instance reads in the whole path; nothing below dispatches through an attribute a caller can set.
3. `get_source_properties(source)` for the connection protocol. Absent or malformed means `null`, not a failure.
4. `list_collection_entities(source, database, collection)` for the entity records. A duplicate or nameless record is malformed.
5. Select the entities: an explicit projection must be fully registered, and a whole-collection request either fits the entity limit or fails. There is no separate paging call, so a truncated projection would be indistinguishable from a small collection.
6. `list_entity_attributes(...)` per selected entity, accumulating against both the per-entity and the total attribute limits.
7. Construct the snapshot. Construction deep-copies and recursively freezes the payload, checks the whole document against the bounds the payload itself declares, and measures the canonical serialization against the byte limit. A snapshot that exists is one that already satisfies every limit it reports.

The provider reads entity and attribute records directly rather than through `build_schema_for_nl()`, because that helper substitutes `TEXT` for an absent declared type and so cannot express "the registry does not know this type". Here an unknown type is `null`.
Relations are not read at all: the producer may leave their endpoints empty, and a relation projection would not mean what a planner would take it to mean.
Every data-context message is a fixed string. Entity names, descriptions, declared types, and connection properties are never interpolated into a record, so no record can carry schema content out of the boundary.

---

## Plan generation through a provider

`OpenAIPlanGenerator` is the one place in the package that imports the OpenAI SDK, and the order of its checks is the design.

1. **Disclosure gate first.** A `DataContextSnapshot` present without `send_data_context=True` raises `DATA_CONTEXT_DISCLOSURE_REQUIRED` here — before the optional import, before the client, before any serialization. A snapshot the caller did not authorize sending never gets as far as being encoded into a request body.
2. **Authorize the catalog.** Each discovered card must be in the allowlist, must still match its reviewed built-in registration, must pin a supported version, and must resolve exactly. Provenance failure and an empty result are different outcomes: the first says the registry cannot be vouched for, the second says the wiring is fine and discovery found nothing authorized.
3. **Default-deny by lifecycle and by effect.** A deprecated card is skipped, and so is one carrying `produces-side-effect`. A write card is never offered to the model, and the decoder rejects one anyway.
4. **Read the live declarations now**, not at decode time. A malformed attribute declaration has to fail before the provider request, so the check sits on this side of the call.
5. **Build the payload.** Goal, labels, limits, the authorized operator metadata in discovery order rather than allowlist order, the caller's attributes, and the snapshot when disclosure was authorized. The document is canonically encoded and checked against a byte bound.
6. **Resolve the client.** An injected client is used as-is. Otherwise `openai` is imported and `openai.OpenAI()` constructed at first use. A `ModuleNotFoundError` for that module maps to `GENERATOR_DEPENDENCY_MISSING` and nothing wider, so a different problem is not mislabelled as a missing install.
7. **One request.** Non-streaming, `store=False`, SDK retries disabled, with the packaged response-format document attached. Defaults are `timeout_seconds=60.0`, `max_output_tokens=4096`, and one candidate.
8. **Decode.** The single output text is bounded, parsed with duplicate JSON keys rejected, validated against the same schema member the provider was given, and every step's operator ID re-checked against the authorized set. Caller-supplied attributes are constraints the model cannot drop or overwrite.

Provider failures map onto codes by exception class and HTTP status: `GENERATOR_TIMEOUT`, `GENERATOR_RATE_LIMITED`, `GENERATOR_UNAVAILABLE`, `GENERATOR_REQUEST_REJECTED`, `GENERATOR_REFUSED`, `GENERATOR_RESPONSE_INVALID`.
No exception text, response body, request payload, credential, or provider identifier crosses into a record, so the record shape does not change when the SDK's messages do.

The outbound schema uses `minItems` and `maxItems`, which the fine-tuned structured-output subset does not support, so a model name starting with `ft:` is rejected at construction rather than by the provider.

---

## Operator skill load path

Every entry point runs the same binding and index checks, in the same order, and the ordering is itself the contract.

1. **Validate the level.** Only 2, 3, and 4 exist; anything else is `NOT_AVAILABLE`.
2. **Validate the binding.** The operator ID must match the pinned pattern, and its name must not be `.` or `..`. The registry must be exactly an `OperatorRegistry`, or the result is `TRUST_REQUIRED`. The card must exist and must be a package-owned built-in — a caller-created registration is `TRUST_REQUIRED`, not `NOT_AVAILABLE`. The card's ID, name, and version and the operator's bound ID and name must all agree, or the result is `BINDING_MISMATCH`.
3. **Read the index.** `_index.json` is read under a 4 KiB bound, decoded with duplicate keys rejected, checked for JSON depth at most 4, checked for an exact key set and the expected format string. Every key must be a pinned ID, and every value must be exactly `<name>/<version>/manifest.json`.
4. **Find the package.** An ID absent from the index is `NOT_AVAILABLE`. One malformed row invalidates the whole index rather than being skipped, including operators whose own rows are valid.
5. **Read the manifest** under the same 4 KiB bound, with an exact key set, the expected format, and an `operator_id` matching the request. Each declared resource kind must be one of the five known kinds, its path must be exactly that kind's filename, and its digest must be 64 lowercase hex characters. A `guide` entry is required.
6. **Read each required file** under a 16 KiB bound. The reader refuses a symlinked root, refuses a symlink at any path segment, rejects absolute and traversing relative paths, resolves both the root and the target strictly, confirms containment, and confirms the target is a regular file.
7. **Verify the digest.** The file's SHA-256 is compared against the manifest value before the bytes are decoded. A mismatch is `RESOURCE_INVALID`, and so is a UTF-8 decode failure.
8. **Snapshot the schema.** The operator's live attribute projection is refreshed, type-checked, and deep-copied, so the returned view does not alias operator state.
9. **Return the view**: the card, the requested level, the loaded kinds, the fixed input and output shapes, and the text.

A malformed operator ID is reported as `INVALID_OPERATOR_ID` before the index is read at all, so a bad ID is never reported as a manifest problem.
There is no cache, so calling `describe()` and then `load()` rereads the index, and a package that changed between the two calls fails the second.
Nothing on this path invokes the operator, and nothing adds the returned text to planner or provider input.

---

## Data registry seam path

The four registry-backed operators, plus `nl2sql` and `nl2bn`, reach the caller's data through one facade.

1. The operator calls `resolve_registry(properties)`.
2. An injected `RegistrySeam` is returned as-is. An injected raw `blue-data` `DataRegistry` is wrapped, because its create methods do not accept the compatibility arguments the seam exposes. An invalid injected value falls through rather than failing.
3. With no injection, `platform.name` and `data_registry.name` together select a provider-built registry. The default provider caches one in-memory registry per name pair with eager index rebuilds. Neither key present returns `None`, and the operator reports the unavailable registry through its own error path.
4. The operator calls seam methods. The seam forwards to the wrapped registry by keyword, which is what prevents a positional swap where the two argument orders differ, and consumes the arguments the delegate has no counterpart for.
5. A create call that requested immediate indexing against a registry whose instance policy disables rebuilds gets an explicit `build_index()` afterwards, so the requested behavior is preserved rather than silently dropped.
6. Search results come back in one of two shapes with opposite score polarity. The seam normalizes both to one flat record with an inverted score — lower is better — derives the ID from the delegate's own hierarchy-node convention, and preserves list order, which is already consumer-ascending.

A write goes further down than the seam: `insert_table` connects the source, opens a connection, runs one `executemany` per batch, commits, reads the cursor's row count, and disconnects.
Row counts are per-batch, and a batch whose cursor does not report one drops the output attribute rather than reporting a wrong total.

---

## LLM request path

1. An operator calls `resolve_llm_client(properties, provider)`. An injected client under `properties["llm_client"]` wins; a provider is asked next; otherwise a fresh client is constructed. The default lifetime is one client per invocation, never a module-level singleton.
2. `execute_api_call(input, properties, additional_data)` merges the client's own properties under the call's.
3. Templating builds the request message. The service prefix — from `service_prefix`, or the client's own name — selects which properties become request fields. A trusted `input_template` receives one dollar-placeholder pass, with inserted data kept literal; an `input_json` shell is filled at the configured context path, and the result lands under `input_field`.
4. Substitution merges the property, parameter, and additional-data sources and raises a `TypeError` on a duplicate key rather than giving one source implicit precedence.
5. Call kwargs are assembled. Only the documented `llm.*` override keys are accepted, and an unknown one is an `LLMError` with code `bad_override`. The four control keys are consumed here and never forwarded. Two dispatch-only fields, `api` and `service_url`, are stripped after every merge, because they are operator defaults rather than caller intent. A field on any namespace that would set a provider endpoint or a credential, or that would substitute the provider's answer, is refused with code `reserved_field` before the cache key is built. A missing model is an `LLMError` with code `no_model`.
6. With caching enabled, the cache key is the canonically serialized kwargs. A hit records usage with zero tokens and zero cost and returns immediately. The cache is keyed per directory, so a per-call `cache_dir` override selects its own isolated cache.
7. Rate limiting sleeps under a lock to hold the configured minimum interval between calls.
8. The provider call runs through LiteLLM under `tenacity`, retrying a retryable `LLMError` up to
   three attempts with exponential backoff and re-raising the last one. A LiteLLM parameter
   rejection or a provider 400 with structured code `unsupported_parameter` is non-retryable.
9. The response is materialized into a payload dictionary, cached when caching is on, and recorded as one `UsageRecord` — model, token counts, cost, end-to-end latency including retries, and the cache-hit flag.
10. `extract_output(payload, merged)` reads the configured output path with JSONPath, applies the configured strip and transformation steps, applies an output template, and casts the result.

Transport and provider exceptions and malformed responses are wrapped as `LLMError`.
Templating errors stay raw, because they happen before the provider boundary.
The async path is the same flow with a bounded semaphore around the provider call.

Cost reporting on `nl2llm@3.0.0` is deliberately narrow: a finite nonnegative USD `cost` with `cost_basis="estimated"` appears only after exactly one priced provider attempt.
A proven local cache hit reports `0.0`; provider-side prompt caching still counts as an attempt.
Retries, failures, unknown prices, and injected clients omit the cost fields rather than guessing.

---

## MCP tool call path

### Construction

1. `create_server()` calls `freeze_deployment()`, which defaults to `versioned_registry()` and `ACTIVE_OPERATOR_IDS`.
2. Each requested ID is checked: the card exists, the card's own ID matches the request, name and version agree, the version is `2.0.0` or `3.0.0`, and the operator resolves to itself.
3. A package-owned ID must additionally be a same-registry built-in whose resolved implementation class matches a reference `versioned_registry()` build. A card that is a built-in or reuses a supported built-in name but is not in the supported set is rejected outright. A caller-created card is accepted at `2.0.0` only.
4. Duplicate logical names in the selection fail rather than one winning. The snapshot is sorted by name.
5. `FastMCP` is constructed with a loopback default host, `streamable_http_path="/mcp"`, `json_response=False`, and `stateless_http=False` — a stateful session over streamable HTTP.
6. For each binding, `add_tool()` registers a handler named for the logical operator, with a description composing the deprecation sentence when applicable, the card's invocation guidance, and the card's description, and with `_meta` carrying the exact `operator_id`, version, and ordered tags.

The handler's signature is synthesized rather than written: `input_data` typed as a list of record groups, `attributes` annotated with a JSON schema built from the operator's live declarations, and `properties` optional. Each attribute keeps its description, and a default is published only for an optional attribute that both declares one and materializes it. Published defaults are deep copies, never aliases of core state.

### Invocation

1. The client calls the tool with `input_data` and optionally `attributes` and `properties`. A missing `attributes` becomes an empty mapping.
2. The handler moves `operator.run(...)` onto a worker thread with `asyncio.to_thread`, so a synchronous transform does not block the event loop.
3. The result triple is projected once: output data, output attributes, and the execution metadata with its error records flattened to plain values.
4. The projection is JSON-converted in a single pass with `default=str` for exotic leaves and `allow_nan=False`. A non-finite float is an adapter error, becomes a tool error at the handler boundary, and never becomes a synthetic operator `ErrorRecord`.
5. The payload is validated against the `RunResult` model and returned as structured content.

`isError` stays false for a recoverable, failed, timed-out, or successful-empty operator outcome; the detail is in `exec_meta`.
It becomes true for an unknown tool, malformed top-level arguments, or a projection or encoding failure — the things that are wrong with the call rather than with the data.

---

## Where failures land

One table, because the split is the part callers most often get wrong.

| Failure | Reported as | Where to read it |
|---|---|---|
| invalid operator attributes | error record | `exec_meta.errors`, `RECOVERABLE` / `INVALID_INPUT` |
| transform raised | error record | `exec_meta.errors`, `FAILED` / `EXECUTION_FAILED` |
| missing LLM extra | error record | `exec_meta.errors`, `RECOVERABLE` / `EXECUTION_FAILED`, with an install suggestion |
| wrapper deadline expired | error record | `exec_meta.errors`, `TIMEOUT` / `OPERATOR_TIMEOUT` |
| successful empty result | not a failure | `output_data == [[]]`, `is_empty=True`, no errors |
| unknown or malformed operator ID | raised | `ResolveError` |
| unusable pipeline graph or input | raised | `PipelineError` |
| operator failure inside a pipeline | returned | `PipelineRun.failed_node_id` and that `NodeRun.exec_meta` |
| any planning stage | raised | `PlanningError.record` |
| LLM transport or provider failure | raised inside the client, contained by `run()` | `LLMError`, then an `EXECUTION_FAILED` record |
| skill index, manifest, or digest problem | raised | `OperatorSkillLoadError.code` |
| embedding index problem | raised | `EmbeddingDiscoveryError.reason` |
| MCP argument or encoding problem | tool error | `isError` true, no operator record |

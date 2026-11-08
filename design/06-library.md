# blue-data-ops — Library

The classes and functions a contributor needs to find, one section per module.
This is the internal map; the user-facing surface is [`../docs/api-reference.md`](../docs/api-reference.md), and the per-operator metadata lives in the generated [`../lib/OPERATORS.md`](../lib/OPERATORS.md).

> External dependency: `blue-data` supplies `DataRegistry` and `DataSource`, both imported in `data/` only. Everything else in the tables below is defined in this repository.

---

## `blue_data_ops` — the top-level package

The import surface a caller gets from `import blue_data_ops`.
It re-exports the operator classes reachable from the package root, the base `Operator` and `Tool`, the result and error types, the registry seam, and the `utils` module.

| Export group | Names |
|---|---|
| operator classes | `ArgmaxOperator`, `ArgminOperator`, `AvgOperator`, `ClassifyOperator`, `ClusterOperator`, `CreateDatabaseOperator`, `CreateTableOperator`, `DataDiscoverOperator`, `DeleteOperator`, `InsertOperator`, `InsertTableOperator`, `IntersectOperator`, `JoinOperator`, `MaxOperator`, `MinOperator`, `NL2BNOperator`, `NL2LLMOperator`, `NL2SQLOperator`, `NormalizeTextOperator`, `ProjectOperator`, `SegmentTextOperator`, `SelectOperator`, `SemanticExtractOperator`, `SemanticFilterOperator`, `SemanticJoinOperator`, `SemanticProjectOperator`, `SemanticTransformOperator`, `SumOperator`, `UnionOperator`, `VectorEmbedOperator`, `VectorSearchOperator`, `VectorSimilarityOperator` |
| bases | `Operator`, `Tool` |
| results and errors | `FunctionResult`, `ExecMeta`, `ErrorRecord`, `ErrorCategory`, `ErrorCode`, `ErrorStage`, `ValidationResult`, `ABSENT` |
| registry seam | `BlueDataRegistryProvider`, `DataRegistryProvider`, `RegistrySeam`, `resolve_registry` |
| compatibility | `BlueDataOpsDeprecationWarning` |
| submodule | `utils` |

`SklearnEstimator` and `OperatorDiscoverOperator` are exported from `blue_data_ops.operators` rather than the package root.
`blue_data_ops.operators` is the fuller surface and is where the registry factories, `OperatorCard`, `OperatorRegistry`, the embedding index, and the type aliases live.

---

## `operators/types.py` — the data and error vocabulary

`operators/types.py` defines the data and error types used at the operator boundary; it contains no behavior.
The type aliases are plain aliases, so a caller never has to construct a wrapper to call an operator.

| Name | Definition | Notes |
|---|---|---|
| `Record` | `dict[str, Any]` | one JSON-like object |
| `Data` | `list[Record]` | one record group |
| `DataBundle` | `list[Data]` | what every operator consumes and produces |
| `Attributes` | `dict[str, Any]` | per-call operator arguments |
| `Properties` | `dict[str, Any]` | per-call execution settings |
| `ABSENT` | a bare sentinel object | distinguishes "no default declared" from "default is `None`" |

| Type | Kind | Fields |
|---|---|---|
| `FunctionResult` | `NamedTuple` | `output_data`, `output_attributes` |
| `ValidationResult` | `NamedTuple` | `ok`, `reason` |
| `ErrorRecord` | `NamedTuple` | `category`, `code`, `operator_id`, `stage`, `message`, `retryable`, `suggestion` |
| `ExecMeta` | `NamedTuple` | `is_empty`, `errors`, `logs`, `traces` |

| Enum | Members |
|---|---|
| `ErrorCategory` | `RECOVERABLE`, `FAILED`, `TIMEOUT` |
| `ErrorStage` | `DEFAULTS`, `VALIDATE`, `EXECUTE`, `NORMALIZE`, `REFINE` |
| `ErrorCode` | `DEFAULTS_FAILED`, `INVALID_INPUT`, `VALIDATION_FAILED`, `VALIDATION_RESULT_INVALID`, `EXECUTION_FAILED`, `EXECUTION_RESULT_INVALID`, `REFINEMENT_FAILED`, `REFINEMENT_RESULT_INVALID`, `OPERATOR_TIMEOUT` |

All three are `str`-valued, so a member compares equal to its own name and serializes without a converter.
`REFINE`, `REFINEMENT_FAILED`, and `REFINEMENT_RESULT_INVALID` are retained vocabulary from the removed refinement API: nothing in the package emits them, and they stay because a stored 2.x record may still contain one.

### `AttributeSpec`

A frozen dataclass with a hand-written `__init__`, declaring one operator attribute.

```text
AttributeSpec(
    type: str,
    description: str = "",
    required: bool = False,
    default: Any = ABSENT,
    materialize_default: bool = True,
)
```

| Field | Meaning |
|---|---|
| `type` | a Blue type string, parsed by `utils.string_to_python_type` |
| `description` | published in the signature and in the MCP attribute schema |
| `required` | whether validation fails when the attribute is absent |
| `default` | the declared default, stored as `None` when none was declared |
| `has_default` | derived: true when `default` was not `ABSENT` |
| `materialize_default` | whether `run()` writes the default into the call attributes |

The split between `default` and `has_default` is why `ABSENT` exists: an attribute defaulting to `None` and an attribute with no default are different, and a single field cannot say which it is.
`materialize_default=False` declares a default for documentation without injecting it into the call — the operator reads it itself, from its own logic, at the point where it matters.
`materialize_default` is excluded from equality comparison and from the repr.

`OperatorError` and `OperatorValidationError` are the exception bases, both defined here.

---

## `operators/operator.py` — the call boundary

The abstract base every operator inherits, its five-stage canonical boundary, and the module-level defaults that make a bodyless operator well-defined.

### `Operator(Tool, ABC)`

Class-level declarations, read by the runtime and never mutated on the class.

| Class attribute | Purpose |
|---|---|
| `name` | the logical operator name and registry key; the MCP adapter prefixes it with `ops_` when registering a tool |
| `description` | the card description and part of the MCP tool description |
| `attributes` | the frozen `dict[str, AttributeSpec]` declaration |
| `PROPERTIES` | class-level property defaults, deep-copied onto each instance |

| Method | Signature | Role |
|---|---|---|
| `apply` | `(input_data, attributes, properties=None) -> DataBundle` | abstract. The transform. Called directly on the raw path |
| `validate` | `(input_data, attributes, properties=None) -> bool` | the raw boolean validator. Total in the base implementation |
| `invoke` | `(input_data, attributes, properties=None) -> DataBundle \| None` | validate then apply; `None` when validation is false |
| `run` | `(input_data, attributes, properties=None) -> tuple[DataBundle, Attributes, ExecMeta]` | the canonical boundary, with the optional deadline wrapper |
| `explain` | `(output, input_data, attributes) -> dict[str, Any]` | input and output statistics for a completed transform |
| `operator_id` | property `-> str` | the pinned registry identity, or `f"{name}@2.0.0"` for a direct call |
| `_execute` | `(input_data, attributes, properties=None) -> FunctionResult` | the override point for an operator that returns output attributes |
| `_validate_input` | `(input_data, attributes, properties=None) -> ValidationResult` | the override point for structured validation with a reason |
| `_refresh_attribute_projection` | `() -> dict[str, AttributeSpec]` | re-derives the frozen specs from the live definitions |
| `_bind_operator_id` | `(operator_id) -> None` | binds an unbound instance to one pinned identity; raises when already bound elsewhere |

The Blue metadata accessors sit alongside those: `get_attributes`, `update_attributes`, `get_attribute`, `get_attribute_type`, `get_attribute_description`, `set_attribute_description`, `set_attribute_required`, `set_attribute_hidden`, `is_attribute_required`, `is_attribute_hidden`, `get_hyperparameters`, `update_hyperparameters`, and the two class methods `is_operator` and `get_tool_type`.
`is_required(name)` and `default_of(name)` read the frozen projection instead of the live view and return `None` rather than raising when the attribute is unknown.

Every setter that changes an attribute definition regenerates the signature and refreshes the projection, so the live view, the signature, and the frozen specs never drift apart.

### Module-level defaults

| Function | Role |
|---|---|
| `apply_defaults(attributes, schema)` | copies the call attributes and materializes declared optional defaults |
| `default_operator_function(input_data, attributes, properties=None)` | the raw default output for an operator with no body: `[]` |
| `default_attributes_validator(attributes, properties=None)` | validates values against the live Blue definitions, honoring `validation_error_handling` |
| `default_operator_validator(input_data, attributes, properties=None)` | the same, with exceptions contained to `False` |
| `default_operator_explainer(output, input_data, attributes)` | Blue's default statistics, including `transformation_ratio` |

### Instance properties

`_initialize_properties()` seeds the property mapping every operator starts from.

| Key | Default |
|---|---|
| `tool_type` | `"operator"` |
| `validate_input`, `validate_output` | `True` |
| `validation_error_handling` | `"fail"` |
| `max_records` | `None` |
| `timeout` | `300` |
| `error_handling` | `"skip"` |
| `log_processing_stats` | `True` |
| `attributes` | the live definitions derived from the class declaration |
| `hyperparameters` | `{}` |

`properties["timeout"]` is retained Blue metadata and does not set a deadline.
The deadline key is `properties["execution.timeout_seconds"]`, read by `run()`.

### `_VersionBindingMixin` and `_VersionBoundOperator`

One implementation registered at two versions needs two identities without two instances.

`_VersionBoundOperator` wraps a target operator, holds its own `_registered_operator_id`, and shares the target's properties, attributes, name, and description by reference.
Each forwarded hook — `apply`, `validate`, `_validate_input`, `_execute`, `invoke`, `explain` — runs inside a context variable set to `(id(target), operator_id)`, so the target's own `operator_id` property reports the pinned identity for the duration of that call.
Error records raised deep inside a shared transform therefore name the version the caller actually asked for.

---

## `operators/registry.py` — identity, discovery, admission

The registry, the card, the three factories, and the provenance predicates the planner and the MCP adapter check against.

### `OperatorCard`

A frozen dataclass. Discovery-facing metadata whose `operator_id` is always pinned.

| Field | Default | Meaning |
|---|---|---|
| `operator_id` | — | `"<name>@<MAJOR.MINOR.PATCH>"` |
| `name` | — | the logical name |
| `version` | — | the semver string |
| `description` | — | copied from the operator class |
| `tags` | `()` | ordered namespaced tags |
| `when_to_invoke` | `""` | invocation guidance |
| `deprecated` | `False` | lifecycle flag |

### `OperatorRegistry`

| Method | Signature | Behavior |
|---|---|---|
| `register` | `(operator, version, tags=(), *, when_to_invoke="", deprecated=False) -> OperatorCard` | validates the name and semver, rejects a duplicate ID, binds or wraps the instance, returns the pinned card |
| `resolve` | `(operator_id) -> Operator` | pinned-only. `ResolveError` on a malformed reference or a miss |
| `get_card` | `(operator_id) -> OperatorCard \| None` | pinned lookup; not-found is `None` |
| `find` | `(query, tags=None) -> list[OperatorCard]` | exact AND tag filter, then case-insensitive text scoring |
| `find_latest` | `(name) -> OperatorCard \| None` | the highest-version card for an exact name |
| `list_cards` | `() -> list[OperatorCard]` | every card, name ascending then version descending |

Registration is immutable: no overwrite, no deregister.
`resolve()` requires a pinned ID and never selects a latest version.
`find()` and `find_latest()` accept looser queries but return pinned cards.

Text scoring weights are fixed: name 10, any tag 8, `when_to_invoke` 6, description 5, each field at most once.
Positive scores only; ties order by name then descending version.

The registry keeps three private tables beyond its cards and operators: the set of built-in pinned IDs, and the reviewed operator and card objects for planning authority.
Built-in origin is a set on the registry rather than a field on the card, so nothing serializes it, no caller can pass it, and no planning record exports it.

### Factories

| Function | Signature | Result |
|---|---|---|
| `default_registry` | `(**versions) -> OperatorRegistry` | 33 raw cards at `1.0.0`, with per-name semver overrides; unknown keys ignored |
| `active_registry` | `() -> OperatorRegistry` | the 33 reviewed active cards — 12 at `@2.0.0`, 20 at `@3.0.0`, and `nl2sql@4.0.0` |
| `versioned_registry` | `() -> OperatorRegistry` | 88 cards: 33 at `@1.0.0`, 33 at `@2.0.0`, 21 at `@3.0.0`, and `nl2sql@4.0.0` |

All three validate every built-in's `DISCOVERY` record in a pre-pass before registering anything, so an invalid spec fails fast and no partial catalog exists.
`default_registry()` registers raw cards with empty `tags` and `when_to_invoke`; only the other two attach the validated metadata and mark the registration reviewed.
For the 21 outcome-enabled names, `default_registry()` selects the outcome implementation for an exact `"3.0.0"` override; `nl2sql` also accepts its declared `"4.0.0"` contract.

### Admission predicates and helpers

| Function | Signature | Role |
|---|---|---|
| `is_builtin_card` | `(registry, card) -> bool` | the registry's card for that ID is the identical object **and** the ID is in the provenance set |
| `is_reviewed_builtin_card` | `(registry, card) -> bool` | additionally, the card and resolved operator still match the reviewed registration |
| `upgrade_legacy_operator_id` | `(reference, registry, *, target_version, aliases=None) -> str` | converts a bare name, alias, or `/server/<server>/(operator\|tool)/<name>` path into a registered pinned ID |
| `_builtin_operator_classes` | `() -> tuple[type[Operator], ...]` | the explicit, name-ordered catalog tuple every factory builds from |
| `_outcome_operator_classes` | `() -> dict[str, type[Operator]]` | the 21 outcome classes keyed by logical name |

`is_builtin_card` requires both object identity and package provenance.
Identity ties the card to this registry instance, which the OpenAI generator later uses to read live declarations.
Provenance confirms that a package factory registered the card; public `register()` also accepts caller-defined cards.

`upgrade_legacy_operator_id` raises `UpgradeError` on a missing, malformed, ambiguous, or unregistered target.
A token that is both a registered bare name and an alias key is ambiguous and fails; alias precedence is not granted.
Neither `resolve()` nor `DataPipeline.from_dict()` calls it — upgrading is always an explicit caller choice.

The catalog tuple is imported lazily inside `_builtin_operator_classes()`, which keeps this module out of the operator import cycle.

---

## `operators/_discovery.py` — the closed tag vocabulary

The six-namespace tag model and its validator.
Built-in specs are checked against closed vocabularies; caller registrations never pass through here and keep their permissive behavior.

| Name | Role |
|---|---|
| `DiscoverySpec` | frozen dataclass: `when_to_invoke` plus ordered `tags`. One per built-in module, as a module-level `DISCOVERY` constant |
| `DiscoveryError` | `ValueError` subclass raised for a violation |
| `NAMESPACE_ORDER` | `("domain", "flow", "accepts", "produces", "capability", "requires")` |
| `REQUIRED_NAMESPACES` | the five that must be present; `requires` is optional |
| `SINGLE_VALUED` | `{"domain"}` |
| `namespace_of(tag)` | the text before the first hyphen |
| `validate_builtin_discovery(name, spec)` | the fail-fast validator |
| `normalize_filter_tag(token)` | strips and case-folds one filter token, rejecting a malformed one |

`validate_builtin_discovery` enforces nonempty invocation text; lowercase hyphenated unique tags in canonical namespace-then-lexicographic order; exactly one `domain-*`; the five required namespaces present; every `accepts`, `produces`, `requires`, and `capability` tag inside its closed set; and every `domain` and `flow` bare value admissible.

`normalize_filter_tag` rejects a token that is empty after stripping, contains any whitespace, or has no hyphen.
It does not check taxonomy membership or hyphen position, which is why `domain-`, `-vector`, and `domain_-vector` are well-formed filters that match no built-in card.
A malformed filter raises rather than silently matching nothing.

---

## `operators/_metadata.py` — the Blue metadata bridge

Converts between the frozen class declarations and the live Blue metadata view, delegating the shared implementations to `utils`.

| Function | Signature | Role |
|---|---|---|
| `definitions_from_specs` | `(specs) -> tuple[dict[str, dict[str, Any]], dict[str, bool]]` | per-instance live definitions plus the materialization flags |
| `project_specs` | `(definitions, materialize_defaults) -> dict[str, AttributeSpec]` | projects the live view back into frozen specs, type-checking every field |
| `enrich_attribute_signature` | `(signature, definitions) -> None` | attaches the live definitions to a parameter named `attributes` and converts each type to its MCP shape |
| `extract_signature` | `(function) -> dict[str, Any]` | the Blue-compatible MCP signature |
| `merge_metadata` | alias of `utils.merge_json` | jsonmerge's object merge |
| `type_string_to_mcp` | alias of `utils.convert_type_string_to_mcp` | type string to MCP JSON-schema shape |

`project_specs` raises `TypeError` rather than coercing, because a wrong live definition has to surface at the boundary rather than silently changing what an operator validates.
`_metadata_snapshot` falls back to a structural copy when `deepcopy` fails, so an unhashable or uncopyable default in a live definition does not break signature generation.

---

## `operators/embedding_discovery.py` — caller-supplied semantic discovery

An in-memory embedding snapshot bound to one registry and one embedder.

| Name | Role |
|---|---|
| `OperatorEmbedder` | a `Protocol`: a `space_id` property and a `__call__(texts) -> Sequence[Sequence[float]]` batch callable |
| `OperatorEmbeddingIndex` | the frozen snapshot. Constructed only through `build()`; `__init__` raises |
| `EmbeddingDiscoveryError` | subclasses both `DiscoveryError` and `OperatorError`, carrying a stable `reason` |

| Method | Signature | Behavior |
|---|---|---|
| `build` | `(registry, embedder) -> OperatorEmbeddingIndex` | classmethod. Snapshots the cards, renders one document each, embeds them in one batch, validates the vectors, records a fingerprint |
| `registry` | property `-> OperatorRegistry` | the registry this index is bound to |
| `find` | `(query, tags=None) -> list[OperatorCard]` | re-checks continuity, embeds the query, returns every tag-matching card in cosine order |

Reasons are a closed set: `BUILD_FAILED`, `QUERY_FAILED`, `INVALID_RESULT`, `STALE_INDEX`, `BACKEND_MISMATCH`, `MODE_UNAVAILABLE`, `INVALID_MODE`.

`find()` applies no threshold and no limit; the caller truncates.
Continuity is checked on every call against the space ID, the card objects, their order, the rendered documents, their hashes, and the fingerprint.
Any difference is `STALE_INDEX`, because answering from a snapshot the registry has moved past would be worse than failing.

---

## `operators/operator_discover_operator.py` — discovery as an operator

`OperatorDiscoverOperator` is an operator-shaped facade over registry discovery, for a caller that reaches operators through a uniform call surface.

Lexical search uses the registry's text scoring after exact tag filtering.
An approximate caller must pass the same explicit registry to the facade and to its index, supplied through `properties["discovery_backend"]`; a missing or mismatched index raises `EmbeddingDiscoveryError("BACKEND_MISMATCH")` with no fallback.
Hybrid search raises `MODE_UNAVAILABLE`, and requesting both modes raises `INVALID_MODE`.

It carries no `DISCOVERY` record, which is what keeps it out of the built-in card catalog and out of the MCP inventory.

---

## `operators/` — the operator implementations

One module per operator, each holding the class and a module-level `DISCOVERY` constant.

| Family | Modules |
|---|---|
| filter and shape | `select_operator`, `project_operator`, `delete_operator`, `insert_operator` |
| join and set | `join_operator`, `union_operator`, `intersect_operator` |
| aggregate | `argmax_operator`, `argmin_operator`, `max_operator`, `min_operator`, `avg_operator`, `sum_operator` |
| text | `normalize_text_operator`, `segment_text_operator` |
| machine learning | `classify_operator`, `cluster_operator`, `sklearn_estimator` |
| vector | `vector_embed_operator`, `vector_search_operator`, `vector_similarity_operator` |
| LLM | `nl2llm_operator`, `nl2sql_operator`, `nl2bn_operator`, `semantic_extract_operator`, `semantic_filter_operator`, `semantic_join_operator`, `semantic_project_operator`, `semantic_transform_operator` |
| registry-backed | `create_database_operator`, `create_table_operator`, `insert_table_operator`, `data_discover_operator` |

A typical module is short: the class declares `name`, `description`, and `attributes`, implements `_execute()` to return a `FunctionResult`, points `apply()` at `_execute().output_data` so the raw path stays available, and narrows `_validate_input()` with its own checks. The module ends with its `DISCOVERY` constant.

`SklearnEstimator` is the one general-purpose member: it accepts any case-insensitive class name from `sklearn.utils.all_estimators()`, inspects the estimator's mixins to decide whether it predicts, clusters, or transforms, and writes the result onto each record. `properties["algorithm"]` selects the class; the fitted model is not persisted.

### Shared helpers

| Module | Role |
|---|---|
| `_coercion.py` | `coerce_numeric(value)`: integer-first then floating-point conversion, returning `None` on failure. The shared aggregate numeric policy. `coerce_flag(value, default)`: reads a `bool` attribute as attribute validation does, so `"false"` is false; `None` gives *default* and a value validation refuses gives `None`. `create_table` and `create_database` use it for `overwrite` |
| `_record_matching.py` | `record_signature(record, match_option)`: the hashable signature behind `union` and `intersect`, for `"key_match"` and `"seq_match"` |
| `_query_results.py` | `format_execution_result(result)`: normalizes a registry execution result to the operator output shape, preserving the upstream case chain exactly |

`_coercion` is why `max` skips a non-numeric value and returns a null aggregate only when nothing coerces, rather than failing on mixed data.

### Outcome operators

The 21 retained `@3.0.0` cards and `nl2sql@4.0.0`. Each subclasses `_OutcomeOperator` and its raw counterpart, in that order, so the measurement `run()` wraps the raw transform.

`_outcomes.py` holds `_OutcomeOperator`, which overrides two methods:

- `run()` captures a monotonic start and the input bundle's shallow shape, calls the base implementation, then attaches `elapsed_ms`, `input_shape`, and — only on an error-free call — `output_shape` to `ExecMeta.traces`. Every step is individually contained, so a measurement failure cannot fail the call.
- `_validate_input()` rejects a value that is not a list of record groups with the reason `supply a list of record groups`, ahead of the attribute checks.

`elapsed_ms` is attached after the base `run()` returns, which keeps it outside any worker that timed out.
The measurements are computed values rather than references, so caller mutation afterwards does not change what the traces report.

Beyond measurement, an outcome operator's `_execute()` reports per-call facts as output attributes: `_avg_outcome` returns `num_values_used`, and `_insert_table_outcome` returns `num_rows_insert` when every batch reported a row count and omits the key when one did not.

---

## `operator_skills/loader.py` — verified resource loading

Loads reviewed prose for an exact package-owned operator, bounded and digest-checked.

| Name | Role |
|---|---|
| `OperatorSkillLoader` | the entry point, constructed with a registry |
| `OperatorSkillView` | a loaded view: `card`, `requested_level`, `loaded_kinds`, `io`, `guide`, `examples`, `history` |
| `OperatorSkillDescriptor` | a metadata-only view: `card`, `declared_kinds`, `declared_levels` |
| `OperatorIOSchema` | `input_shape`, `output_shape`, and the snapshotted `attributes` |
| `OperatorResource` | one file: `operator_id`, `kind`, `text`, `sha256` |
| `OperatorSkillLoadError` | carries a closed `code` |
| `OperatorSkillErrorCode` | `INVALID_OPERATOR_ID`, `NOT_AVAILABLE`, `BINDING_MISMATCH`, `MANIFEST_INVALID`, `RESOURCE_INVALID`, `TRUST_REQUIRED`, `SCHEMA_INVALID` |
| `snapshot_attribute_specs(operator)` | refreshes, type-checks, and deep-copies the attribute projection |

| Method | Signature | Behavior |
|---|---|---|
| `available_operator_ids` | `() -> tuple[str, ...]` | validates the index and intersects it with package-built cards in this registry |
| `describe` | `(operator_id) -> OperatorSkillDescriptor` | validates card, index, and manifest, then reports declared kinds and levels without opening any Markdown |
| `read` | `(operator_id, kind) -> OperatorResource` | one resource by kind, digest-verified |
| `load` | `(operator_id, level=2) -> OperatorSkillView` | the level's required kinds, plus the card and the live attribute schema |

Levels map to required kinds: 2 is `("guide",)`, 3 is `("guide", "examples")`, 4 is `("guide", "examples", "history")`.

| Constant | Value | Applies to |
|---|---|---|
| `INDEX_BYTE_LIMIT` | 4096 | `_index.json` |
| `MANIFEST_BYTE_LIMIT` | 4096 | a `manifest.json` |
| `RESOURCE_BYTE_LIMIT` | 16384 | one resource file |
| `JSON_DEPTH_LIMIT` | 4 | both JSON documents |

`_FilesystemResourceReader.read()` is the only file access: it refuses a symlinked root, refuses a symlink at every path segment, rejects an absolute or traversing relative path, resolves both root and target strictly, confirms containment, confirms the target is a regular file, and reads at most `limit + 1` bytes so an over-limit file is detected without being loaded.

JSON is decoded with `object_pairs_hook=_reject_duplicate_keys`, so a duplicate key is an error rather than a last-one-wins silent choice.

The five known resource kinds are `guide` → `Operator.md`, `examples` → `examples.md`, `optimization` → `optimization.md`, `issues` → `issues.md`, and `history` → `history.md`.
A manifest may declare a subset; `guide` is required.

There is no cache. Calling `describe()` and then `load()` rereads the index, and a package that changed between the two calls fails the second.

---

## `plan/types.py` — pipeline record constants

| Name | Definition |
|---|---|
| `PlanRecord` | `dict[str, Any]`, the serialized form of any graph object |
| `Constant` | a `str` subclass with value-based equality |
| `Status` | `INITED`, `REFINING`, `REFINED`, `EXECUTING`, `EXECUTED`, `PLANNED`, `FAILED` |
| `NodeType` | `INPUT`, `OUTPUT`, `OPERATOR` |
| `EntityType` | `OPERATOR`, `DATA_PIPELINE` |
| `SyncBackend` | a `Protocol`: `__call__(path, key, value) -> None` |

The constants are `str` subclasses rather than enums because they are written into serialized records and read back by value.
`REFINING` and `REFINED` are retained vocabulary from the removed refinement API.
Nothing in the package sets either one; `to_jsonform_diagram_json` still maps them to a progress value so a stored 2.x record renders.

`SyncBackend` is the injection point that replaces Blue's runtime synchronizer.
The default is no synchronization at all, which is what keeps this package free of any message-bus, connection, or stream dependency.

---

## `plan/pipeline.py` — the portable graph

Seven classes over a shared `Base`: `Node`, `Entity`, and `DAG` each extend it directly, and `EntityDAG` → `Plan` → `DataPipeline` layer on top of `DAG`.

| Class | Adds |
|---|---|
| `Base` | a live `PlanRecord` with `id`, `label`, `type`, `properties`, plus `to_dict()`, `from_dict()`, and optional synchronization |
| `Node(Base)` | reciprocal `prev` and `next` edge lists, and `connect_to()` |
| `Entity(Base)` | a metadata record linkable to nodes |
| `DAG(Base)` | a `nodes` map and a label-to-ID `map`, node creation and lookup, edge wiring, traversal, and filtering |
| `EntityDAG(DAG)` | typed entity collections and the node-to-entity links |
| `Plan(EntityDAG)` | `merge()`, which folds another plan's nodes and entities in as one entity |
| `DataPipeline(Plan)` | plan-level attributes, declared input and output, per-node value and status, and the three `define_*` constructors |

### `DataPipeline`

| Method | Signature | Role |
|---|---|---|
| `define_input` | `(label=None, value=None, provenance=None, properties=None, sync=None) -> Node` | the single declared input node |
| `define_output` | `(label=None, value=None, provenance=None, properties=None, sync=None) -> Node` | the single declared output node |
| `define_operator` | `(name, label=None, attributes=None, properties=None, sync=None) -> Node` | an operator node plus its operator entity |
| `create_operator` | `(name, label=None, attributes=None, properties=None, sync=None) -> Entity` | the entity on its own |
| `set_plan_input` / `set_plan_output` | `(node_or_id, sync=None) -> None` | declares which node is the boundary |
| `get_plan_input` / `get_plan_output` | `(pipeline=None) -> Node \| None` | reads it back, optionally from a merged sub-plan entity |
| `set_node_value` / `get_node_value` | `(node, value=None, provenance=None, sync=None)` / `(node, provenance=None)` | the per-node data slot, with an optional provenance-keyed variant |
| `set_node_status` / `get_node_status` | same shape | the per-node status slot |
| `set_attribute` / `get_attribute` / `get_attributes` | plan-level attributes | metadata travelling with the plan |
| `merge` | `(merge_plan, sync=None) -> None` | folds a sub-plan in and rewrites its nodes' provenance |
| `to_jsonform_diagram_json` | `() -> dict[str, Any]` | a node-and-edge rendering for a diagram view, with progress derived from status |

`define_operator` and `create_operator` both call `_require_pinned_operator_id`, which rejects a bare name, a deployment route, and a host address.
Only `name@<MAJOR.MINOR.PATCH>` is accepted, so a serialized plan stays deterministic and deployment-neutral.

`to_dict()` is the serialization boundary, and `from_dict()` on the round trip is how a caller gets a plan that execution has not mutated.
`from_dict()` validates only that `id` and `type` are present and fills the structural defaults; the graph checks belong to the executor.

---

## `plan/executor.py` — graph validation and execution

| Class | Role |
|---|---|
| `PipelineExecutor` | constructed with the registry the pinned IDs must resolve against |
| `PipelinePreflight` | `node_order` and `operator_ids` |
| `NodeRun` | `node_id`, `operator_id`, `status`, `output_data`, `output_attributes`, `exec_meta` |
| `PipelineRun` | `output_data`, `node_runs`, `failed_node_id`, plus a `succeeded` property |
| `PipelineError` | a `ValueError` subclass: the graph or the input cannot be executed safely |

| Method | Signature |
|---|---|
| `preflight` | `(pipeline, properties=None) -> PipelinePreflight` |
| `execute` | `(pipeline, input_data, properties=None) -> PipelineRun` |

Both share one `_prepare()` step, so a graph that preflights clean will reach its first operator.
`_prepare()` checks node records and edge reciprocity, requires exactly one declared input and one declared output, topologically sorts, requires every node to lie on a path from the input and to the output, rejects a node that has already started, resolves each pinned ID, and deep-copies the attributes. Ordinary properties retain stored-plan, invocation, then node precedence. LLM aliases use invocation, stored-plan, then node precedence.

Execution aggregates each node's predecessor outputs in predecessor order, calls `run()`, records a `NodeRun`, and stops at the first node whose metadata carries errors, marking the remaining nodes failed.
An exception escaping `run()` is still caught and turned into a synthetic `FAILED` / `EXECUTION_FAILED` record, so the executor's contract holds even if an operator's does not.

`_aggregate_predecessors` raises `PipelineError` when a predecessor's stored value is not a bundle, which catches a hand-edited record before it reaches an operator.

---

## `plan/context.py` — planning errors and bounded schema context

This module holds two things that would otherwise sit in different places: the planning error vocabulary, and the data-context contracts.
`DataScope` is part of `PlanningRequest`, and the data-context boundary raises the same structured records the planner does, so both need one record type — keeping it here is what lets `planner` import `context` without a cycle.

### Error vocabulary

| Name | Role |
|---|---|
| `PlanningStage` | `VALIDATION`, `DISCOVERY`, `DATA_CONTEXT`, `GENERATION`, `SELECTION`, `COMPILATION`, `PREFLIGHT` |
| `PlanningErrorCode` | the closed code set, from `INVALID_REQUEST` through the seven `GENERATOR_*` provider outcomes to `RESULT_COPY_FAILED` |
| `PlanningErrorRecord` | `NamedTuple`: `category`, `code`, `stage`, `message`, `retryable`, `suggestion` |
| `PlanningError` | `ValueError` subclass exposing `record` |
| `planning_error(...)` | the constructor every raise site uses |
| `invalid_request(message)` | the `VALIDATION` / `INVALID_REQUEST` shorthand |
| `context_read_failure()` | the one generic record used for any failure of a foreign provider |

The `GENERATOR_*` codes are provider-independent by design: the names describe what happened to planning rather than which SDK or HTTP status produced it, and no provider text reaches a record.

### Data context

| Name | Role |
|---|---|
| `DataScope` | frozen dataclass: `source`, `database`, `collection`, and an advisory `entities` projection, canonicalized into sorted order |
| `DataContextSnapshot` | frozen dataclass: `scope`, `resolved_entities`, and a closed `payload` |
| `DataContextProvider` | a `Protocol`: `collect(scope) -> DataContextSnapshot` |
| `RegistryDataContextProvider` | the shipped adapter over a `RegistrySeam` |
| `detached_snapshots(collected)` | validates a provider's snapshot and rebuilds it as two package-owned copies |
| `validate_scope_fields(scope)` | checks a scope's current field values, not just its class |
| `DATA_CONTEXT_FORMAT` | `"blue-data-ops/data-context@1"` |
| `MAX_NAME_OR_TYPE_CODEPOINTS` | 128, fixed rather than tunable: it describes a name's wire representation, not a budget |

The payload has exactly four keys — `protocol`, `schema`, `provenance`, `limits` — and the shape is closed, so there is no field an unexpected value could travel in.
Construction deep-copies and recursively freezes the payload, validates the whole document against the bounds the payload itself declares, and measures the canonical serialization against the byte limit.
A snapshot that exists already satisfies every limit it reports.

`detached_snapshots()` exists because a single instance reaching both the generator and `PlanningResult` would make the generator's argument and the planner's retained record the same mutable object.
The two returned copies are distinct objects that serialize identically; nothing the caller supplied survives into either.

`RegistryDataContextProvider(registry, *, max_entities=32, max_attributes_per_entity=64, max_total_attributes=512, max_description_chars=512, max_serialized_bytes=131072)` collects from three read-only registry calls: `get_source_properties`, `list_collection_entities`, and `list_entity_attributes`.
It records `raw_rows: 0` in the snapshot's provenance and reads no relations, because the producer may leave their endpoints empty and a relation projection would not mean what a planner would take it to mean.
`collect()` pins the registry and the limits into local state on entry and dispatches through no other instance attribute, which is what lets the planner surface this class's structured errors as they are.

---

## `plan/planner.py` — the planning stages

The request types, the draft types, the rule generators, the selector, and the planner itself.

### Request

| Type | Fields |
|---|---|
| `DiscoveryQuery` | `text`, `tags=()`, `limit=20` |
| `PlanningRequest` | `goal`, `discovery_queries`, `operator_attributes={}`, `data_scope=None`, `allowed_operator_ids=()`, `input_label="input"`, `output_label="output"`, `max_discovery_cards=40`, `max_candidates=8`, `max_steps=16`, `max_nodes=18`, `max_edges=17` |

Both validate in `__post_init__`, and the planner re-validates every field again on entry.
That is not redundancy: a frozen dataclass still yields to `object.__setattr__`, and the scope decides which collection is read and which addresses the compiler accepts.

### Drafts and results

| Type | Fields |
|---|---|
| `PlanStep` | `step_id`, `operator_id`, `attributes={}`, `depends_on=()`, `label=None` |
| `PlanDraft` | `steps`, `label=None` |
| `DiscoverySnapshot` | `cards`, plus an `operator_ids` property and `one(name)` |
| `PlanningResult` | `request`, `discovery`, `candidates`, `selected`, `pipeline`, `preflight`, `data_context=None` |
| `PlannerRun` | `planning`, `execution` |

`DiscoverySnapshot.one(name)` raises `DISCOVERY_RESULT_INVALID` unless exactly one discovered card carries that name, naming the IDs it did find.
It is what a rule template calls when it needs an unambiguous slot.

### Generators and selector

| Name | Role |
|---|---|
| `PlanGenerator` | a `Protocol`: `generate(request, discovery, data_context) -> Sequence[PlanDraft]` |
| `PlanRule` | a callable alias with the same three arguments, returning `PlanDraft \| None` |
| `RuleTemplateStep` | one exact operator slot: `step_id`, `operator_name`, `required_attributes`, `expected_tags` |
| `RulePlanTemplate` | `label` plus ordered steps; builds a linear draft, and is callable as a rule |
| `RulePlanGenerator` | evaluates rules in order and keeps their drafts |
| `SELECT_THEN_AVERAGE_TEMPLATE` | the shipped filter-then-average template |
| `project_then_aggregate_template(name)` | the shipped project-then-aggregate templates for `"avg"`, `"sum"`, `"min"`, `"max"` |
| `RequireSinglePlan` | the shipped selector: `NO_CANDIDATES` on empty, `AMBIGUOUS_CANDIDATES` on more than one |

A rule and a generator take the same three arguments.
A rule may ignore the data-context snapshot, and the parameter is still required so the protocol has one shape.

`RulePlanTemplate.generate()` is stricter than a plain rule: per slot it requires discovery to have returned exactly one card with that name, and it compares the card's ID, name, version, and full ordered tag tuple against the template.
A template that no longer matches the catalog refuses to build rather than planning against a card it does not recognize.
`RuleTemplateStep` and `RulePlanTemplate` both validate their own shape in `__post_init__` and raise `GENERATION_FAILED` on a malformed configuration.

### `PipelinePlanner`

```text
PipelinePlanner(
    registry: OperatorRegistry,
    generator: PlanGenerator,
    selector: RequireSinglePlan | None = None,
    data_context_provider: DataContextProvider | None = None,
    *,
    embedding_index: OperatorEmbeddingIndex | None = None,
)
```

An embedding index bound to a different registry raises `EmbeddingDiscoveryError("BACKEND_MISMATCH")` at construction.

| Method | Signature | Role |
|---|---|---|
| `discover` | `(request) -> DiscoverySnapshot` | compatibility discovery over exact `2.0.0` cards, including lifecycle history |
| `plan` | `(request) -> PlanningResult` | the full stage sequence |
| `execute` | `(planning, input_data, properties=None) -> PipelineRun` | re-materializes the compiled pipeline and runs it |
| `run` | `(request, input_data, properties=None) -> PlannerRun` | `plan()` then `execute()` |

`execute()` rebuilds the pipeline from its serialized form, so a prior `PlanningResult` can be executed more than once without the first run having changed it.

Internally the planner keeps a scope anchor and re-compares it after every step that could have let caller code mutate the request, and it normalizes every draft on each crossing of a caller boundary.
`_capture_admission()` snapshots the discovered cards with their resolved operators, and `_compile()` re-reads the live registry and requires object identity against that snapshot before it will emit a node.
`_check_addressed_step()` requires an `nl2sql` step to name the request's own source, database, and collection — an address-consistency check on the step's attributes, not table authorization.

---

## `plan/openai_generator.py` — provider-backed generation

One non-streaming Responses request per `generate()`, behind an authorization boundary and a separate disclosure opt-in.

```text
OpenAIPlanGenerator(
    model: str,
    *,
    registry: OperatorRegistry,
    allowed_operator_ids: Collection[str],
    client: Any | None = None,
    send_data_context: bool = False,
    max_candidates: int = 1,
    timeout_seconds: float = 60.0,
    max_output_tokens: int = 4096,
)
```

| Constructor check | Reason |
|---|---|
| `model` nonempty and not `ft:`-prefixed | the outbound schema uses `minItems` and `maxItems`, which the fine-tuned structured-output subset does not support |
| `registry` exactly an `OperatorRegistry` | provenance checks read this instance's private tables |
| `max_candidates == 1` | the shipped selector accepts exactly one candidate; a larger value would advertise a capability nothing honors |
| `0 < timeout_seconds <= 300` | a bounded provider wait |
| `256 <= max_output_tokens <= 16384` | a bounded response |
| every allowed ID pinned at `2.0.0` or `3.0.0`, unique | the allowlist is an authorization boundary |

| Name | Role |
|---|---|
| `generate(request, discovery, data_context)` | the `PlanGenerator` implementation |
| `PLANNING_INPUT_FORMAT` | `"blue-data-ops/planning-input@1"` |
| `PLANNER_INSTRUCTIONS` | the system instructions, which state that operator descriptions and the goal are data rather than instructions |
| `response_format()` | a fresh copy of the packaged `text.format` document |

The provider gets the whole packaged schema document and the local validator gets only its `schema` member, both from `plan/_schemas/plan-candidates.schema.json`, so a limit cannot drift between what the provider validates and what this package accepts.

Decoder bounds are module constants rather than schema keywords, because a byte bound is checked locally against UTF-8 rather than code points: 128 bytes for an ID, 256 for a label, 32768 for one step's attributes JSON, 131072 for the raw response, 131072 for the request, and attribute nesting depth 64.

`_decode_attributes()` merges the caller's attributes first, then the model's.
An undeclared key is rejected before the overlap test.
Reversing this order would let a model-authored field bypass the declaration check whenever the caller supplied the same key.
An overlapping key must agree exactly rather than being overwritten by whichever side wrote last.

`_map_provider_exception()` maps by exception class and HTTP status onto `GENERATOR_TIMEOUT`, `GENERATOR_RATE_LIMITED`, `GENERATOR_UNAVAILABLE`, `GENERATOR_REQUEST_REJECTED`, `GENERATOR_REFUSED`, and `GENERATOR_RESPONSE_INVALID`.
A `ModuleNotFoundError` naming exactly `openai` becomes `GENERATOR_DEPENDENCY_MISSING`; anything wider stays a generic generation failure, so an SDK that is installed but broken is not reported as uninstalled.

---

## `data/registry_seam.py` — the blue-data facade

`RegistrySeam(registry: DataRegistry)` wraps one `blue-data` registry and is the compatibility surface every operator calls.

| Method group | Methods |
|---|---|
| create | `create_source_database`, `create_source_database_collection_entity` |
| describe | `set_source_database_description`, `set_source_database_collection_entity_description` |
| records | `set_record_data`, `get_record` |
| introspect | `get_source_properties`, `get_source_database_collection_properties`, `list_collection_entities`, `list_entity_attributes`, `list_collection_relations`, `get_data_source_schema` |
| connect | `connect_source`, `register_source` |
| query | `execute_query` |
| search | `search_records`, `search_records_hierarchical` |

Every call forwards by keyword.
That is what prevents a positional swap in `execute_query`, where the facade accepts `(query, source, ...)` and the wrapped registry accepts `(source, query, ...)`.

Four compatibility behaviors are carried here rather than in the operators:

- `rebuild` is accepted per call. `blue-data` has no such flag, so `_emulate_rebuild()` calls `build_index()` when a true per-call flag meets an instance policy that has rebuilds off.
- `protocol` on `get_data_source_schema` is accepted for signature compatibility and not forwarded; the wrapped registry derives the protocol from the source's own connection properties.
- `approximate` and `hybrid` on `search_records` are accepted and not forwarded; the original consumer-side registry accepted and ignored them, and the wrapped engine has no counterpart.
- `_normalize_search_result()` folds two delegate result shapes into one flat record with an inverted score — lower is better, matching the original registry's own inversion — and derives the ID from the delegate's `"{scope}/{type}/{name}"` hierarchy-node convention. List order is preserved, which is already consumer-ascending.

The seam holds one `Any`-typed delegate attribute.
`blue-data` ships no `py.typed`, so this is the package's single untyped-library boundary and unknown member types stop here rather than spreading into callers.

`list_collection_entities` and `list_entity_attributes` read registered metadata only: they neither connect to the source nor execute a query. Planning context uses them instead of `build_schema_for_nl()` so it can tell an absent declared type from a real one.

---

## `data/provider.py` — registry resolution

| Name | Role |
|---|---|
| `DataRegistryProvider` | an ABC with one abstract `get_registry(platform_name, registry_name, properties) -> RegistrySeam` |
| `BlueDataRegistryProvider` | the default: a per-name-pair cached in-memory `DataRegistry` with eager index rebuilds |
| `resolve_registry(properties, provider=None)` | the resolution order every registry-backed operator calls |

`resolve_registry` returns an injected `RegistrySeam` as-is, wraps an injected raw `DataRegistry`, then falls back to constructing one from `properties["platform.name"]` and `properties["data_registry.name"]` through the provider.
An invalid injected value falls through to the construction keys rather than failing.
Neither key present returns `None`, and the calling operator reports the unavailable registry through its own error path.

This module defines a local `Properties = dict[str, Any]` alias rather than importing the one in `operators/types.py`, so the dependency stays one-way: operators import the seam, and the seam never imports operators.

---

## `llm/client.py` — the provider seam

| Name | Role |
|---|---|
| `LLMClient(name, properties=None)` | builds templated requests and executes them through LiteLLM |
| `UsageRecord` | `model`, `prompt_tokens`, `completion_tokens`, `cost`, `latency_seconds`, `cache_hit` |
| `UsageLedger` | an append-only list of records, with `total_cost` and `total_tokens` |

| Method | Signature |
|---|---|
| `execute_api_call` | `(input, properties=None, additional_data=None) -> Any` |
| `aexecute_api_call` | `(input, properties=None, additional_data=None) -> Any` |

The client's own properties are merged under the call's, so a per-call value wins.

| Constant | Contents |
|---|---|
| `_ACCEPTED_LLM_KEYS` | `model`, `stream`, `max_tokens`, `temperature`, `reasoning_effort`, `cache`, `cache_dir`, `max_parallel`, `rate_limit` |
| `_CONTROL_KEYS` | `cache`, `cache_dir`, `max_parallel`, `rate_limit` — consumed by the client, never forwarded |
| `_RESERVED_FIELDS` | `api`, `service_url` — dispatch-only operator defaults, stripped after every merge rather than refused |
| `_GENERATION_FIELDS` | the closed set a prefixed property may set, `_SIGNATURE_GENERATION_FIELDS` and `_KWARGS_GENERATION_FIELDS` together — anything outside it raises `reserved_field` rather than being forwarded |
| `_SUBSTITUTED_RESPONSE_FIELDS` | `mock_response`, `mock_timeout` — LiteLLM returns these verbatim without calling anyone |

Three codes come out of assembling the call kwargs.
An unknown `llm.*` key raises `LLMError` with code `bad_override`, and a missing model raises `LLMError` with code `no_model`.
A prefixed property namespace admits the generation parameters of the provider call and nothing else.
Any other field — one that chooses the provider, the endpoint, the project, tenant or region, one that supplies a credential, or one that substitutes the provider's answer — raises `LLMError` with code `reserved_field`, before the cache key is built, so nothing a caller sent under one of those names is written to disk either.
`model` is additionally held to the deployment's provider, and one that resolves elsewhere is refused with `model_not_allowed`.
A bare model name selects a provider too, so the check is on the outcome — what the provider library would actually dispatch to — as well as on the spelling.
A slash is not itself a provider prefix: an identifier such as `accounts/fireworks/models/llama-v3` names a model and is accepted, while `azure/my-deploy` is not, because the deployment names Azure and the property names the deployment.
The two refusals share a code and carry different messages: one says the endpoint and the key come from the environment the deployment runs in, the other says a result carries what the provider answered rather than what the caller sent.
Caching is off unless `llm.cache` is set, keyed per `cache_dir` so a per-call override selects its own isolated cache, with the canonically serialized call kwargs as the key.
Rate admission waits for a slot. Each attempt shares a cumulative budget capped at 10 seconds and the remaining operator deadline; if the wait expires, the caller receives a retryable local refusal. See [LLM settings](../docs/llm-settings.md#rate-admission-and-response-cache) for the user-facing limits and cache behavior.
The provider call carries a `tenacity` retry for retryable `LLMError` instances: three attempts,
exponential backoff, re-raising the last. LiteLLM's `UnsupportedParamsError`, and a provider
`BadRequestError` whose structured body has code `unsupported_parameter`, become a non-retryable
`unsupported_parameter` error because repeating the same rejected request cannot repair it.

`_record()` writes one `UsageRecord` per call, cache hits included, with end-to-end latency that spans retries.
`_safe_int()` makes accounting total: any inconvertible token value — a junk string, an infinity, a `Decimal('NaN')`, an arbitrary object — counts as zero rather than raising inside a cost calculation.

`_InvocationCostObservation` is the narrow path behind the `nl2llm@3.0.0` cost trace.
`complete_cost()` returns `0.0` for a proven local cache hit with no provider attempt, the estimated cost after exactly one attempt, and `None` otherwise — retries, failures, and unknown prices report nothing rather than guessing.

---

## `llm/provider.py` — client lifetime

| Name | Role |
|---|---|
| `LLMClientProvider` | an ABC with one abstract `get_client(properties) -> LLMClient` |
| `CachingLLMClientProvider` | opt-in per-configuration reuse, keyed on `service_prefix`, `llm.*`, and prefixed keys |
| `resolve_llm_client(properties, provider=None)` | injected client, then provider, then a fresh client |

The default lifetime is one client per invocation, never a module-level singleton.
`CachingLLMClientProvider` falls back to constructing an uncached client when the relevant configuration is not JSON-serializable, so a non-serializable value is never an error.
The cache's lifetime belongs to whoever created the provider.

---

## `llm/templating.py` — request and response shaping

| Function | Role |
|---|---|
| `safe_substitute(template, **kwargs)` | applies `string.Template.safe_substitute` once; inserted values and Jinja syntax remain literal |
| `build_message(input_data, properties, additional_data=None, default_prefix="")` | builds the request message, rejecting duplicate substitution keys |
| `extract_output(payload, properties)` | reads the configured output path, then strips, transforms, templates, and casts |

`safe_substitute` preserves unknown `$names`, supports `$$` escaping, and keeps line endings intact. For example, `safe_substitute("$a", a="$b", b="done")` returns `"$b"`. This security repair changes the former recursive/Jinja helper contract. LLM prompts normalize line endings and remove one terminal newline from the trusted template before substitution; inserted data retains its original bytes.

`_substitute_with_collision_check` merges the property, parameter, and additional-data sources and raises `TypeError` on a duplicate key rather than giving one source implicit precedence.

`_preprocess_output` applies the configured `replace` and `sub` transformations. The `sub` case passes the configured replacement string to the regular-expression engine rather than reusing the compiled search pattern as the replacement — a deliberate difference from the reference behavior.
`_cast_output` implements `int`, `float`, `json`, and `str`; any other cast name, `"bool"` included, leaves the value unchanged.

---

## `llm/errors.py` — the provider error type

`LLMError(message, code=None, provider_error=None, *, retryable=True)` is raised for transport
failures, malformed responses, and rejected adapter configuration.

The wrapping boundary is stated in the module: provider exceptions and malformed responses are wrapped here by the client, and templating errors — a substitution `TypeError`, a JSONPath miss — stay raw because they happen before the provider boundary.

---

## `tools/tool.py` — the Blue tool surface

`Tool(name, function, description=None, properties=None, validator=None, explainer=None)` is a function plus live properties, validation, explanation, and signature metadata.

| Method group | Methods |
|---|---|
| properties | `properties` property, `get_properties(overrides=None)` |
| signature | `get_signature`, `get_parameters`, `get_parameter`, `get_parameter_type` |
| parameter metadata | `set_parameter_description`, `set_parameter_required`, `set_parameter_hidden`, `is_parameter_required`, `is_parameter_hidden` |
| returns | `get_returns`, `get_returns_type`, `set_returns_description` |

`get_properties(overrides)` merges rather than mutating, so a caller can ask what the properties would be without changing them.

The `properties` property lazily initializes through `_initialize_missing_metadata()` when the backing attribute is absent, which is what lets a subclass constructed through an unusual path still answer metadata questions.
`Operator` guards that path against re-entry.

---

## `utils/type_utils.py` — Blue type parsing

| Function | Signature | Role |
|---|---|---|
| `string_to_python_type` | `(type_str) -> Any` | converts a Blue type string to a Python type for Pydantic |
| `create_pydantic_model` | `(parameters) -> type[BaseModel]` | builds a model from `{name: {"type", "required"}}` definitions |
| `validate_parameter_type` | `(value, expected_type) -> bool` | validates one value against one Blue type string |

`string_to_python_type` reproduces Blue's return-object identity, not just its semantics: the `list`, `dict`, `optional`, and `union` spellings return `typing.List`, `typing.Dict`, `typing.Optional`, and `typing.Union` objects, while `tuple`, `set`, `frozenset`, and `deque` return builtin generics.
Code that compares the returned type object keeps working.
Unknown names and the empty string fall back to `Any`.

`validate_parameter_type` applies the same lax Pydantic coercion Blue applies.
A `None` expected type accepts anything.
A validation mismatch or a malformed specification — `union[]`, which yields an empty `Union` and a `TypeError` — returns `False` with a warning rather than leaking a parser error.
It raises `RuntimeError` only on a genuine internal fault, which is Blue's own fail boundary.

---

## `utils/tool_utils.py` — signature and type-shape conversion

| Function | Signature | Role |
|---|---|---|
| `annotation_to_type_str` | `(annotation) -> str` | a class becomes its `__name__`, anything else becomes `str(annotation)` with the `typing.` prefix stripped |
| `convert_type_string_to_mcp` | `(type_str) -> dict[str, Any]` | type string to MCP JSON-schema shape |
| `extract_signature` | `(function, mcp_format=False) -> dict[str, Any]` | a `{parameters, returns}` dictionary |

`extract_signature` carries Blue's falsy-default quirk: a truthy default marks a parameter optional and records its value, and a falsy or absent default marks it required.
A `None` return annotation yields an empty `returns` dictionary.

`convert_type_string_to_mcp` maps `int` and `float` to `number`, `str` to `string`, a `List[...]` to an array with recursively converted items, a `Dict...` to an object, and everything else — the empty string included — to `unknown`.
The `List` slice offset is Blue's.

---

## `utils/json_utils.py` — merge and JSONPath

| Function | Signature | Role |
|---|---|---|
| `merge_json` | `(original_json, update_json) -> Any` | jsonmerge's default object merge |
| `json_query` | `(json_object, json_path_query, single=True, default=None) -> Any` | JSONPath query |
| `json_query_set` | `(json_object, attribute, value, context="$") -> None` | sets an attribute at every context match |

`merge_json` mirrors Blue byte-for-byte, raising on a scalar base against an object head rather than silently replacing it.
`json_query_set` sets directly at the root context; at any other context each match must be a dict, and index and field paths are updated in place.

`jsonpath-ng` and `jsonmerge` ship no type information, so the untyped boundary is crossed once at the top of this module and downstream results are plain `Any`.

---

## `utils/string_utils.py` and `utils/uuid_utils.py`

`string_utils` re-exports `safe_substitute` from `llm/templating` and nothing else.
The remaining Blue `string_utils` helpers — `camel_case`, `remove_non_alphanumeric`, and the web-safe base64 pair — are left out: they are outside the migrated operator closure, and the base64 pair would add a `pydash` dependency the package does not otherwise need.

`uuid_utils` holds the canonical-ID helpers, with Blue's `Separator.ID` value `":"` inlined rather than imported from `blue.constant`.

| Function | Role |
|---|---|
| `create_uuid()` | a short lowercase-hex identifier from a UUID4's first field |
| `split_ids(canonical_id)` | the components |
| `extract_name_id(canonical_id)` | the trailing `(name, id)` pair |
| `extract_sid(canonical_id)` | that pair rejoined |
| `extract_prefix(canonical_id)` | everything before it, or `None` |
| `concat_ids(*ids)` | joins with the canonical separator |

---

## `_deprecation.py`

`BlueDataOpsDeprecationWarning(DeprecationWarning)` is the warning category the 2.x lifecycle surface used.
It stays importable as a compatibility category; nothing in the package emits it, because the deprecated surfaces that did have been removed.

---

## `blue_data_ops_mcp.registration` — the deployment snapshot

| Name | Role |
|---|---|
| `ACTIVE_OPERATOR_IDS` | the 33 mixed-version primary IDs, the ordinary deployment default |
| `V2_OPERATOR_IDS` | the 33 retained `@2.0.0` IDs, a compatibility tuple rather than the default |
| `OperatorBinding` | frozen: `card` and `operator` |
| `DeploymentSnapshot` | `tuple[OperatorBinding, ...]` |
| `DEPRECATION_SENTENCE` | the sentence prepended to a deprecated card's tool description |

| Function | Signature | Role |
|---|---|---|
| `freeze_deployment` | `(registry=None, operator_ids=None) -> DeploymentSnapshot` | validates and freezes one exact primary-only selection, sorted by name |
| `make_run_handler` | `(operator) -> Any` | an async handler wrapping `run()`, with a synthesized signature |
| `run_payload` | `(result) -> dict[str, Any]` | projects a `run()` triple onto the wire object |
| `register_snapshot` | `(server, snapshot) -> None` | adds one structured-output tool per binding |

Both ID tuples are explicit adapter policy ordered by logical name, not a semver maximum and not a registry query.

`freeze_deployment` checks each requested ID for card existence, self-consistent card identity, a supported version, and exact operator resolution.
A package-owned ID must additionally be a same-registry built-in whose resolved implementation class matches a reference `versioned_registry()` build.
A card that is a built-in, or reuses a supported built-in name, but is not in the supported set is rejected outright; a caller-created card is accepted at `2.0.0` only.
Duplicate logical names fail rather than one winning.

`make_run_handler` moves `run()` off the event loop with `asyncio.to_thread`, so a synchronous transform does not block the server.
`_wire_json` applies the conversion once with `default=str` and `allow_nan=False`; a `ValueError` from a non-finite float is an adapter error that becomes a tool error at the handler boundary and never becomes a synthetic operator `ErrorRecord`.

`_compose_description` joins the deprecation sentence when applicable, the card's `when_to_invoke`, and the card's description.
`_meta` carries `operator_id`, `version`, and `tags`, adding `deprecated` only when it is true.

---

## `blue_data_ops_mcp.schema` — the wire contract

| Name | Role |
|---|---|
| `RunResult` | the structured envelope: `output_data`, `output_attributes`, `exec_meta` |
| `ExecMetaModel` | `is_empty`, `errors`, `logs`, `traces` |
| `ErrorRecordModel` | the canonical error record with the frozen error vocabulary |
| `attributes_json_schema(operator)` | the JSON schema for the `attributes` argument |
| `handler_signature(operator, return_annotation)` | the synthesized handler signature |

All three models set `ConfigDict(extra="forbid")`, so an unexpected key on the wire is a validation failure rather than a silently accepted field.

`attributes_json_schema` keeps every attribute's description and publishes a default only for an optional attribute that both declares one and materializes it.
Required attributes and the declarations with `materialize_default=False` publish no default, matching the canonical materialization boundary.
Published defaults are deep copies, never aliases of core state.

`handler_signature` builds the three parameters — `input_data` as a list of record groups, `attributes` annotated with that schema and defaulting to an empty object, `properties` optional — and the structured return annotation.
`additionalProperties` stays `True` on the attributes object, because the container schema is not where business validation belongs.

---

## `blue_data_ops_mcp.server` — construction and serving

| Function | Signature |
|---|---|
| `create_server` | `(*, registry=None, operator_ids=None, host=None, port=None, path="/mcp") -> FastMCP[Any]` |
| `serve` | `(*, registry=None, operator_ids=None, host=None, port=None, path="/mcp") -> None` |

`create_server` freezes the deployment, constructs `FastMCP` with `json_response=False` and `stateless_http=False` — a stateful session — and registers the snapshot.
`serve` performs the same construction and calls `server.run(transport="streamable-http")`.

The package `__init__` resolves `ACTIVE_OPERATOR_IDS`, `V2_OPERATOR_IDS`, `create_server`, and `serve` through a module-level `__getattr__`, so importing `blue_data_ops_mcp` does not import the MCP SDK until one of them is actually read.

HTTP requires the shared API key by default on both streamable HTTP and SSE.
See the [HTTP bind, authentication and mounted lifespan contract](../docs/mcp.md#http-authentication-and-bind-settings)
for environment overrides, the explicit no-key opt-out and the SDK Host/Origin limits.

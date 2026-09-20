# API Reference

The public Python surface of `blue-data-ops`, module by module.
For a task-oriented walkthrough see [guide.md](guide.md); for the shapes behind these signatures see [`design/09-api-interface-spec.md`](../design/09-api-interface-spec.md).

Per-operator metadata — attributes, defaults, tags, invocation guidance, and accepted outcome coordinates for each of the 33 active operator IDs — lives in the generated [`lib/OPERATORS.md`](../lib/OPERATORS.md), which is the source of truth for that content and is never hand-edited.
This page does not restate it.
[`lib/README.md`](../lib/README.md) is the source of truth for the library package itself; where the two overlap, it wins.
For the MCP tool surface see [mcp.md](mcp.md).

---

## Top-level exports

Everything in this table is importable directly from `blue_data_ops`.
Nothing else is.

```python
from blue_data_ops import Operator, SelectOperator, FunctionResult, RegistrySeam
```

### Operator classes

Thirty-two concrete operator classes plus the abstract base.
Each concrete class is one logical operator; the exact version comes from the registry that resolved it, not from the class.

| Export | Logical operator | Extra required |
|---|---|---|
| `Operator` | abstract base, see [Operator](#operator) below | none |
| `ArgmaxOperator` | `argmax` | none |
| `ArgminOperator` | `argmin` | none |
| `AvgOperator` | `avg` | none |
| `ClassifyOperator` | `classify` | `[ml]` |
| `ClusterOperator` | `cluster` | `[ml]` |
| `CreateDatabaseOperator` | `create_database` | none, needs a registry |
| `CreateTableOperator` | `create_table` | none, needs a registry |
| `DataDiscoverOperator` | `data_discover` | none, needs a registry |
| `DeleteOperator` | `delete` | none |
| `InsertOperator` | `insert` | none |
| `InsertTableOperator` | `insert_table` | none, needs a registry |
| `IntersectOperator` | `intersect` | none |
| `JoinOperator` | `join` | none |
| `MaxOperator` | `max` | none |
| `MinOperator` | `min` | none |
| `NL2BNOperator` | `nl2bn` | `[llm]` |
| `NL2LLMOperator` | `nl2llm` | `[llm]` |
| `NL2SQLOperator` | `nl2sql` | `[llm]` |
| `NormalizeTextOperator` | `normalize_text` | none |
| `ProjectOperator` | `project` | none |
| `SegmentTextOperator` | `segment_text` | none |
| `SelectOperator` | `select` | none |
| `SemanticExtractOperator` | `semantic_extract` | `[llm]` |
| `SemanticFilterOperator` | `semantic_filter` | `[llm]` |
| `SemanticJoinOperator` | `semantic_join` | `[llm]` |
| `SemanticProjectOperator` | `semantic_project` | `[llm]` |
| `SemanticTransformOperator` | `semantic_transform` | `[llm]` |
| `SumOperator` | `sum` | none |
| `UnionOperator` | `union` | none |
| `VectorEmbedOperator` | `vector_embed` | `[vector]` |
| `VectorSearchOperator` | `vector_search` | `[vector]` |
| `VectorSimilarityOperator` | `vector_similarity` | `[vector]` |

The thirty-third active operator, `sklearn_estimator`, is implemented by `SklearnEstimator` and is reachable from `blue_data_ops.operators` rather than the top level — see [Registry and discovery](#registry-and-discovery).

### Everything else exported at the top level

| Export | Kind | What it is |
|---|---|---|
| `Tool` | class | The Blue-compatible function wrapper `Operator` extends: live properties, a validator, an explainer, and signature metadata |
| `FunctionResult` | named tuple | `(output_data, output_attributes)`, what an operator's internal `_execute()` hook returns |
| `ValidationResult` | named tuple | `(ok, reason)`, what the internal `_validate_input()` hook returns |
| `ErrorRecord` | named tuple | One contained operator failure, see [Result and error types](#result-and-error-types) |
| `ExecMeta` | named tuple | `(is_empty, errors, logs, traces)`, the metadata every `run()` returns |
| `ErrorCategory` | str enum | `RECOVERABLE`, `FAILED`, `TIMEOUT` |
| `ErrorCode` | str enum | The frozen failure vocabulary, nine values |
| `ErrorStage` | str enum | `DEFAULTS`, `VALIDATE`, `EXECUTE`, `NORMALIZE`, `REFINE` |
| `ABSENT` | sentinel | Distinguishes "no default declared" from a declared default of `None` in `AttributeSpec` |
| `RegistrySeam` | class | The compatibility facade over a `blue-data` `DataRegistry` |
| `DataRegistryProvider` | abstract class | The provider seam `resolve_registry` accepts for constructing that registry |
| `BlueDataRegistryProvider` | class | The default provider: one cached in-memory registry per `(platform, registry)` name pair |
| `resolve_registry` | function | `resolve_registry(properties, provider=None) -> RegistrySeam \| None` |
| `BlueDataOpsDeprecationWarning` | warning class | The `DeprecationWarning` subclass the 2.x lifecycle surface used; retained so historical records stay portable |
| `utils` | module | The Blue-compatible helpers, see [Utilities](#utilities) |

---

## `Operator`

```python
from blue_data_ops import Operator
```

An abstract, flat, single-output, type-aware data operator.
Input and output are both a `DataBundle`: a list of record groups, where a group is a list of JSON-like record dicts.
Subclasses declare three class variables and implement one method — see [extending.md](extending.md).

| Class variable | Type | Role |
|---|---|---|
| `name` | `str` | The logical operator name; the registry pins it to `name@version` |
| `description` | `str` | One-sentence description, copied onto the operator card |
| `attributes` | `dict[str, AttributeSpec]` | The declared call attributes |
| `PROPERTIES` | `dict[str, Any]` | Per-class property defaults merged over the base defaults at construction |

### Calling an operator

| Call | Returns | Behavior |
|---|---|---|
| `run(input_data, attributes, properties=None)` | `(DataBundle, Attributes, ExecMeta)` | The canonical boundary: materialize declared defaults, validate, execute, normalize. Contains every failure as an `ErrorRecord` instead of raising |
| `apply(input_data, attributes, properties=None)` | `DataBundle` | Abstract. The raw transform, with no defaults, validation, or normalization. Exceptions propagate |
| `invoke(input_data, attributes, properties=None)` | `DataBundle \| None` | Boolean validation, then `apply()`. Returns `None` when validation fails |
| `validate(input_data, attributes, properties=None)` | `bool` | Checks attributes against the live declared schema. Total: it does not raise |
| `explain(output, input_data, attributes)` | `dict[str, Any]` | Describes a completed transform with input and output statistics |

`run()` is the only call that gives every invocation a fresh output-attributes mapping and a normalized empty result.
A successful empty result is `[[]]` with `is_empty=True` and no errors.
Invalid input, an execution failure, and a timeout all come back as `[[]]` plus one error record.
Set a wrapper deadline with `properties={"execution.timeout_seconds": 5.0}`; the wrapper never retries, and the legacy `properties["timeout"]` field stays observable without setting the deadline.

### Reading and adjusting declared attributes

| Call | Returns | Behavior |
|---|---|---|
| `operator_id` (property) | `str` | The pinned registry identity, or `f"{name}@2.0.0"` for a direct, unregistered instance |
| `attributes` (instance) | `dict[str, AttributeSpec]` | The live projection of the declared schema, refreshed on each `run()` |
| `get_attributes()` | `dict[str, dict[str, Any]]` | The same schema as plain definition dicts |
| `get_attribute(name)` | `dict[str, Any] \| None` | One definition |
| `get_attribute_type(name)` / `get_attribute_description(name)` | `Any` | One field of that definition |
| `set_attribute_description(name, text)` / `set_attribute_required(name, flag)` / `set_attribute_hidden(name, flag)` | `None` | Adjust the live definition on this instance |
| `is_attribute_required(name)` / `is_attribute_hidden(name)` | `Any` | Read those flags |
| `is_required(name)` | `bool \| None` | The declared requirement, `None` for an unknown attribute |
| `default_of(name)` | `Any` | The declared default, or `None` when none is declared |
| `update_attributes(...)` | `None` | Merge new definitions into the live schema |
| `get_hyperparameters()` / `update_hyperparameters(values)` | `dict[str, Any]` / `None` | The `properties["hyperparameters"]` mapping |
| `Operator.is_operator(value)` / `Operator.get_tool_type(value)` | `bool` / `str` | Class-level checks used by Blue tool dispatch |

`Operator` also inherits the `Tool` parameter-metadata surface: `get_properties`, `get_signature`, `get_parameters`, `get_parameter`, `get_parameter_type`, `set_parameter_description`, `set_parameter_required`, `set_parameter_hidden`, `is_parameter_required`, `is_parameter_hidden`, `get_returns`, `get_returns_type`, and `set_returns_description`.

---

## Result and error types

```python
from blue_data_ops import ErrorRecord, ExecMeta, FunctionResult, ValidationResult
```

| Type | Fields |
|---|---|
| `FunctionResult` | `output_data: DataBundle`, `output_attributes: Attributes` |
| `ValidationResult` | `ok: bool`, `reason: str \| None` |
| `ExecMeta` | `is_empty: bool`, `errors: list[ErrorRecord]`, `logs: list[str]`, `traces: dict[str, Any]` |
| `ErrorRecord` | `category: ErrorCategory`, `code: ErrorCode`, `operator_id: str`, `stage: ErrorStage`, `message: str`, `retryable: bool`, `suggestion: str \| None` |

`ErrorCode` values: `DEFAULTS_FAILED`, `INVALID_INPUT`, `VALIDATION_FAILED`, `VALIDATION_RESULT_INVALID`, `EXECUTION_FAILED`, `EXECUTION_RESULT_INVALID`, `REFINEMENT_FAILED`, `REFINEMENT_RESULT_INVALID`, `OPERATOR_TIMEOUT`.
The two `REFINEMENT_*` codes and the `REFINE` stage are retained vocabulary: no 3.0 code path produces them, and old serialized records still decode.

The 21 operators active at `@3.0.0` may add `input_shape`, `output_shape`, and `elapsed_ms` measurements to `ExecMeta.traces`.
A missing measurement means unavailable, not zero.

---

## Registry and discovery

```python
from blue_data_ops.operators import OperatorCard, OperatorRegistry, active_registry
```

### Registry factories

| Factory | Cards | Use it for |
|---|---|---|
| `active_registry()` | 33, twelve at `@2.0.0` and twenty-one at `@3.0.0` | Ordinary 3.0 discovery and execution |
| `versioned_registry()` | 87 retained historical cards | Migration code that deliberately resolves 1.x or 2.x behavior |
| `default_registry(**versions)` | 33 raw cards at `1.0.0`, with per-name overrides | The raw v1 compatibility view. These cards carry empty `tags` and `when_to_invoke` and grant no planning authority |

### `OperatorRegistry`

| Call | Returns | Behavior |
|---|---|---|
| `register(operator, version, tags=(), *, when_to_invoke="", deprecated=False)` | `OperatorCard` | Register under the operator's own `name` at an exact semver version. Registrations are immutable: a repeat raises `ValueError`, and there is no deregister |
| `resolve(operator_id)` | `Operator` | Exact pinned lookup. A bare name or a missing ID raises `ResolveError`; there is no latest-version fallback |
| `get_card(operator_id)` | `OperatorCard \| None` | Pinned card lookup, `None` when absent |
| `find(query, tags=None)` | `list[OperatorCard]` | Exact AND tag filter, then case-insensitive text scoring. A malformed filter token raises `DiscoveryError` |
| `find_latest(name)` | `OperatorCard \| None` | Highest version for one exact name |
| `list_cards()` | `list[OperatorCard]` | Every card, by name then descending version |

`find()` scores a name hit 10, any tag hit 8, a `when_to_invoke` hit 6, and a description hit 5, counting each field at most once.
Ties break on name, then descending version.
A blank query with tags is tag-only discovery; a blank query without tags returns `[]`.
There is no OR syntax and no negative-tag syntax.

### `OperatorCard`

A frozen dataclass whose `operator_id` is always pinned.

| Field | Type |
|---|---|
| `operator_id` | `str`, always `"<name>@<MAJOR.MINOR.PATCH>"` |
| `name` | `str` |
| `version` | `str` |
| `description` | `str` |
| `tags` | `tuple[str, ...]`, in canonical namespace order |
| `when_to_invoke` | `str` |
| `deprecated` | `bool` |

The six tag namespaces and their closed vocabularies are listed in [`lib/OPERATORS.md`](../lib/OPERATORS.md#tag-taxonomy).

### Other names in `blue_data_ops.operators`

| Export | Kind | What it is |
|---|---|---|
| `SklearnEstimator` | class | The `sklearn_estimator` operator. It wraps any estimator `sklearn.utils.all_estimators()` returns, by case-insensitive class name; needs `[ml]` |
| `OperatorDiscoverOperator` | class | A discovery facade over lexical or caller-supplied embedding search. It carries no discovery record of its own and stays outside the built-in card catalog and the MCP inventory |
| `OperatorEmbedder` | protocol | A caller-supplied batch embedder: a `space_id` property and `__call__(texts) -> Sequence[Sequence[float]]` |
| `OperatorEmbeddingIndex` | class | `build(registry, embedder)` embeds one validated snapshot of every card; `find(query, tags=None)` ranks it by cosine similarity; `registry` returns the exact registry captured at build time |
| `EmbeddingDiscoveryError` | exception | Raised with a stable `reason` such as `BUILD_FAILED`, `QUERY_FAILED`, `INVALID_RESULT`, or `STALE_INDEX` |
| `DiscoverySpec` | frozen dataclass | `when_to_invoke` plus ordered `tags`; each built-in operator module owns one as a module-level `DISCOVERY` constant |
| `DiscoveryError` | exception | A built-in discovery record violated the closed vocabulary, or a filter token was malformed |
| `upgrade_legacy_operator_id` | function | Converts a bare name, an explicit alias, or a legacy `/server/<server>/operator/<name>` path to a registered pinned ID. Always an explicit caller choice; `resolve()` never calls it |
| `UpgradeError` | exception | That conversion found nothing, or found something ambiguous |
| `ResolveError` | exception | `resolve()` was given a non-pinned or unregistered reference |
| `OperatorError` | exception | The base class for operator errors raised rather than contained |
| `OperatorValidationError` | exception | Attribute validation failed as a system error |
| `AttributeSpec` | frozen dataclass | One declared attribute: `type`, `description`, `required`, `default`, `has_default`, `materialize_default` |
| `Record`, `Data`, `DataBundle`, `Attributes`, `Properties` | type aliases | `dict[str, Any]`, `list[Record]`, `list[Data]`, `dict[str, Any]`, `dict[str, Any]` |

`OperatorEmbeddingIndex.build()` sends every card's name, invocation guidance, description, and ordered tags to the embedder in one batch.
`find()` applies no threshold and no limit, so callers slice the returned list themselves.
A registry mutated after the index was built raises `EmbeddingDiscoveryError("STALE_INDEX")` rather than returning stale rankings.

---

## Operator skill resources

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
```

Reviewed Markdown resources attached to exact operator IDs: 54 packages, 33 at `@2.0.0` and 21 at `@3.0.0`.
Loading a resource does not invoke the operator and does not add its text to planner or provider input.

| Export | Kind | What it is |
|---|---|---|
| `OperatorSkillLoader(registry)` | class | Loads resources for package-owned built-ins in that registry |
| `OperatorSkillView` | frozen dataclass | `card`, `requested_level`, `loaded_kinds`, `io`, `guide`, `examples`, `history` |
| `OperatorSkillDescriptor` | frozen dataclass | `card`, `declared_kinds`, `declared_levels` |
| `OperatorIOSchema` | frozen dataclass | `input_shape`, `output_shape`, and a detached `attributes` snapshot |
| `OperatorResource` | frozen dataclass | `operator_id`, `kind`, `text`, `sha256` |
| `OperatorSkillLoadError` | exception | Carries a `code` from `OperatorSkillErrorCode` |
| `OperatorSkillErrorCode` | str enum | `INVALID_OPERATOR_ID`, `NOT_AVAILABLE`, `BINDING_MISMATCH`, `MANIFEST_INVALID`, `RESOURCE_INVALID`, `TRUST_REQUIRED`, `SCHEMA_INVALID` |
| `snapshot_attribute_specs(operator)` | function | Refreshes and detaches an operator's live attribute projection |
| `INDEX_BYTE_LIMIT`, `MANIFEST_BYTE_LIMIT` | `int` | 4096 each |
| `RESOURCE_BYTE_LIMIT` | `int` | 16384 |
| `JSON_DEPTH_LIMIT` | `int` | 4 |

| Loader call | Returns | Behavior |
|---|---|---|
| `available_operator_ids()` | `tuple[str, ...]` | Package-built cards in this registry that also appear in the resource index |
| `describe(operator_id)` | `OperatorSkillDescriptor` | Validates card, index, and manifest, then reports declared kinds and levels without opening any Markdown |
| `read(operator_id, kind)` | `OperatorResource` | One resource with its verified digest |
| `load(operator_id, level=2)` | `OperatorSkillView` | Level 2 is the card, the live attribute schema, and `Operator.md`; level 3 adds `examples.md`; level 4 adds `history.md` |

All 54 packages declare levels 2 and 3.
No package ships level-4 `history.md` in 3.0, so requesting level 4 raises `OperatorSkillLoadError` with code `NOT_AVAILABLE`.
The loader holds no cache, so each call rereads the index; a package that changes between two calls fails the second one rather than serving a mixed view.
Custom registrations are not eligible.

---

## Pipelines and planning

```python
from blue_data_ops.plan import DataPipeline, PipelineExecutor, PipelinePlanner
```

### Pipelines

| Export | Kind | What it is |
|---|---|---|
| `DataPipeline` | class | A serializable layered node-and-entity graph. `define_input`, `define_output`, and `define_operator` add nodes; `connect_nodes` wires them; `set_plan_input` and `set_plan_output` mark the ends; `to_dict` and `from_dict` round-trip it |
| `Plan`, `Node`, `Entity` | classes | The graph record types `DataPipeline` composes |
| `PipelineExecutor(registry)` | class | `preflight(pipeline, properties=None)` resolves and checks without running; `execute(pipeline, input_data, properties=None)` runs in stable topological order and stops at the first structured operator failure |
| `PipelineRun` | frozen dataclass | `output_data`, `node_runs`, `failed_node_id`, and a `succeeded` property |
| `NodeRun` | frozen dataclass | `node_id`, `operator_id`, `status`, `output_data`, `output_attributes`, `exec_meta` |
| `PipelinePreflight` | frozen dataclass | `node_order`, `operator_ids` |
| `PipelineError` | exception, a `ValueError` | The graph or the input cannot be executed safely |
| `Status`, `NodeType`, `EntityType` | string constants | `Status`: `INITED`, `REFINING`, `REFINED`, `EXECUTING`, `EXECUTED`, `PLANNED`, `FAILED`. `NodeType`: `INPUT`, `OUTPUT`, `OPERATOR`. `EntityType`: `OPERATOR`, `DATA_PIPELINE` |
| `PlanRecord` | type alias | `dict[str, Any]`, the live record form every graph object stores |
| `SyncBackend` | protocol | `__call__(path, key, value)`, an optional callback receiving one synchronized change |

`preflight()` and `execute()` raise `PipelineError` for an unusable graph.
An operator failure after preflight stays contained in `node_runs[*].exec_meta`.
Execution mutates node values and statuses on the supplied plan, so round-trip a copy when the original record must stay unchanged.

### Planning

| Export | Kind | What it is |
|---|---|---|
| `PipelinePlanner(registry, generator, ...)` | class | `discover(request)`, `plan(request)`, `execute(planning, input_data)`, and `run(request, input_data)` |
| `PlanningRequest` | frozen dataclass | `goal`, `discovery_queries`, `operator_attributes`, `data_scope`, `allowed_operator_ids`, `input_label`, `output_label`, and the five bounds `max_discovery_cards`, `max_candidates`, `max_steps`, `max_nodes`, `max_edges` |
| `DiscoveryQuery` | frozen dataclass | `text`, `tags`, `limit`. Needs text or tags |
| `DiscoverySnapshot` | frozen dataclass | `cards`, an `operator_ids` property, and `one(name)` for the exactly-one case |
| `PlanStep` | frozen dataclass | `step_id`, `operator_id`, `attributes`, `depends_on`, `label` |
| `PlanDraft` | frozen dataclass | `steps`, `label` |
| `PlanningResult` | frozen dataclass | `request`, `discovery`, `candidates`, `selected`, `pipeline`, `preflight`, `data_context` |
| `PlannerRun` | frozen dataclass | `planning`, `execution` |
| `PlanGenerator` | protocol | `generate(request, discovery, data_context) -> Sequence[PlanDraft]` |
| `RulePlanGenerator(rules=None)` | class | Evaluates caller-supplied rules in order and keeps their drafts |
| `RulePlanTemplate` | frozen dataclass | Builds a linear draft from exactly discovered operators and caller-supplied attributes |
| `RuleTemplateStep` | frozen dataclass | One exact operator slot in such a template |
| `SELECT_THEN_AVERAGE_TEMPLATE` | `RulePlanTemplate` | The shipped filter-then-average rule |
| `project_then_aggregate_template(name)` | function | The project-to-aggregate template for `"avg"`, `"sum"`, `"min"`, or `"max"` |
| `RequireSinglePlan` | class | The shipped selector; it accepts exactly one candidate |
| `OpenAIPlanGenerator(model, ...)` | class | One non-streaming Responses call per `generate()`; needs the `[openai]` extra |

Planning raises rather than returning a partial plan, because no pipeline exists yet to carry the record.

| Export | Kind | What it is |
|---|---|---|
| `PlanningError` | exception, a `ValueError` | Carries a `record` |
| `PlanningErrorRecord` | named tuple | `category`, `code`, `stage`, `message`, `retryable`, `suggestion` |
| `PlanningStage` | str enum | `VALIDATION`, `DISCOVERY`, `DATA_CONTEXT`, `GENERATION`, `SELECTION`, `COMPILATION`, `PREFLIGHT` |
| `PlanningErrorCode` | str enum | 29 stable codes, including `INVALID_REQUEST`, `NO_CANDIDATES`, `AMBIGUOUS_CANDIDATES`, `PLAN_LIMIT_EXCEEDED`, `GENERATOR_TIMEOUT`, `GENERATOR_RATE_LIMITED`, and `GENERATOR_UNAVAILABLE` |

`allowed_operator_ids` on a request, and the same argument on `OpenAIPlanGenerator`, are authorization boundaries rather than filters.
Without one, package built-ins are limited to the `active_registry()` selection.
Records exclude response bodies, request payloads, credentials, and provider-specific exception text.

### Data context for planning

A generator that needs schema context receives a validated snapshot, never rows.

| Export | Kind | What it is |
|---|---|---|
| `DataScope` | frozen dataclass | The exact registry address to plan against, plus an advisory entity projection; `to_dict()` serializes it |
| `DataContextSnapshot` | frozen dataclass | A validated, immutable entity-and-attribute projection for one scope; `to_dict()` serializes it |
| `DataContextProvider` | protocol | `collect(scope) -> DataContextSnapshot` |
| `RegistryDataContextProvider` | class | Collects a bounded snapshot from three read-only registry list operations |

`RegistryDataContextProvider` defaults to 32 entities, 64 attributes per entity, 512 attributes in total, 512 description characters, and 131072 serialized bytes.
It reads source properties, entity names, descriptions, and declared attribute types.
It reads no relations and no rows, and records `raw_rows: 0` in provenance.
A request carrying a `data_scope` requires a provider; a request without one never touches the registry.

---

## Registry seam

```python
from blue_data_ops import BlueDataRegistryProvider, DataRegistryProvider, RegistrySeam, resolve_registry
```

`blue_data_ops.data` is the package's only `blue-data` import boundary.
`RegistrySeam` wraps a `blue-data` `DataRegistry` and keeps the argument shapes the operators were written against, including the per-call `rebuild` flag the wrapped registry has no parameter for.

| Seam call | Purpose |
|---|---|
| `create_source_database(source, database, ...)` | Declare a database under a registered source |
| `create_source_database_collection_entity(source, database, collection, entity, ...)` | Declare an entity |
| `set_source_database_description(...)` / `set_source_database_collection_entity_description(...)` | Attach descriptions used by discovery |
| `register_source(source)` / `connect_source(source)` / `get_source_properties(source)` | Source lifecycle |
| `list_collection_entities(...)` / `list_entity_attributes(...)` | Read registered metadata only, without connecting or querying |
| `execute_query(query, source, database=None, collection=None, optional_properties={})` | Run a query through the registry |
| `get_data_source_schema(source, database, collection, protocol=None, format="dict")` | Read a source schema |
| `set_record_data(...)` / `get_record(...)` | Registry record storage |
| `search_records(...)` / `search_records_hierarchical(...)` | Metadata search, normalized to flat records with an inverted score where lower is closer |

`resolve_registry(properties, provider=None)` takes the first path that works: an injected `RegistrySeam` under `properties["data_registry"]`, then a raw `DataRegistry` there (which it wraps), then construction from `properties["platform.name"]` and `properties["data_registry.name"]` through the provider.
It returns `None` when nothing resolves.
Supplying your own `DataRegistryProvider` is covered in [extending.md](extending.md).

---

## LLM client support

```python
from blue_data_ops.llm import CachingLLMClientProvider, LLMClient, LLMError, resolve_llm_client
```

The LiteLLM-backed client the `nl2*` and `semantic_*` operators use.
The module imports without the `[llm]` extra; LiteLLM is imported lazily at the first provider call, so a missing extra surfaces there rather than at import time.

| Export | Kind | What it is |
|---|---|---|
| `LLMClient(name, properties=None)` | class | Builds a templated request and executes it. `execute_api_call(input, properties=None, additional_data=None)` is synchronous; `aexecute_api_call(...)` is the async form with bounded concurrency |
| `UsageRecord` | dataclass | `model`, `prompt_tokens`, `completion_tokens`, `cost`, `latency_seconds`, `cache_hit` |
| `UsageLedger` | class | `records`, `add(record)`, and the `total_cost` and `total_tokens` properties. One record per call, cache hits included |
| `LLMError` | exception | Transport failures and rejected adapter configuration. Carries `message`, `code`, `provider_error` |
| `LLMClientProvider` | abstract class | `get_client(properties) -> LLMClient` |
| `CachingLLMClientProvider` | class | Opt-in per-config client reuse; the cache's lifetime belongs to whoever holds the provider |
| `resolve_llm_client(properties, provider=None)` | function | An injected `properties["llm_client"]`, then the provider, then a fresh client |

The default lifetime is one client per invocation rather than a module-level singleton.
Built-in operators call `resolve_llm_client` without a provider, so inside an operator call the reachable seam is `properties["llm_client"]`.
Accepted `llm.*` override keys are `model`, `stream`, `max_tokens`, `temperature`, `cache`, `cache_dir`, `max_parallel`, and `rate_limit`; an unknown one raises `LLMError` with code `bad_override`.
The last four are consumed by the client and never forwarded to the provider.
A prefixed namespace admits the generation parameters and nothing else.
A property outside that set — `api_key`, `api_base`, `base_url`, `custom_llm_provider`, the Vertex and Bedrock selectors, and every other routing or identity field — raises `LLMError` with code `reserved_field`, as does one that would substitute the provider's answer, `mock_response` or `mock_timeout`.
`model` is additionally held to the deployment's provider, and one that resolves elsewhere is refused with `model_not_allowed`.
A bare model name selects a provider too, so the check is on the outcome — what the provider library would actually dispatch to — as well as on the spelling.
A slash is not itself a provider prefix: an identifier such as `accounts/fireworks/models/llama-v3` names a model and is accepted, while `azure/my-deploy` is not, because the deployment names Azure and the property names the deployment.
A third code, `bad_provider`, is deployment misconfiguration rather than a caller error: it names `BLUE_DATA_LLM_PROVIDER` and the value it was given when that value is not a provider the library serves, so the misconfiguration is reported where it was made rather than deep inside the provider call.
Both refusals happen before the cache key is built.
Supply credentials through the provider's own environment variables, which is now the only route; never through a property, and never through a committed property file.

---

## Utilities

```python
from blue_data_ops.utils import safe_substitute, validate_parameter_type
```

The Blue-compatible helpers the operator surface depends on.
[`lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md) is the source of truth for which Blue helpers are deliberately absent.

| Export | Signature | Purpose |
|---|---|---|
| `string_to_python_type` | `(type_str) -> Any` | Blue type string to a real Python type for Pydantic |
| `validate_parameter_type` | `(value, expected_type) -> bool` | Check one value against one Blue type string |
| `create_pydantic_model` | `(parameters) -> type[BaseModel]` | Build a model from `{name: {"type", "required"}}` definitions |
| `annotation_to_type_str` | `(annotation) -> str` | An `inspect` annotation to a Blue type string |
| `extract_signature` | `(function, mcp_format=False) -> dict[str, Any]` | A `{parameters, returns}` description of a callable |
| `convert_type_string_to_mcp` | `(type_str) -> dict[str, Any]` | A Blue type string to an MCP JSON-schema shape |
| `merge_json` | `(original_json, update_json) -> Any` | `jsonmerge`'s default object-merge strategy |
| `json_query` | `(...) -> Any` | JSONPath read |
| `json_query_set` | `(...) -> Any` | JSONPath write at every match |
| `safe_substitute` | `(template, **kwargs) -> str` | Repeated `string.Template` and Jinja substitution until stable |
| `create_uuid` | `() -> str` | A short lowercase-hex identifier |
| `split_ids` | `(canonical_id) -> list[str]` | Split a canonical ID into components |
| `extract_sid` | `(canonical_id) -> str` | The trailing name and id pair as a short id |
| `extract_name_id` | `(canonical_id) -> list[str]` | The trailing `(name, id)` components |
| `extract_prefix` | `(canonical_id) -> str \| None` | Everything before that trailing pair |
| `concat_ids` | `(*ids) -> str` | Join components with the canonical separator |

---

## Not part of the public API

One interface named in the interface spec is not built.
There is no `platform/api/`, so there is no REST API; [api.md](api.md) is the placeholder for it.

The `blue-ops` command is a separate distribution with its own reference, [cli.md](cli.md); nothing on this page is reachable through it except by running an operator.

Module members prefixed with an underscore, and the outcome operator classes behind the `@3.0.0` cards, are internal.
Reach them through a registry, not by importing them.

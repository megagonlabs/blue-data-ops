# blue-data-ops — API / Interface Spec

The interfaces available to consumers of this repository.

Three external interfaces exist.
The **Python library** is canonical: everything else delegates to it.
The **MCP server** is a thin adapter in a second distribution, `blue-data-ops-mcp`, which holds no business logic of its own and projects the library's own result contract onto the wire.
The **`blue-ops` command** is a third distribution, `blue-data-ops-cli`, on the same terms.

There is no REST API.
Section 3 records that boundary.

Database credentials and permissions belong to the deployment. The MCP server binds to loopback by default.
MCP requests over HTTP/SSE require a shared API key unless the host explicitly opts out;
stdio relies on local process access.

---

## 1. Python Library

`blue_data_ops` and its subpackages are the whole surface.
All three distributions ship `py.typed`, so a consumer's type checker reads the annotations without stubs.

### 1.1 Namespace layout

| Import path | Exports | Holds |
|---|---|---|
| `blue_data_ops` | 49 | the 32 concrete operator classes, the `Operator` base, the result and error types, the registry seam, and `utils` |
| `blue_data_ops.operators` | 65 | the operator classes including `SklearnEstimator` and `OperatorDiscoverOperator`, plus the registry, cards, factories, discovery, the type aliases, and the operator exceptions |
| `blue_data_ops.plan` | 38 | pipelines, the executor, the planner, generators, and planning records |
| `blue_data_ops.operator_skills` | 12 | the resource loader, its views, and its bounds |
| `blue_data_ops.llm` | 7 | the LLM client, its provider seam, usage records, and `LLMError` |
| `blue_data_ops.data` | 4 | the `blue-data` registry seam and its provider |
| `blue_data_ops.tools` | 1 | `Tool` |
| `blue_data_ops.utils` | 16 | the platform-compatible helper functions |

The top level is the convenience surface: a caller who wants to run an operator imports from `blue_data_ops`, and a caller who wants the registry imports from `blue_data_ops.operators`.
Nothing is re-exported upward from `plan`, `operator_skills`, or `llm`.

### 1.2 The top-level namespace

Thirty-two concrete operator classes:

`ArgmaxOperator`, `ArgminOperator`, `AvgOperator`, `ClassifyOperator`, `ClusterOperator`, `CreateDatabaseOperator`, `CreateTableOperator`, `DataDiscoverOperator`, `DeleteOperator`, `InsertOperator`, `InsertTableOperator`, `IntersectOperator`, `JoinOperator`, `MaxOperator`, `MinOperator`, `NL2BNOperator`, `NL2LLMOperator`, `NL2SQLOperator`, `NormalizeTextOperator`, `ProjectOperator`, `SegmentTextOperator`, `SelectOperator`, `SemanticExtractOperator`, `SemanticFilterOperator`, `SemanticJoinOperator`, `SemanticProjectOperator`, `SemanticTransformOperator`, `SumOperator`, `UnionOperator`, `VectorEmbedOperator`, `VectorSearchOperator`, `VectorSimilarityOperator`

And sixteen other names:

| Name | Kind | Purpose |
|---|---|---|
| `Operator` | abstract class | the base every operator inherits |
| `Tool` | class | the metadata and signature layer under `Operator` |
| `FunctionResult` | named tuple | `(output_data, output_attributes)`, returned by the internal execution hook |
| `ValidationResult` | named tuple | `(ok, reason)`, returned by the internal validation hook |
| `ExecMeta` | named tuple | `(is_empty, errors, logs, traces)`, the third element of a `run()` result |
| `ErrorRecord` | named tuple | one structured failure |
| `ErrorCategory` | str enum | `RECOVERABLE`, `FAILED`, `TIMEOUT` |
| `ErrorCode` | str enum | nine codes |
| `ErrorStage` | str enum | `DEFAULTS`, `VALIDATE`, `EXECUTE`, `NORMALIZE`, `REFINE` |
| `ABSENT` | sentinel | separates "declares no default" from "defaults to `None`" |
| `RegistrySeam` | class | the facade over a `blue-data` registry |
| `DataRegistryProvider` | abstract class | the provider contract for constructing a registry |
| `BlueDataRegistryProvider` | class | the default provider, caching one registry per name pair |
| `resolve_registry` | function | resolve an injected registry or construct one from properties |
| `BlueDataOpsDeprecationWarning` | warning class | the category the 2.x lifecycle surface used. 3.0 emits it nowhere and keeps it importable. |
| `utils` | module | the platform-compatible helpers, re-exported as a submodule |

The 33rd active operator's class, `SklearnEstimator`, is reachable from `blue_data_ops.operators` rather than from the top level, and its class name has no `Operator` suffix.
Both are deliberate: it arrived after the top-level surface was settled, and the registry is the intended way to reach it.

Every type name in this table is also importable from `blue_data_ops.operators`, except `Tool`, `RegistrySeam`, `DataRegistryProvider`, `BlueDataRegistryProvider`, `resolve_registry`, `BlueDataOpsDeprecationWarning`, and `utils`, which live in `blue_data_ops.tools`, `blue_data_ops.data`, and the package root.

### 1.3 Operator names and active versions

Each class maps to one logical operator name, and each name has exactly one active exact ID.
Thirty-three names, grouped as [`../lib/OPERATORS.md`](../lib/OPERATORS.md) groups them:

| Class | Name | Active ID | Extra |
|---|---|---|---|
| `SelectOperator` | `select` | `select@2.0.0` | — |
| `ProjectOperator` | `project` | `project@3.0.0` | — |
| `DeleteOperator` | `delete` | `delete@2.0.0` | — |
| `InsertOperator` | `insert` | `insert@3.0.0` | — |
| `JoinOperator` | `join` | `join@3.0.0` | — |
| `UnionOperator` | `union` | `union@2.0.0` | — |
| `IntersectOperator` | `intersect` | `intersect@3.0.0` | — |
| `ArgmaxOperator` | `argmax` | `argmax@2.0.0` | — |
| `ArgminOperator` | `argmin` | `argmin@2.0.0` | — |
| `MaxOperator` | `max` | `max@3.0.0` | — |
| `MinOperator` | `min` | `min@3.0.0` | — |
| `AvgOperator` | `avg` | `avg@3.0.0` | — |
| `SumOperator` | `sum` | `sum@2.0.0` | — |
| `NormalizeTextOperator` | `normalize_text` | `normalize_text@2.0.0` | — |
| `SegmentTextOperator` | `segment_text` | `segment_text@2.0.0` | — |
| `ClassifyOperator` | `classify` | `classify@3.0.0` | `ml` |
| `ClusterOperator` | `cluster` | `cluster@3.0.0` | `ml` |
| `SklearnEstimator` | `sklearn_estimator` | `sklearn_estimator@2.0.0` | `ml` |
| `VectorEmbedOperator` | `vector_embed` | `vector_embed@3.0.0` | `vector` |
| `VectorSearchOperator` | `vector_search` | `vector_search@3.0.0` | `vector` |
| `VectorSimilarityOperator` | `vector_similarity` | `vector_similarity@3.0.0` | `vector` |
| `NL2LLMOperator` | `nl2llm` | `nl2llm@3.0.0` | `llm` |
| `NL2SQLOperator` | `nl2sql` | `nl2sql@4.0.0` | `llm` |
| `NL2BNOperator` | `nl2bn` | `nl2bn@3.0.0` | `llm` |
| `SemanticExtractOperator` | `semantic_extract` | `semantic_extract@3.0.0` | `llm` |
| `SemanticFilterOperator` | `semantic_filter` | `semantic_filter@3.0.0` | `llm` |
| `SemanticJoinOperator` | `semantic_join` | `semantic_join@3.0.0` | `llm` |
| `SemanticProjectOperator` | `semantic_project` | `semantic_project@3.0.0` | `llm` |
| `SemanticTransformOperator` | `semantic_transform` | `semantic_transform@3.0.0` | `llm` |
| `CreateDatabaseOperator` | `create_database` | `create_database@2.0.0` | — |
| `CreateTableOperator` | `create_table` | `create_table@2.0.0` | — |
| `InsertTableOperator` | `insert_table` | `insert_table@3.0.0` | — |
| `DataDiscoverOperator` | `data_discover` | `data_discover@2.0.0` | — |

A class name resolves to the `@2.0.0` implementation when constructed directly, because a `@3.0.0` outcome implementation is a separate private class the registry selects.
Construct through `active_registry().resolve(...)` to get the active version.
Per-operator attributes, tags, and documented outcomes are in [`../lib/OPERATORS.md`](../lib/OPERATORS.md), which is generated and is the source of truth for that detail.

### 1.4 The operator call surface

```python
class Operator(Tool, ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    attributes: ClassVar[dict[str, AttributeSpec]]
    PROPERTIES: ClassVar[dict[str, Any]]

    def __init__(
        self,
        name: str | None = None,
        function: Callable[..., Any] | None = None,
        description: str | None = None,
        properties: Properties | None = None,
        validator: Callable[..., Any] | None = None,
        explainer: Callable[..., Any] | None = None,
    ) -> None: ...

    @property
    def operator_id(self) -> str: ...

    # Canonical structured boundary
    def run(self, input_data: DataBundle, attributes: Attributes, properties: Properties | None = None) -> tuple[DataBundle, Attributes, ExecMeta]: ...

    # Raw compatibility paths
    def apply(self, input_data: DataBundle, attributes: Attributes, properties: Properties | None = None) -> DataBundle: ...
    def invoke(self, input_data: DataBundle, attributes: Attributes, properties: Properties | None = None) -> DataBundle | None: ...
    def validate(self, input_data: DataBundle, attributes: Attributes, properties: Properties | None = None) -> bool: ...
    def explain(self, output: DataBundle, input_data: DataBundle, attributes: Attributes) -> dict[str, Any]: ...

    # Declared-attribute accessors
    def get_attributes(self) -> dict[str, dict[str, Any]]: ...
    def get_attribute(self, attribute: str) -> dict[str, Any] | None: ...
    def get_attribute_type(self, attribute: str) -> Any: ...
    def get_attribute_description(self, attribute: str) -> Any: ...
    def update_attributes(self, attributes: dict[str, dict[str, Any]] | None = None) -> None: ...
    def set_attribute_description(self, attribute: str, description: str) -> None: ...
    def set_attribute_required(self, attribute: str, required: bool) -> None: ...
    def set_attribute_hidden(self, attribute: str, hidden: bool) -> None: ...
    def is_attribute_required(self, attribute: str) -> Any: ...
    def is_attribute_hidden(self, attribute: str) -> Any: ...
    def is_required(self, attribute: str) -> bool | None: ...
    def default_of(self, attribute: str) -> Any: ...
    def get_hyperparameters(self) -> dict[str, Any]: ...
    def update_hyperparameters(self, hyperparameters: dict[str, Any] | None = None) -> None: ...

    @classmethod
    def is_operator(cls, value: object) -> bool: ...
    @classmethod
    def get_tool_type(cls, value: object) -> str: ...
```

Four call paths, and the difference between them is what wraps the transform rather than what the transform does:

| Call | Returns | Materializes defaults | Validates | Contains exceptions |
|---|---|---|---|---|
| `run()` | `(output_data, output_attributes, exec_meta)` | yes | yes, structured | yes, as an `ErrorRecord` |
| `apply()` | `output_data` | no | no | no, they propagate |
| `invoke()` | `output_data` or `None` | no | yes, boolean | no, they propagate |
| `validate()` | `bool` | no | yes, boolean | no, they propagate |

Every built-in defines `apply()` as `self._execute(...).output_data`, so `run()` and `apply()` run the same transform body.
`run()` adds default materialization, structured validation, result type checking, empty-output normalization, and the deadline.

`run()` never raises for an operator problem.
A successful empty result is `[[]]` with `is_empty=True` and no records; a failure is `[[]]` with one record and `is_empty=False`.
Set the deadline per call with `properties={"execution.timeout_seconds": 5.0}`; the wrapper runs the call in a single worker thread and never retries.
The legacy `properties["timeout"]` field stays observable and sets nothing.

`operator_id` is the pinned ID the registry bound the instance to.
An instance constructed directly and never registered reports `name@2.0.0`, so an error record from a direct call still names something exact.

A worked call:

```python
from blue_data_ops.operators import active_registry

operator = active_registry().resolve("select@2.0.0")
data = [[{"name": "a", "score": 3}, {"name": "b", "score": 9}]]
attributes = {"operand_key": "score", "operand": ">", "operand_val": 5}

output_data, output_attributes, meta = operator.run(data, attributes)
assert output_data == [[{"name": "b", "score": 9}]]
assert output_attributes == {}
assert meta.errors == [] and meta.is_empty is False

rejected = operator.run(data, {})
assert rejected[0] == [[]]
assert rejected[2].errors[0].code.value == "INVALID_INPUT"
assert rejected[2].errors[0].stage.value == "VALIDATE"
```

### 1.5 The Tool metadata surface

`Operator` inherits the platform-compatible metadata layer, so code written against Blue's Tool surface keeps working.

```python
class Tool:
    PROPERTIES: ClassVar[dict[str, Any]]

    @property
    def properties(self) -> dict[str, Any]: ...

    def get_properties(self, properties: dict[str, Any] | None = None) -> dict[str, Any]: ...
    def get_signature(self) -> dict[str, Any]: ...
    def get_parameters(self) -> dict[str, Any] | None: ...
    def get_parameter(self, parameter: str) -> dict[str, Any] | None: ...
    def get_parameter_type(self, parameter: str) -> Any: ...
    def set_parameter_description(self, parameter: str, description: str) -> dict[str, Any] | None: ...
    def set_parameter_required(self, parameter: str, required: bool) -> dict[str, Any] | None: ...
    def set_parameter_hidden(self, parameter: str, hidden: bool) -> dict[str, Any] | None: ...
    def is_parameter_required(self, parameter: str) -> Any: ...
    def is_parameter_hidden(self, parameter: str) -> Any: ...
    def get_returns(self) -> dict[str, Any] | None: ...
    def get_returns_type(self) -> Any: ...
    def set_returns_description(self, description: str) -> dict[str, Any] | None: ...
```

`get_properties(overrides)` merges without mutating the live mapping.
The signature is generated with the platform's own rules, including how it renders annotated parameters and how it treats a falsy default.
The attribute definitions are attached under `parameters.attributes.properties` with each type string converted to its MCP form; the shapes are in [10-data-model.md](10-data-model.md).

### 1.6 Registry and discovery

Everything in this section is imported from `blue_data_ops.operators`.

```python
def default_registry(**versions: Any) -> OperatorRegistry: ...
def active_registry() -> OperatorRegistry: ...
def versioned_registry() -> OperatorRegistry: ...

class OperatorRegistry:
    def register(self, operator: Operator, version: str, tags: Sequence[str] = (), *, when_to_invoke: str = "", deprecated: bool = False) -> OperatorCard: ...
    def resolve(self, operator_id: str) -> Operator: ...
    def get_card(self, operator_id: str) -> OperatorCard | None: ...
    def find(self, query: str, tags: Sequence[str] | None = None) -> list[OperatorCard]: ...
    def find_latest(self, name: str) -> OperatorCard | None: ...
    def list_cards(self) -> list[OperatorCard]: ...

def upgrade_legacy_operator_id(reference: str, registry: OperatorRegistry, *, target_version: str, aliases: dict[str, str] | None = None) -> str: ...
```

| Factory | Cards | Use |
|---|---|---|
| `active_registry()` | 33 exact IDs, 12 at `@2.0.0`, 20 at `@3.0.0`, and `nl2sql@4.0.0` | ordinary discovery and execution |
| `versioned_registry()` | 88 cards: 33 at `@1.0.0`, 33 at `@2.0.0`, 21 at `@3.0.0`, and `nl2sql@4.0.0` | migration code that needs retained behavior |
| `default_registry(**versions)` | 33 raw cards at `@1.0.0`, overridable per name | the raw compatibility view |

Each call returns a fresh registry holding its own operator instances, so two registries never share state.

`resolve()` accepts only `name@<MAJOR.MINOR.PATCH>` and raises `ResolveError` for a bare name, a malformed version, or an unregistered ID.
There is no latest-version fallback at resolution time.
`register()` raises `ValueError` for a non-semver version, for an operator with no name, and for an ID that is already registered, because registrations are immutable and there is no deregistration.

`find()` applies the exact AND tag filter first, then scores text case-insensitively: name 10, any tag 8, invocation guidance 6, description 5, each field scoring at most once.
Only positive scores are returned, ties order by name then descending version.
A blank query with tags is tag-only discovery, ordered by name then descending version; a blank query with no tags returns `[]`.
A malformed filter token raises `DiscoveryError` rather than matching nothing: a token must be non-empty after stripping, carry no internal whitespace, and contain a hyphen.

`upgrade_legacy_operator_id` converts a bare name, an explicit alias, or a legacy `/server/<server>/(operator|tool)/<name>` route into a registered pinned ID, and raises `UpgradeError` for a missing, malformed, ambiguous, or unregistered target.
It is never called implicitly; neither `resolve()` nor `DataPipeline.from_dict()` invokes it.

Embedding discovery is opt-in and caller-supplied:

```python
class OperatorEmbedder(Protocol):
    @property
    def space_id(self) -> str: ...
    def __call__(self, texts: tuple[str, ...]) -> Sequence[Sequence[float]]: ...

class OperatorEmbeddingIndex:
    @classmethod
    def build(cls, registry: OperatorRegistry, embedder: OperatorEmbedder) -> OperatorEmbeddingIndex: ...
    def find(self, query: str, tags: Sequence[str] | None = None) -> list[OperatorCard]: ...
```

`build()` sends every card's name, invocation guidance, description, and ordered tags to the embedder in one batch.
`find()` filters by exact AND tags, then ranks by cosine similarity with no threshold and no limit; the caller truncates.
The constructor raises `TypeError` — use `build()`.
An invalid vector, a failing callback, a registry that changed since the snapshot, or a mismatched backend raises `EmbeddingDiscoveryError`, whose `reason` is one of `BUILD_FAILED`, `QUERY_FAILED`, `INVALID_RESULT`, `STALE_INDEX`, `BACKEND_MISMATCH`, `MODE_UNAVAILABLE`, `INVALID_MODE`.
The package neither chooses nor installs an embedding model.

`OperatorDiscoverOperator` wraps both search modes as an operator, for a caller that wants discovery as a pipeline step.
It carries no discovery metadata, is in no registry factory, and is not served over MCP.

### 1.7 The data registry seam

Imported from `blue_data_ops` or `blue_data_ops.data`.

```python
class DataRegistryProvider(ABC):
    @abstractmethod
    def get_registry(self, platform_name: str, registry_name: str, properties: Properties) -> RegistrySeam: ...

class BlueDataRegistryProvider(DataRegistryProvider): ...

def resolve_registry(properties: Properties | None, provider: DataRegistryProvider | None = None) -> RegistrySeam | None: ...
```

`RegistrySeam` is the facade the registry-backed operators call.
Its methods cover source registration and connection, database and collection-entity creation, description setting, record read and write, entity and attribute listing, schema retrieval, query execution, and record search including the hierarchical form.
Six operators use it: `create_database`, `create_table`, `insert_table`, `data_discover`, `nl2bn`, and `nl2sql`.

`resolve_registry` resolves in this order: an injected `RegistrySeam` under `properties["data_registry"]`, a raw `blue-data` `DataRegistry` under the same key which it wraps, then the pair `properties["platform.name"]` and `properties["data_registry.name"]` handed to the provider.
It returns `None` when none of those is present.
An invalid injected value falls through to the construction keys rather than raising.

These two modules are the only place in the package that imports `blue_data_ops`'s one internal dependency.
Behavioral differences from the platform's own registry, search scoring in particular, are recorded in [`../lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md).

### 1.8 Pipelines and planning

Imported from `blue_data_ops.plan`.

```python
class DataPipeline(Plan):
    def __init__(
        self,
        id: str | None = None,
        label: str | None = None,
        type: str = "DATA_PIPELINE",
        properties: dict[str, Any] | None = None,
        attributes: dict[str, Any] | None = None,
        path: str | None = None,
        plan_provenance: str | None = None,
        plan_input: str | Node | None = None,
        plan_output: str | Node | None = None,
        sync_backend: SyncBackend | None = None,
        auto_sync: bool = False,
        sync: bool | None = None,
    ) -> None: ...

    def define_input(self, label: str | None = None, value: Any = None, provenance: str | None = None, properties: dict[str, Any] | None = None, sync: bool | None = None) -> Node: ...
    def define_output(self, label: str | None = None, value: Any = None, provenance: str | None = None, properties: dict[str, Any] | None = None, sync: bool | None = None) -> Node: ...
    def define_operator(self, name: str, label: str | None = None, attributes: dict[str, Any] | None = None, properties: dict[str, Any] | None = None, sync: bool | None = None) -> Node: ...
    def connect_nodes(self, f: str | Node, t: str | Node, sync: bool | None = None) -> None: ...
    def set_plan_input(self, i: str | Node | None, sync: bool | None = None) -> None: ...
    def set_plan_output(self, o: str | Node | None, sync: bool | None = None) -> None: ...
    def merge(self, merge_plan: DataPipeline, sync: bool | None = None) -> None: ...
    def to_dict(self) -> PlanRecord: ...
    @classmethod
    def from_dict(cls, data: PlanRecord, path: str | None = None, sync_backend: SyncBackend | None = None, auto_sync: bool = False, sync: bool | None = None) -> DataPipeline: ...
    def to_jsonform_diagram_json(self) -> dict[str, Any]: ...
```

`define_operator` requires a pinned `name@<MAJOR.MINOR.PATCH>` and raises `ValueError` for a bare name, a deployment route, or a host address, so a serialized plan stays deployment-neutral.
`to_dict()` returns the live record rather than a copy; round-trip it through `from_dict()` for an independent snapshot.
`sync_backend` is an optional callback taking `(path, key, value)`; with no callback there is no state propagation and the `plan` package has no bus, stream, or connection dependency.
`to_jsonform_diagram_json()` renders nodes and edges for a diagram consumer, deriving a progress value from node status when none is set.

```python
class PipelineExecutor:
    def __init__(self, registry: OperatorRegistry) -> None: ...
    def preflight(self, pipeline: DataPipeline, properties: Properties | None = None) -> PipelinePreflight: ...
    def execute(self, pipeline: DataPipeline, input_data: DataBundle, properties: Properties | None = None) -> PipelineRun: ...
```

`preflight()` resolves every pinned ID and computes the execution order without running an operator.
Both methods raise `PipelineError` for a graph with no nodes, a missing declared input or output, more than one of either, an unsupported node type, malformed or duplicate or non-reciprocal edges, a dangling reference, a cycle, a node that is not on a path from input to output, a node that has already started, an operator node with no entity or with malformed call data, an unresolvable ID, or input that is not a bundle.
An operator failure after preflight is not raised: it lands in `PipelineRun`.

Execution runs nodes in topological order, aggregates each node's predecessors into one bundle in predecessor order, stops at the first structured operator failure, and marks unfinished nodes `FAILED`.
It mutates node values and statuses on the plan it was given.

```python
class PipelinePlanner:
    def __init__(
        self,
        registry: OperatorRegistry,
        generator: PlanGenerator,
        selector: RequireSinglePlan | None = None,
        data_context_provider: DataContextProvider | None = None,
        *,
        embedding_index: OperatorEmbeddingIndex | None = None,
    ) -> None: ...

    def discover(self, request: PlanningRequest) -> DiscoverySnapshot: ...
    def plan(self, request: PlanningRequest) -> PlanningResult: ...
    def execute(self, planning: PlanningResult, input_data: DataBundle, properties: Properties | None = None) -> PipelineRun: ...
    def run(self, request: PlanningRequest, input_data: DataBundle, properties: Properties | None = None) -> PlannerRun: ...
```

`plan()` runs discovery, bounded data-context collection, generation, selection, compilation, and preflight, then returns a `PlanningResult`.
`run()` adds execution.
`execute()` replays a prior result against a fresh copy of its compiled pipeline.
`discover()` is the compatibility discovery pass over exact `@2.0.0` cards including lifecycle history, and it is not what `plan()` uses.

Every failure raises `PlanningError`, a `ValueError` subclass carrying `error.record`.
That is the one place the package reports a recoverable outcome by raising, because planning produces either a compiled pipeline or nothing.

Two protocols and the shipped implementations:

```python
class PlanGenerator(Protocol):
    def generate(self, request: PlanningRequest, discovery: DiscoverySnapshot, data_context: DataContextSnapshot | None) -> Sequence[PlanDraft]: ...

class DataContextProvider(Protocol):
    def collect(self, scope: DataScope) -> DataContextSnapshot: ...
```

| Name | Kind | Behavior |
|---|---|---|
| `RulePlanGenerator(rules=None)` | generator | evaluates caller rules in order and keeps their drafts. The default rule recognizes the built-in filter-then-average request. |
| `OpenAIPlanGenerator(model, *, registry, allowed_operator_ids, ...)` | generator | one non-streaming Responses call per `generate()`, against the packaged strict schema. Requires the OpenAI SDK (`openai` or `llm` extra). |
| `RequireSinglePlan()` | selector | accepts exactly one draft; zero raises `NO_CANDIDATES` and several raise `AMBIGUOUS_CANDIDATES` |
| `RegistryDataContextProvider(registry, *, ...)` | context provider | a bounded schema snapshot from three read-only registry calls: source properties, collection entities, entity attributes. Reads no rows. |
| `SELECT_THEN_AVERAGE_TEMPLATE` | rule template | the shipped filter-then-average template |
| `project_then_aggregate_template(name)` | factory | a project-then-aggregate template for `"avg"`, `"sum"`, `"min"`, or `"max"` |

`OpenAIPlanGenerator` defaults to `send_data_context=False`, `max_candidates=1`, `timeout_seconds=60.0`, and `max_output_tokens=4096`.
It rejects a fine-tuned model name locally, because the packaged schema uses array bounds the fine-tuned Structured Outputs subset does not support.
Passing a schema snapshot without setting `send_data_context=True` raises `DATA_CONTEXT_DISCLOSURE_REQUIRED` before the SDK import and before any provider traffic.

`RegistryDataContextProvider` defaults to 32 entities, 64 attributes per entity, 512 attributes in total, 512 description characters, and 131072 serialized bytes.
A request with a `data_scope` requires a provider; a request without one never touches the registry.

The record shapes for all of this are in [10-data-model.md](10-data-model.md); [06-library.md](06-library.md) covers the class layout.

### 1.9 Operator resources

Imported from `blue_data_ops.operator_skills`.

```python
class OperatorSkillLoader:
    def __init__(self, registry: OperatorRegistry) -> None: ...
    def available_operator_ids(self) -> tuple[str, ...]: ...
    def describe(self, operator_id: str) -> OperatorSkillDescriptor: ...
    def load(self, operator_id: str, level: int = 2) -> OperatorSkillView: ...
    def read(self, operator_id: str, kind: str) -> OperatorResource: ...

def snapshot_attribute_specs(operator: Operator) -> dict[str, AttributeSpec]: ...

INDEX_BYTE_LIMIT = 4_096
MANIFEST_BYTE_LIMIT = 4_096
RESOURCE_BYTE_LIMIT = 16_384
JSON_DEPTH_LIMIT = 4
```

Fifty-five packages ship, 33 at `@2.0.0`, 21 at `@3.0.0`, and `nl2sql@4.0.0`, covering every active exact ID, the retained `@2.0.0` set and `nl2sql@3.0.0`.
Every package declares levels 2 and 3; none declares level 4.

| Level | Loads |
|---|---|
| 2 | the card, the live attribute schema, and `Operator.md` |
| 3 | level 2 plus `examples.md` |
| 4 | level 3 plus `history.md`. No package declares it, so requesting it raises `NOT_AVAILABLE`. |

Every failure is `OperatorSkillLoadError`, a `ValueError` subclass carrying a stable `code`:

| Code | Raised when |
|---|---|
| `INVALID_OPERATOR_ID` | the ID is not an exact path-safe pinned ID. Checked before the index is read. |
| `NOT_AVAILABLE` | no package for that ID, an unsupported level, an unavailable resource kind, or an unreadable package root |
| `BINDING_MISMATCH` | the registry card and the requested ID disagree, or a manifest names a different ID |
| `MANIFEST_INVALID` | the index or a manifest violates its closed shape. One malformed index row fails every index-backed call. |
| `RESOURCE_INVALID` | an unsafe path, a digest mismatch, or text that is not valid UTF-8 |
| `TRUST_REQUIRED` | the card is not a package-owned built-in of this registry, or the registry is not an exact `OperatorRegistry` |
| `SCHEMA_INVALID` | the operator's live attribute projection could not be snapshotted |

There is no cache.
Calling these methods in sequence rereads the index, and a package that changes between two calls fails the second.
Loading a resource does not invoke the operator and does not add its text to planner or provider input.
There is no latest-version fallback.

### 1.10 The LLM client

Imported from `blue_data_ops.llm`.

```python
class LLMClient:
    def __init__(self, name: str, properties: dict[str, Any] | None = None) -> None: ...
    def execute_api_call(self, input: Any, properties: dict[str, Any] | None = None, additional_data: dict[str, Any] | None = None) -> Any: ...

class LLMClientProvider(ABC):
    @abstractmethod
    def get_client(self, properties: dict[str, Any]) -> LLMClient: ...

class CachingLLMClientProvider(LLMClientProvider): ...

def resolve_llm_client(properties: dict[str, Any] | None, provider: LLMClientProvider | None = None) -> LLMClient: ...
```

The client builds a templated request, sends it through LiteLLM, and extracts the response through a configured output path.
It records one `UsageRecord` per call — model, prompt and completion tokens, cost, latency, and cache-hit flag — on a `UsageLedger` exposing `total_cost` and `total_tokens`; accounting never raises, and an unconvertible token count is zero.

Controls are properties: `llm.cache`, `llm.cache_dir` (default `.blue-data-ops-cache`), `llm.max_parallel` (default 8), and `llm.rate_limit`.
A caller may inject a configured client through `properties["llm_client"]` to reuse one across calls; without one, the default lifetime is construct-per-call with nothing shared.

`LLMError` wraps transport and provider failures and rejected adapter configuration, carrying
`message`, `code`, `provider_error`, and `retryable`.
Templating failures before the provider boundary are not wrapped and propagate as they are.
This client is the operator-level LLM seam; the plan generator's OpenAI seam is separate, and nothing else in the package imports that SDK.

### 1.11 Utilities

`blue_data_ops.utils` carries the platform helper functions the operator surface depends on, under the same names and with the same behavior.

| Function | Signature |
|---|---|
| `string_to_python_type` | `(type_str: str) -> Any` |
| `validate_parameter_type` | `(value: Any, expected_type: str \| None) -> bool` |
| `create_pydantic_model` | `(parameters: Dict[str, Any]) -> type[BaseModel]` |
| `annotation_to_type_str` | `(annotation: Any) -> str` |
| `convert_type_string_to_mcp` | `(type_str: str) -> dict[str, Any]` |
| `extract_signature` | `(function: Callable[..., Any], mcp_format: bool = False) -> dict[str, Any]` |
| `merge_json` | `(original_json: Any, update_json: Any) -> Any` |
| `json_query` | `(json_object: dict[str, Any], json_path_query: str, single: bool = True, default: Any = None) -> Any` |
| `json_query_set` | `(json_object: dict[str, Any], attribute: str, value: Any, context: str = "$") -> None` |
| `safe_substitute` | `(template: str, **kwargs: Any) -> str`; one dollar-placeholder pass, literal inserted data and Jinja syntax |
| `create_uuid` | `() -> str` |
| `concat_ids` | `(*ids: str) -> str` |
| `split_ids` | `(canonical_id: str) -> list[str]` |
| `extract_name_id` | `(canonical_id: str) -> list[str]` |
| `extract_prefix` | `(canonical_id: str) -> str \| None` |
| `extract_sid` | `(canonical_id: str) -> str` |

These modules do not import the platform.
The easy-to-miss behaviors — which `typing` objects `string_to_python_type` returns, how `validate_parameter_type` coerces, what `merge_json` raises on a scalar base — are recorded in [`../lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md), which is the source of truth for compatibility detail.

### 1.12 Exceptions

The library raises for a condition the caller must fix before anything can run, and returns a record for a condition that leaves a result to carry it.

| Exception | Base | Import from | Raised when |
|---|---|---|---|
| `OperatorError` | `Exception` | `blue_data_ops.operators` | base class for operator errors |
| `OperatorExecutionError` | `OperatorError` | `blue_data_ops`, `blue_data_ops.operators` | trusted-author fixed public execution diagnostic: `(message, *, suggestion=None, retryable=False)`; exact bounded primitives, canonical body only |
| `OperatorValidationError` | `OperatorError` | `blue_data_ops.operators` | exported for callers that raise from a custom validation path. Nothing in the package raises it. |
| `ResolveError` | `Exception` | `blue_data_ops.operators` | a pinned reference cannot be resolved. Recoverable. |
| `UpgradeError` | `Exception` | `blue_data_ops.operators` | a legacy reference cannot be upgraded. Recoverable. |
| `DiscoveryError` | `ValueError` | `blue_data_ops.operators` | a built-in metadata record or a filter token is malformed |
| `EmbeddingDiscoveryError` | `DiscoveryError`, `OperatorError` | `blue_data_ops.operators` | embedding discovery failed; carries `reason` |
| `OperatorSkillLoadError` | `ValueError` | `blue_data_ops.operator_skills` | resource loading failed; carries `code` |
| `PipelineError` | `ValueError` | `blue_data_ops.plan` | a pipeline or its input cannot be executed |
| `PlanningError` | `ValueError` | `blue_data_ops.plan` | planning failed; carries `record` |
| `LLMError` | `Exception` | `blue_data_ops.llm` | an LLM transport or provider failure, or rejected client configuration |

An operator failure is not in this table.
It arrives as an `ErrorRecord` inside `ExecMeta.errors`, and there is no exception to catch.
The platform's `BlueError` and its `ErrorLoom` mixin are not provided; [`../lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md) has the porting notes.

---

## 2. MCP Server

Implemented at `platform/ops-mcp/` as the distribution `blue-data-ops-mcp` and the module `blue_data_ops_mcp`, built on the official SDK's `FastMCP`.
It is an adapter: it selects operators, projects `run()` onto a wire envelope, and holds no operator logic.
[`../platform/ops-mcp/README.md`](../platform/ops-mcp/README.md) is the source of truth for its surface, and this section is the design-level summary.

### 2.1 The module surface

```python
from blue_data_ops_mcp import ACTIVE_OPERATOR_IDS, V2_OPERATOR_IDS, create_server, serve

def create_server(
    *,
    registry: OperatorRegistry | None = None,
    operator_ids: Iterable[str] | None = None,
    host: str | None = None,
    port: int | None = None,
    path: str = "/mcp",
) -> FastMCP[Any]: ...

def serve(*, registry=None, operator_ids=None, host=None, port=None, path="/mcp") -> None: ...
```

Four names, and the two constants are resolved lazily through a module `__getattr__` so importing the package does not import the SDK.

`create_server()` returns a configured server for embedding, and `serve()` constructs one and runs it.
The transport is stateful streamable HTTP and the defaults bind to `127.0.0.1:8010/mcp`.
`json_response` is false and `stateless_http` is false.
Review network exposure before changing the host.

| Constant | Contents |
|---|---|
| `ACTIVE_OPERATOR_IDS` | the 33 mixed-version IDs served by default, ordered by name |
| `V2_OPERATOR_IDS` | the 33 retained `@2.0.0` IDs, kept for callers that imported the old constant |

Both tuples are explicit adapter policy rather than a registry query or a semver maximum.
Neither is derived from the other.

### 2.2 The tool inventory

Thirty-three primary tools and no companions.
Each tool is named `ops_` plus its logical operator — `ops_select`, `ops_avg`, `ops_nl2sql` — so the protocol surface stays stable while the version behind a tool moves.
The prefix is the only part of a name this adapter chooses.
A client holds one flat tool namespace across every server it has loaded and this family ships a server per source, so a bare `select` or `create_database` collides; `create_database` already did, with `blue-data-user-source`'s tool of the same name and a different meaning.
`_meta.operator_id` stays unprefixed, because it names a core registration rather than a wire surface.
The default selection matches core `active_registry()`, so the library, the generated reference, and the protocol cannot disagree about which version is current.

Each tool's description is assembled from the card: the deprecation sentence when the card is flagged, then `when_to_invoke`, then the description, joined by blank lines.
No card in the shipped selection is flagged.

`_meta` carries the exact binding:

```json
{
  "operator_id": "max@3.0.0",
  "version": "3.0.0",
  "tags": [
    "domain-arithmetic", "flow-aggregate", "accepts-data",
    "produces-data", "capability-extrema", "capability-reduction"
  ]
}
```

`deprecated: true` is added when the card is flagged.
MCP has no server-side tag query, so a client calls `list_tools()`, reads `_meta.tags`, and filters locally.

### 2.3 Tool arguments

Every tool takes the same three arguments, generated from the operator's declared attributes:

| Argument | Required | Schema |
|---|---|---|
| `input_data` | yes | `array` of `array` of `object`, each object open |
| `attributes` | no, defaults to `{}` | `object` with `additionalProperties: true`, one named property per declared attribute, and `required` listing the attributes core declares required |
| `properties` | no, defaults to `null` | `object` with `additionalProperties: true`, or `null` |

All three arguments carry a description.

Each named attribute publishes its description, its JSON Schema `type` where core's declared type has a faithful one, and an `enum` where core's own validator closes the set.
Two attributes publish no type, because core resolves their declared type to `Any` and would accept anything: `ops_select`'s `operand_val` and `ops_semantic_filter`'s `return_idx`.
An enum is published only where core enforces one, never on the strength of a description — several attributes name their permitted values in prose and still accept others, and those stay open so the schema does not refuse a call the operator would run.
A default is published only for an optional attribute that both declares one and materializes it; a required attribute and an unmaterialized optional attribute publish none.
Published defaults are deep copies, never aliases of core state.

The container stays open, and the schema advertises the operator's contract without becoming a second enforcement point in front of `run()`: an unknown or wrong-typed attribute, or an omitted required one, still passes through to operator validation and comes back as a recoverable record.
What changed in adapter `1.0.0` is what a *client* can refuse before sending, not what the server accepts.

`ops_max` publishes this, with the three long argument descriptions elided at the `…` so the shape stays readable:

```json
{
  "type": "object",
  "title": "ops_maxArguments",
  "required": ["input_data"],
  "properties": {
    "input_data": {
      "type": "array",
      "title": "Input Data",
      "description": "Record groups to operate on: …",
      "items": {"type": "array", "items": {"type": "object", "additionalProperties": true}}
    },
    "attributes": {
      "type": "object",
      "title": "Attributes",
      "description": "Operator arguments for this tool. …",
      "additionalProperties": true,
      "default": {},
      "required": ["max_key"],
      "properties": {
        "max_key": {"type": "string", "description": "The key to find the maximum value for"},
        "output_key": {"type": "string", "default": "max", "description": "The key name for the result max value"}
      }
    },
    "properties": {
      "title": "Properties",
      "description": "Execution and backend settings for this call, or null. …",
      "anyOf": [{"type": "object", "additionalProperties": true}, {"type": "null"}],
      "default": null
    }
  }
}
```

### 2.4 Structured results

Every tool publishes structured output: the `run()` triple, projected once.

```json
{
  "output_data": [[{"name": "b", "score": 9}]],
  "output_attributes": {},
  "exec_meta": {"is_empty": false, "errors": [], "logs": [], "traces": {}}
}
```

The output schema forbids additional properties at every level and declares the three error enums by name, so a client sees `ErrorCategory`, `ErrorCode`, and `ErrorStage` as closed string enums rather than free text.
An error entry carries `category`, `code`, `operator_id`, `stage`, `message`, `retryable`, and `suggestion`, all required.

The projection applies one JSON conversion: `default=str` for a leaf that is not JSON-native, and `allow_nan=False`, so `NaN` and `Infinity` are rejected.
Read `structuredContent` as authoritative; `json.loads(result.content[0].text)` is the same object.

Each call runs the operator in a worker thread, so a synchronous transform does not block the event loop.

### 2.5 Error surfacing

| Situation | `isError` | Where the detail is |
|---|---|---|
| a recoverable, failed, timed-out, or successful-empty operator outcome | false | `exec_meta` |
| an unknown tool, malformed top-level arguments, or a projection or encoding failure | true | the tool error; no operator record is invented |
| malformed JSON-RPC or a transport failure | — | the SDK's behavior |

A call that passes the container schema and fails operator validation is a successful MCP result.
Calling `ops_select` without its required attributes returns an `INVALID_INPUT` record at the `VALIDATE` stage with `isError` false.
A conversion failure the adapter causes stays an adapter error and never becomes a synthetic operator record.

### 2.6 Selections other than the default

`operator_ids` replaces the default selection with an exact pinned subset; an empty tuple serves no tools.
`registry` supplies the backing registry, which may be a superset of the selection.
The selection is validated before a single tool is registered, and each of these raises rather than degrading:

- a repeated ID in the selection, or two versions of one logical name;
- a card the registry does not hold, or one whose identity disagrees with the ID requested;
- a version other than `2.0.0` or `3.0.0`, except the exact built-in `nl2sql@4.0.0` card;
- a package-owned ID whose provenance or resolved implementation class does not match a reference build;
- a caller-created card that shadows a supported built-in logical name, or a caller-created card at any version other than `2.0.0`.

A caller-created `@2.0.0` card may reuse a removed logical name such as `multipart_query`; that runs the caller's implementation and restores nothing.
Custom `@1.0.0` and `@3.0.0` cards are outside the contract.
Acceptance for execution grants no planning authority and authorizes no write; the caller and the deployment host remain responsible for that.

### 2.7 Version pairing

The adapter pins the core exactly, `blue-data-ops==1.0.0`, alongside `blue-data[server]>=1.0.0,<2`, `mcp>=1.28.1,<2` and `pydantic>=2.11,<3`.
One environment therefore holds one verified pair, and the core and the adapter are updated together.
The MCP initialization response's `serverInfo.version` is this package's own version, `1.0.0`, set on the server after `FastMCP` builds it because `FastMCP` takes no version argument and otherwise reports the SDK's.
The same string is `blue_data_ops_mcp.__version__` and what package metadata returns, and each tool's operator version is in its `_meta`, moving independently of it.

---

## 3. REST API — not built

There is no HTTP API in this repository.
`platform/` holds `ops-cli` and `ops-mcp`, and there is no `platform/api/`, no ASGI or WSGI application, and no web framework in any distribution's dependencies or extras.

MCP provides the current network interface for model clients, and no REST adapter is planned.
If a REST adapter is added, it would be a fourth distribution under `platform/`, with its own version and exact core pin, following the shape in section 2.7.
Like the MCP adapter, it would keep operator logic in the core.


---

## 4. CLI

`blue-data-ops-cli` installs one console command, `blue-ops`, declared as `blue_data_ops_cli.commands:cli`.
The core distribution declares no console script, so a process that installs only the library still adds nothing to `PATH`.
No package in this repository is runnable as `python -m`.
[`../platform/ops-cli/README.md`](../platform/ops-cli/README.md) is the source of truth for the command's behavior; this section states the contract.

The objection the earlier interface answered still stands — an operator call's input is a nested structure and its output is a three-element result, and neither survives argv and stdout with its shape intact.
The command answers it rather than avoiding it: a record bundle arrives as a file or on standard input, never as an argument, and a result is rendered rather than reformatted, with `--format json` emitting the structure unchanged.

### 4.1 The command tree

Commands are `blue-ops <component> <action> <parameters>`, which is the family's shape.
Twenty-four commands over five components and one subcomponent.

| Component | Actions |
|---|---|
| `profile` | `add`, `remove`, `list`, `config`, `inspect`, `select` |
| `catalog` | `list`, `inspect`, `select` |
| `operator` | `list`, `search`, `inspect`, `run` |
| `operator resource` | `list`, `inspect`, `export` |
| `pipeline` | `add`, `import`, `export`, `list`, `inspect`, `remove`, `run` |
| `metadata` | `inspect` |

The root group carries `--version`, `-h`/`--help`, and `--profile NAME`.
`--format table|json|nl` is on every command that returns a result; `--catalog active|history` is on every command that reads the registry; `--confirm` is on every command that destroys or overwrites something.

There is no `database`, `data`, or `schema` component.
This repository has no store of its own, an operator's attribute schema is part of that operator's description rather than a component, and the data registry those words would name belongs to `blue-data`, whose own CLI manages it.

### 4.2 Configuration

Four tiers, in one order everywhere: **command option > environment variable > profile > built-in default**.

A parameter name is also its environment variable name.
A variable exported empty is refused rather than read as unset, because an empty tier that is silently skipped hands the setting down without saying so.
`BLUE_DATA_OPS_HOME` and `BLUE_DATA_PROFILE` come from the environment only, since one of them is the directory the profiles are read from and the other picks which profile that is.
The parameter list, with casts and defaults, is `profile_spec.json` and is published in the package README.

### 4.3 Output

`table`, `json`, and `nl`, and there is no `csv`: a record bundle is `list[list[dict]]` and CSV has no representation for the group boundary.
Every JSON result is one object with a payload key named for the resource, beside its metadata keys; a key that is a list or a count is present even when empty.
The result goes to standard output and everything else — progress, logs, warnings, errors — to standard error.
Every format strips terminal control characters from every cell, because operator output is whatever a model wrote or a data source held.

### 4.4 Exit codes

Ten codes, one per failure family, each carrying the library's own code in the description and in the JSON error's `detail`.

| Code | Exit | Cause |
|---|---|---|
| — | 0 | success, including an empty result and a declined confirmation |
| `INTERNAL` | 1 | an exception outside the classified families |
| `USAGE` | 2 | usage error, refused by the parser before any command body runs |
| `REQUEST` | 3 | `ResolveError`, `DiscoveryError`, or `PipelineError` |
| `CONFIG` | 4 | a resolved configuration value the library refused |
| `PROFILE` | 4 | a profile operation this CLI rejected |
| `TRANSPORT` | 5 | the provider timed out, rate-limited, or was unavailable |
| `RESOURCE` | 6 | `OperatorSkillLoadError` |
| `PLANNING` | 7 | any other planning failure |
| `EXECUTION` | 8 | an operator run returned a failed `ErrorRecord` |
| `TIMEOUT` | 9 | an operator run exceeded its allowance |

Exits 0 through 5 carry the meanings the family's other guide-compliant CLI gave them; 6 through 9 are this library's own failure families.

### 4.5 Secrets

A secret is never accepted as a value on the command line, where it would reach shell history: `--property openai.api_key=…` is refused and the refusal names `blue-ops profile config OPENAI_API_KEY`, which prompts with the input hidden.
A stored secret is base64-encoded behind an `enc:` prefix, which is obfuscation rather than encryption; the 0600 file mode is the real protection and the README says so.
Every error line, every log line, and the settings footer go through the package's masking, because they carry text the CLI did not write — a library message quoting an argument, or a provider SDK exception free to include a header.
Records do not: they are the output an operator was asked to compute.

### 4.6 Maintenance scripts are not this interface

`lib/scripts/` holds three Python tools run from a checkout with `python`, one of which parses arguments, and three shell scripts that wrap `build`, `install`, and `publish`.
They are repository maintenance, not a product interface, and they install no entry point.

---

## 5. What Is Stable

| Surface | Stability |
|---|---|
| `blue_data_ops` and its subpackage exports | public. A removal is a major version. |
| a pinned operator ID, once registered | immutable. A registry never overwrites or deregisters one, and removing an ID from the package catalog is a major version. |
| the `run()` triple, `ExecMeta`, and `ErrorRecord` fields | public. The MCP adapter projects the three error enums onto the wire as closed string enums, so adding a value is a protocol change rather than an internal one. |
| the `DataPipeline` record as `to_dict()` emits it | public; it is the portable serialization boundary |
| the operator resource index and manifest formats | versioned by their `format` strings, `blue-data-ops/operator-skill-index@1` and `blue-data-ops/operator-skill@1` |
| the data-context document | versioned by `blue-data-ops/data-context@1` |
| MCP tool names, arguments, and the result envelope | public. The operator version behind a tool may move without the tool changing, and adapter `1.0.0` renamed every tool once, to the `ops_` prefix. |
| a module or name with a leading underscore | private, including the modules holding the `@3.0.0` outcome implementations. Reach those through the registry. |
| `properties` keys | the cross-cutting dotted keys are public; operator-specific keys are documented per operator in [`../lib/OPERATORS.md`](../lib/OPERATORS.md) |
| CLI command and option names, the JSON payload keys, and the exit codes | public. A renamed command, a removed option, a renamed payload key, or a moved exit code is a major version of `blue-data-ops-cli`. |

Migration boundaries between release lines are in [`../lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md), for the adapter in [`../platform/ops-mcp/README.md`](../platform/ops-mcp/README.md), and for released versions of all three distributions in [`../CHANGELOG.md`](../CHANGELOG.md).

HTTP requires the shared API key by default on both streamable HTTP and SSE.
See the [HTTP bind, authentication and mounted lifespan contract](../docs/mcp.md#http-authentication-and-bind-settings)
for environment overrides, the explicit no-key opt-out and the SDK Host/Origin limits.

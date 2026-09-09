# blue-data-ops

`blue-data-ops 2.8.0` is the standalone Python package for Blue data operators. It includes record-oriented transforms, registry-backed database operations, pinned operator discovery, structured execution results, and a local pipeline planner. Operator input and output use `list[list[dict]]`: a list of record groups.

## Requirements

- Python 3.11+
- `blue-data` 0.1.0 or later. It is an eager import-time dependency and must be importable whenever `blue_data_ops` is imported. Registry-backed operators access it through the data seam.

## Installation

For a source checkout, place `blue-data` and `blue-data-ops` under the same parent directory. Then run:

```bash
python3 -m venv blue-data-ops/lib/.venv
source blue-data-ops/lib/.venv/bin/activate
python -m pip install -e ./blue-data/lib
python -m pip install -e "./blue-data-ops/lib[ml,vector,llm]"
```

Install the `dev` extra when working on this package:

```bash
python -m pip install -e "./blue-data-ops/lib[dev]"
```

If your artifact index is configured separately, install the released artifact instead:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==2.8.0"
```

The artifact-index command works only when that index also provides `blue-data>=0.1.0`. The sibling-checkout commands above are the direct path for a new contributor.

The optional extras are `ml` for `classify` and `cluster`, `vector` for the three vector operators, `llm` for `nl2llm`, `nl2sql`, `nl2bn`, the `semantic_*` operators, and `query_breakdown`, and `openai` for `OpenAIPlanGenerator`. `nl2query_router` does not need the `llm` extra. The `openai` extra is the only one the planner needs, and only for that one generator:

```bash
python -m pip install -e "./blue-data-ops/lib[openai]"
```

The `openai` extra pins `openai>=2.54,<3`. Nothing in the package imports that SDK until an `OpenAIPlanGenerator` has to build its own client, so every other path installs and runs without it.

If an LLM-backed `run()` call cannot import a member of the `llm` extra, its `ExecMeta` contains an `EXECUTION_FAILED` error with an instruction to install `blue-data-ops[llm]`. Other execution failures keep the generic contained error.

After installation, read the distribution version separately from the `@2.0.0` operator-card version:

```python
from importlib.metadata import version

assert version("blue-data-ops") == "2.8.0"
```

## Usage

Start with the credential-free examples:

```bash
cd blue-data-ops/lib
python examples/core_quickstart.py
python examples/sqlite_quickstart.py
python examples/refinement.py
```

`sqlite_quickstart.py` creates a temporary SQLite database with ten rows, registers it, performs a real insert, and removes the database when it exits. `refinement.py` calls the seam deprecated in 2.8.0 and stays runnable as compatibility evidence; start from the other two. See [examples/README.md](examples/README.md) for the ML, vector, and live-provider examples. See [OPERATORS.md](OPERATORS.md) for the generated attribute and outcome reference for all 36 operators. These reference and example files ship in the source distribution; they are not installed as files beside the Python package in the wheel.

```python
from blue_data_ops import SelectOperator

op = SelectOperator()
data = [[
    {"name": "a", "score": 3},
    {"name": "b", "score": 9},
]]

# Raw v1-compatible call: validate, then apply.
out = op.invoke(data, {"operand_key": "score", "operand": ">", "operand_val": 5})
# [[{"name": "b", "score": 9}]]

op.attributes            # declared attribute schema (name -> AttributeSpec)
op.validate(data, {})    # False: operand_key/operand/operand_val are required
```

### Registry-backed data operations

`create_database`, `create_table`, `insert_table`, and `data_discover` need a `blue-data` registry. The complete runnable setup is [examples/sqlite_quickstart.py](examples/sqlite_quickstart.py). Its core steps are:

```python
from tempfile import TemporaryDirectory

from blue_data.registry.data_registry import DataRegistry
from blue_data.source.json.memory_json_source import MemoryJSONSource
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource
from blue_data_ops import CreateDatabaseOperator, RegistrySeam

with TemporaryDirectory() as directory:
    source = SQLiteDBSource(
        "demo_sqlite",
        properties={"connection": {"database_directory": directory}},
    )
    registry = DataRegistry(store=MemoryJSONSource(), rebuild=False)
    registry.register_source(source)
    registry.sync_source(source.name, recursive=True)
    seam = RegistrySeam(registry)

    output, _, meta = CreateDatabaseOperator().run(
        [[]],
        {"source": source.name, "database": "main"},
        {"data_registry": seam},
    )
    assert meta.errors == []
```

You may inject a raw `DataRegistry` instead; `resolve_registry()` wraps it. Without an injection, pass both `platform.name` and `data_registry.name`. The default provider then creates and caches an in-memory `DataRegistry` for that pair. A missing injection or naming pair leaves the registry unresolved.

## Operators

| Category | Operators |
|---|---|
| Filter / shape | `select`, `project`, `delete`, `insert` |
| Join / set | `join`, `union`, `intersect` |
| Aggregate | `argmax`, `argmin`, `max`, `min`, `avg`, `sum` |
| Text | `normalize_text`, `segment_text` |
| ML (extra: `ml`) | `classify`, `cluster` |
| Vector (extra: `vector`) | `vector_embed`, `vector_search`, `vector_similarity` |
| LLM (extra: `llm`) | `nl2llm`, `nl2sql`, `nl2bn`, `semantic_extract`, `semantic_filter`, `semantic_join`, `semantic_project`, `semantic_transform` |
| Registry-backed | `create_database`, `create_table`, `insert_table`, `data_discover` |
| Plan-producing (deprecated) | `multipart_query`, `nl2query_router`, `plan_discover`, `query_breakdown` |

`nl2llm`, `nl2sql`, `nl2bn`, the `semantic_*` operators, and `query_breakdown` send requests through [LiteLLM](https://github.com/BerriAI/litellm); configure the model per call via properties (default `openai.model: gpt-4o`). `classify` uses NumPy and scikit-learn from the `ml` extra. Registry-backed operators talk to `blue-data` through the data seam.

The four plan-producing operators are deprecated in 2.8.0 and removed in 3.0.0. They still resolve and run for the rest of 2.x; see [Deprecations in 2.8.0](#deprecations-in-280).

This short `nl2llm` call uses a live provider:

```python
from blue_data_ops import NL2LLMOperator

output, _, meta = NL2LLMOperator().run(
    [[]],
    {
        "query": "Return two example products",
        "attrs": [{"name": "name", "type": "string"}],
    },
    {"openai.model": "gpt-4o-mini"},
)
assert meta.errors == []
```

Install `[llm]` and configure the provider credential before running it. The complete `nl2sql` example in [examples/nl2sql_sqlite.py](examples/nl2sql_sqlite.py) builds a real SQLite schema and defaults to `execute_query=False`. Add `--execute` to run the generated SQL. The prefix check is a case-insensitive `startswith` guard, not a SQL parser or sandbox; callers remain responsible for database permissions and query safety.

### Versioned registries

`OperatorRegistry` (in `blue_data_ops.operators`) registers operators under an immutable `name@<MAJOR.MINOR.PATCH>` id. `resolve()` accepts only an exact pinned id and raises `ResolveError` when it cannot resolve one.

`default_registry()` is the frozen v1 view: 36 raw cards at `1.0.0`. `versioned_registry()` is the v2 discovery view: 72 cards, with `1.0.0` and `2.0.0` for each operator. Its cards add ordered tags and `when_to_invoke` guidance. Constructing either catalog does not query a data registry.

```python
from blue_data_ops.operators import default_registry, versioned_registry

v1 = default_registry()
v1_select = v1.resolve("select@1.0.0")

catalog = versioned_registry()
v2_cards = [card for card in catalog.list_cards() if card.version == "2.0.0"]
select_card = next(card for card in v2_cards if card.name == "select")
v2_select = catalog.resolve(select_card.operator_id)
```

`find(query, tags=...)` performs deterministic text discovery with an optional exact AND tag filter. It returns cards, not operator instances. `find_latest(name)` returns the highest-version card for an exact name:

```python
cards = catalog.find("filter", tags=["domain-relational"])
latest = catalog.find_latest("nl2sql")
op = catalog.resolve(latest.operator_id) if latest is not None else None
```

Tags have six axes: `capability-*` describes the operation, `domain-*` the data family, `flow-*` the pipeline position, `accepts-*` the input shape, `produces-*` the result or side effect, and `requires-*` the runtime dependency or integration. A card may carry several values on an axis. Tag strings are exact; with multiple tags, every tag must be present. Free-text scoring ranks only the cards that pass that filter. The generated [operator reference](OPERATORS.md#tag-taxonomy) lists the current values and every card assignment.

`OperatorEmbeddingIndex` adds embedding search for direct Python callers. The caller supplies the embedder and its `space_id`; the package does not select or install an embedding model.

```python
from blue_data_ops.operators import OperatorEmbeddingIndex, versioned_registry


class KeywordEmbedder:
    @property
    def space_id(self) -> str:
        return "readme-keywords-v1"

    def __call__(self, texts: tuple[str, ...]) -> list[list[float]]:
        terms = ("filter", "join", "query")
        return [
            [1.0, *(float(term in text.casefold()) for term in terms)]
            for text in texts
        ]


catalog = versioned_registry()
embedding_index = OperatorEmbeddingIndex.build(catalog, KeywordEmbedder())
cards = embedding_index.find("filter rows", tags=["produces-data"])
op = catalog.resolve(cards[0].operator_id) if cards else None
```

`build()` passes every card's name, `when_to_invoke`, description, and ordered tags to the embedder in one batch. A nonblank search passes the query unchanged in a separate call; a whitespace-only query is blank. With a nonblank query, `find()` returns every tag-matching card in cosine order. It applies no threshold or limit; callers limit the returned list. Rebuild the index after registering another card or changing the embedding model or preprocessing, and give each embedding space a distinct `space_id`. Callback failures, invalid vectors, and stale snapshots raise `EmbeddingDiscoveryError` with a stable `reason`.

### Operator skill resources

`blue_data_ops.operator_skills` loads versioned guidance for exact package-owned operators. Version 2.8.0 includes `@2.0.0` packages for all 32 active execution operators and retains the `multipart_query@2.0.0` package. It also lets callers inspect package availability and resource metadata before loading text. A level-2 view combines the current card and live attribute schema with `Operator.md`; level 3 also loads `examples.md`. Loading a view does not invoke the operator or add the text to planner or provider input.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
loader = OperatorSkillLoader(registry)
skill = loader.load("nl2sql@2.0.0", level=3)

assert skill.card is registry.get_card("nl2sql@2.0.0")
assert skill.io.attributes["question"].required
```

To expand a discovered card, first intersect the discovery result with the packages available to this loader:

```python
eligible_ids = set(loader.available_operator_ids())

matches = registry.find("average", tags=["domain-arithmetic"])
selected = next(card for card in matches if card.operator_id in eligible_ids)
descriptor = loader.describe(selected.operator_id)
skill = loader.load(selected.operator_id, level=max(descriptor.declared_levels))

assert selected.operator_id == "avg@2.0.0"
assert descriptor.declared_kinds == ("guide", "examples")
assert descriptor.declared_levels == (2, 3)
assert skill.card is selected
```

`available_operator_ids()` validates the package index and intersects it with package-built cards in the loader's registry. `describe()` validates the selected card, the full index, and its manifest, then reports the resource kinds and complete levels declared there. Neither method opens Markdown or validates the live attribute schema. Calling them in sequence reads the index twice and the selected manifest once because the loader keeps no cache or snapshot.

A discovered card may have no skill package. Eligibility is separate from both visibility and lifecycle: `avg@1.0.0` is current and searchable and still ships no package, while `avg@2.0.0` is the eligible one. Check eligibility before expansion instead of treating the miss as a failed discovery:

```python
skipped = next(card for card in matches if card.operator_id not in eligible_ids)

assert skipped.operator_id == "avg@1.0.0"
assert registry.get_card(skipped.operator_id) is not None
```

Metadata calls do not guarantee that a later resource read will succeed. A package can change between calls, and `load()` or `read()` may still raise `OperatorSkillLoadError`. Handle `OperatorSkillErrorCode.NOT_AVAILABLE` when an optional level or resource is absent. The loader has no latest-version fallback and does not accept custom registrations.

The runnable [`operator_skill_discovery.py`](examples/operator_skill_discovery.py) and [`operator_skill_integrations.py`](examples/operator_skill_integrations.py) examples show lexical, embedding-first, and planner-adjacent caller flows. The planner itself never loads skill metadata or text.

### Structured execution

`run()` is the canonical v2 call. It applies canonical defaults, validates, executes once, and returns `(output_data, output_attributes, exec_meta)`. The internal `_execute()` hook returns `FunctionResult(output_data, output_attributes)`; `run()` normalizes that result and adds `ExecMeta`. Result-produced `output_attributes` is a fresh mapping for each call.

```python
from blue_data_ops.operators import versioned_registry

op = versioned_registry().resolve("select@2.0.0")
data = [[{"name": "a", "score": 3}, {"name": "b", "score": 9}]]
attributes = {"operand_key": "score", "operand": ">", "operand_val": 5}

output_data, output_attributes, meta = op.run(data, attributes)
assert output_data == [[{"name": "b", "score": 9}]]
assert output_attributes == {}
assert meta.is_empty is False
assert meta.errors == []
```

`ExecMeta` has four fields: `is_empty`, `errors`, `logs`, and `traces`. Each `ErrorRecord` has `category`, `code`, `operator_id`, `stage`, `message`, `retryable`, and `suggestion`. Categories are `RECOVERABLE`, `FAILED`, or `TIMEOUT`; stages are `DEFAULTS`, `VALIDATE`, `EXECUTE`, `NORMALIZE`, or `REFINE`.

Continuing the structured-execution example, an empty result is still successful. `run()` normalizes any empty group shape to `[[]]`, sets `is_empty=True`, and leaves `errors` empty:

```python
empty_data, _, empty_meta = op.run(
    [[{"score": 3}]],
    {"operand_key": "score", "operand": ">", "operand_val": 99},
)
assert empty_data == [[]]
assert empty_meta.is_empty is True
assert empty_meta.errors == []
```

In the same example, invalid input and execution failures are data, not raised operator exceptions. The failure output is `[[]]`, and the error record identifies the boundary:

```python
failed_data, failed_attributes, failed_meta = op.run([[{"score": 3}]], {})
error = failed_meta.errors[0]
assert failed_data == [[]]
assert failed_attributes == {}
assert (error.category.value, error.code.value, error.stage.value) == (
    "RECOVERABLE",
    "INVALID_INPUT",
    "VALIDATE",
)
assert error.operator_id == "select@2.0.0"
```

Set a canonical wrapper deadline with `properties={"execution.timeout_seconds": <finite-positive-number>}`. The wrapper never retries. The legacy `properties["timeout"]` field remains observable but does not set this deadline.

`apply()` and `invoke()` remain the raw v1-compatible paths through v2.x. For ordinary data operators, `apply()` calls the transform directly and `invoke()` runs boolean `validate()` before `apply()`, returning `None` when validation is false. `multipart_query` and `nl2query_router` preserve Blue's two-argument `validate(attributes, properties)` call shape; their inherited three-argument `invoke()` is not a supported path. Use `refine()` for those plan-producing operators. Raw calls do not provide canonical default materialization or contained `ExecMeta`; use `run()` when the caller needs those semantics. Those four operators and every `refiner()` and `refine()` call are deprecated in 2.8.0. See [COMPATIBILITY.md](COMPATIBILITY.md) for the migration boundary.

The rest of the compatibility surface remains public. The ordinary three-argument `validate(input_data, attributes, properties)` path checks the live attribute schema and returns `False` for invalid attribute values. The two plan-producing exceptions above use their Blue call shape. `explain()` describes a completed transform, and `attributes`, `is_required(name)`, and `default_of(name)` expose the declared attributes.

### Refinement and plan representation

The whole refinement seam is deprecated in 2.8.0 and removed in 3.0.0, including the calls below and `RefinableOperator` itself. It stays callable for the rest of 2.x, and each call warns. Treat this section and [`examples/refinement.py`](examples/refinement.py) as evidence that existing integrations keep working, not as the shape for a new one.

The four plan-producing operators expose raw `refiner()` and normalized `refine()` calls. `refiner()` keeps the v1 serialized-record shape. `refine()` returns `(list[DataPipeline], ExecMeta)` and reports empty or failed refinement through the same metadata model as `run()`.

```python
from copy import deepcopy

from blue_data_ops.operators import versioned_registry
from blue_data_ops.plan import DataPipeline, RefinableOperator

refinable = versioned_registry().resolve("multipart_query@2.0.0")
assert isinstance(refinable, RefinableOperator)
input_data = [[]]
attributes = {}
plans, refine_meta = refinable.refine(input_data, attributes)
assert len(plans) == 1
assert refine_meta.errors == []
records = [plan.to_dict() for plan in plans]
restored = [DataPipeline.from_dict(record) for record in records]
detached = [DataPipeline.from_dict(deepcopy(record)) for record in records]
```

`DataPipeline.to_dict()` and `DataPipeline.from_dict()` are the portable representation boundary. `to_dict()` exposes the pipeline's live mapping, and `from_dict(record)` adopts `record` as its live mapping rather than copying it. Use `deepcopy(record)` as shown above when the restored pipeline must not update the reusable serialized record.

A pipeline records pinned operator IDs, nodes, and edges. `PipelineExecutor` runs a materialized pipeline locally:

```python
from blue_data_ops.operators import versioned_registry
from blue_data_ops.plan import DataPipeline, PipelineExecutor

plan = DataPipeline(label="high-scores")
source = plan.define_input("records")
selected = plan.define_operator(
    "select@2.0.0",
    attributes={"operand_key": "score", "operand": ">", "operand_val": 5},
)
result = plan.define_output("result")
plan.set_plan_input(source)
plan.set_plan_output(result)
plan.connect_nodes(source, selected)
plan.connect_nodes(selected, result)

run = PipelineExecutor(versioned_registry()).execute(
    plan,
    [[{"name": "a", "score": 3}, {"name": "b", "score": 9}]],
)
assert run.succeeded
assert run.output_data == [[{"name": "b", "score": 9}]]
```

`PipelineExecutor.preflight()` and `execute()` raise `blue_data_ops.plan.PipelineError` when the materialized graph or execution input cannot be used safely. Operator failures after preflight remain contained in the returned `PipelineRun`: `succeeded` is false, `failed_node_id` names the stopped node, and its `NodeRun.exec_meta` carries the operator error records.

The executor resolves every pinned ID before it calls an operator, traverses the graph in stable topological order, forwards predecessor groups, and records each completed operator in `run.node_runs`. A successful empty result continues through the graph. The first structured node error stops the run and sets `failed_node_id`.

Only materialized plans are executable. Call `refine()` first, choose one returned plan, and pass that plan to the executor. An execution node that still resolves to a `RefinableOperator` is rejected during preflight. The executor does not retry, replan, select alternatives, dispatch remotely, or provide Redis/pubsub synchronization. Execution updates node values and statuses on the supplied plan; round-trip a copy first if the original record must remain unchanged.

## Planning

`PipelinePlanner` turns a goal and a set of discovery queries into a compiled `DataPipeline`, and optionally executes it. It runs discovery, data-context collection, generation, selection, and compilation, then hands the compiled plan to executor preflight. A plan generator supplies candidates; the planner owns every other stage.

```python
from blue_data_ops.operators import versioned_registry
from blue_data_ops.plan import (
    SELECT_THEN_AVERAGE_TEMPLATE,
    DiscoveryQuery,
    PipelinePlanner,
    PlanningRequest,
    RulePlanGenerator,
)

planner = PipelinePlanner(
    versioned_registry(),
    RulePlanGenerator([SELECT_THEN_AVERAGE_TEMPLATE]),
)
request = PlanningRequest(
    goal="average total of orders above 100",
    discovery_queries=(
        DiscoveryQuery("filter", tags=("capability-filter",)),
        DiscoveryQuery("average", tags=("capability-average",)),
    ),
    operator_attributes={
        "select": {"operand_key": "total", "operand": ">", "operand_val": 100},
        "avg": {"avg_key": "total", "output_key": "average_total"},
    },
)

run = planner.run(request, [[{"total": 120.0}, {"total": 215.0}, {"total": 50.0}]])
assert run.execution.output_data == [[{"average_total": 167.5}]]
assert [step.operator_id for step in run.planning.selected.steps] == [
    "select@2.0.0",
    "avg@2.0.0",
]
```

`plan(request)` returns a `PlanningResult` without executing anything: a copy of the `request`, the `discovery` snapshot, the generated `candidates`, the `selected` draft, the compiled `pipeline`, its `preflight`, and the `data_context` retained for the run. `run(request, input_data)` returns a `PlannerRun` holding that `PlanningResult` and the `PipelineRun` from executing it. `execute(planning, input_data)` executes a `PlanningResult` produced earlier; it runs a copy, so the result's own pipeline record stays unchanged.

The planner compiles only `@2.0.0` operator ids, and only ones its own discovery returned. `RequireSinglePlan` is the shipped selector and accepts exactly one candidate; pass a `selector` of your own to choose among several. `PlanningRequest` carries the bounds: `max_discovery_cards`, `max_candidates`, `max_steps`, `max_nodes`, and `max_edges`.

`plan()` admits active cards only. `discover()` is unchanged and still returns deprecated cards, so the two can disagree; see [Deprecations in 2.8.0](#deprecations-in-280).

### Rule templates

A `RulePlanTemplate` builds one linear candidate from exact discovered operators and caller-supplied attributes. Each `RuleTemplateStep` names the operator, the attributes the caller has to supply, and the exact tag tuple the discovered card must carry, so a template fails rather than planning against an operator whose metadata moved.

`SELECT_THEN_AVERAGE_TEMPLATE` is the shipped filter-then-average template. `project_then_aggregate_template(name)` returns the project-to-aggregate template for `"avg"`, `"sum"`, `"min"`, or `"max"`:

```python
from blue_data_ops.plan import project_then_aggregate_template

template = project_then_aggregate_template("sum")
assert template.label == "project-then-sum"
```

`RulePlanGenerator(rules)` runs each rule in order and keeps the drafts that are not `None`. A rule is any callable taking `(request, discovery, data_context)` and returning `PlanDraft | None`, and a `RulePlanTemplate` is itself such a callable. Constructed with no argument, `RulePlanGenerator()` uses the built-in select-then-average rule, which recognizes its own goal wording and returns `None` for anything else.

### Planning errors

Planning raises `PlanningError` instead of reporting through `ExecMeta`. It is a `ValueError` subclass carrying a structured `record`:

```python
from blue_data_ops.operators import versioned_registry
from blue_data_ops.plan import DiscoveryQuery, PipelinePlanner, PlanningError, PlanningRequest, RulePlanGenerator

planner = PipelinePlanner(versioned_registry(), RulePlanGenerator())
request = PlanningRequest(
    goal="average total of orders above 100",
    discovery_queries=(DiscoveryQuery("filter", tags=("capability-filter",)),),
)

try:
    planner.plan(request)
except PlanningError as error:
    record = error.record
    print(record.category, record.code, record.stage, record.retryable, record.suggestion)
```

`PlanningErrorRecord` has `category`, `code`, `stage`, `message`, `retryable`, and `suggestion`. `category` reuses the operator `ErrorCategory` (`RECOVERABLE`, `FAILED`, `TIMEOUT`). `PlanningStage` is `VALIDATION`, `DISCOVERY`, `DATA_CONTEXT`, `GENERATION`, `SELECTION`, `COMPILATION`, or `PREFLIGHT`. Each `PlanningErrorCode` names what happened to planning rather than which dependency caused it, so a code stays stable across generators and providers.

Planning raises where execution returns metadata because there is no partial result to attach a record to: either a pipeline compiled or it did not.

### Bounded data context

A generator that needs to know the schema receives a `DataContextSnapshot`, never rows. `DataScope` names the exact registry address to plan against, with an optional entity projection. The following constructor excerpt assumes the application has already created `registry`, `generator`, and `seam`; [examples/sqlite_quickstart.py](examples/sqlite_quickstart.py) shows the complete registry setup.

```python
from blue_data_ops.plan import DataScope, PipelinePlanner, RegistryDataContextProvider

scope = DataScope("demo_sqlite", "shop", "public", entities=("orders",))
planner = PipelinePlanner(
    registry,
    generator,
    data_context_provider=RegistryDataContextProvider(seam),  # seam is a RegistrySeam
)
```

`RegistryDataContextProvider` uses three read-only registry operations: source properties, the collection's entity list, and each entity's attributes. It returns entity names, optional descriptions, and attribute names with declared types, where an unknown type is `null`. It reads no relations and no rows, and the snapshot's provenance records `raw_rows: 0`. Its limits are `max_entities` (32), `max_attributes_per_entity` (64), `max_total_attributes` (512), `max_description_chars` (512), and `max_serialized_bytes` (131072). A snapshot that exists already satisfies every limit it reports.

A request carrying a `data_scope` needs a provider; without one the planner raises `DATA_CONTEXT_REQUIRED` rather than planning blind. A request without a scope never reaches the registry at all, configured provider or not.

The planner hands the generator one snapshot and keeps a second, equal one on the `PlanningResult`. The two are distinct objects that serialize identically, both rebuilt from the provider's document into package-owned instances, so whatever a generator does to its copy cannot reach the recorded result.

### The OpenAI plan generator

`OpenAIPlanGenerator` is a `PlanGenerator` backed by one non-streaming Responses call per `generate()`. It needs the `openai` extra.

```python
from blue_data_ops.operators import versioned_registry
from blue_data_ops.plan import OpenAIPlanGenerator, PipelinePlanner

registry = versioned_registry()
generator = OpenAIPlanGenerator(
    "gpt-4o",
    registry=registry,
    allowed_operator_ids=["select@2.0.0", "avg@2.0.0"],
)
planner = PipelinePlanner(registry, generator)
```

`allowed_operator_ids` is an authorization boundary rather than a ranking hint. A card is offered to the model only when the caller allowlisted it, discovery returned it, this same registry built it, it pins `@2.0.0`, and it carries no `produces-side-effect` tag. The decoder re-checks that same set, so a model naming anything else fails before a `PlanDraft` exists. Caller-supplied `operator_attributes` are constraints: the model may add declared attributes, but it cannot overwrite or drop one the caller set. A conflicting value raises `GENERATION_RESULT_INVALID` and fails the whole generator or planner call before any drafts are returned.

To extend the preceding generator with data-context disclosure, set a second, explicit opt-in:

```python
generator = OpenAIPlanGenerator(
    "gpt-4o",
    registry=registry,
    allowed_operator_ids=["nl2sql@2.0.0", "select@2.0.0", "avg@2.0.0"],
    send_data_context=True,
)
```

Without `send_data_context=True`, a snapshot reaching `generate()` raises `DATA_CONTEXT_DISCLOSURE_REQUIRED` before the SDK import, the client, and any provider traffic; the snapshot is never quietly dropped. An `nl2sql` step is refused unless a snapshot was both supplied and disclosed.

Pass `client=` to inject a configured `OpenAI` instance, whether for a different base URL or for a test double. Left as `None`, the generator constructs `openai.OpenAI()` at first use, and the SDK reads the credential from the environment in its usual way; the generator neither reads nor records that value. Each call sets `store=False`, disables the SDK's retries, and makes none of its own. `timeout_seconds` (60.0) and `max_output_tokens` (4096) bound it, and `max_candidates` is 1 because the shipped selector accepts exactly one plan.

Provider failures map to provider-independent codes chosen by exception class and HTTP status: `GENERATOR_DEPENDENCY_MISSING`, `GENERATOR_REQUEST_REJECTED`, `GENERATOR_TIMEOUT`, `GENERATOR_RATE_LIMITED`, `GENERATOR_UNAVAILABLE`, `GENERATOR_REFUSED`, and `GENERATOR_RESPONSE_INVALID`. No response body, request payload, credential, or provider identifier reaches a planning record.

### Planning from refinement candidates

`plan_refinement()` is deprecated in 2.8.0 and removed in 3.0.0, along with the refinement sources it accepts. Its behavior is unchanged for the rest of 2.x.

`plan_refinement()` accepts one explicit package-built `@2.0.0` refinement source and its call input. The request must have a nonempty exact-ID allowlist that admits the source and every child. The planner calls normalized `refine()` once, rejects an error-bearing, over-limit, or invalid batch as a whole, projects each complete portable graph into a draft, and then uses the configured selector before fresh compilation and preflight.

The eligible sources are `multipart_query@2.0.0`, `nl2query_router@2.0.0`, `plan_discover@2.0.0`, and `query_breakdown@2.0.0`. The default `RequireSinglePlan` selector still rejects a batch with more than one candidate. A scoped request remains anchored throughout projection and compilation, including a matching `nl2query_router` to `nl2sql` path.

Planning remains one pass. There is no refinement loop, retry, or replanning after execution. This path does not load operator skill resources, collect a data-context snapshot, or send skill text to a planner, provider, or MCP response.

## Deprecations in 2.8.0

Two groups of surfaces are deprecated in this release and removed in 3.0.0. Everything named here still imports, resolves, and runs for the rest of 2.x.

The four plan-producing operators are the first group. Both registered versions of `multipart_query`, `nl2query_router`, `plan_discover`, and `query_breakdown` carry the lifecycle flag, so eight of the 72 cards are marked. The second group is the refinement seam for every operator: `refiner()`, `refine()`, `PipelinePlanner.plan_refinement()`, `RefinableOperator`, `DeclarativeOperator`, the refiner helpers those operator modules export, and the four `__refine` tools on the MCP adapter.

Read the flag off a card rather than keeping your own list of names:

```python
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
going_away = sorted(card.operator_id for card in registry.list_cards() if card.deprecated)

assert len(going_away) == 8
assert registry.resolve("plan_discover@2.0.0") is not None
```

Discovery and exact resolution are unchanged. `find()`, embedding search, `get_card()`, and `resolve()` all still return deprecated cards.

### Warnings

A deprecated call emits one `BlueDataOpsDeprecationWarning` per top-level entry, reported against your calling line. The category subclasses `DeprecationWarning`, so CPython's default filters hide it outside `__main__`. Where the compatibility use is deliberate, silence that one category rather than promoting warnings process-wide:

```python
import warnings

from blue_data_ops import BlueDataOpsDeprecationWarning

warnings.filterwarnings("ignore", category=BlueDataOpsDeprecationWarning)
```

### Planning admits active cards only

`discover()` still returns deprecated cards, and `plan()` drops them before admission without charging them against `max_discovery_cards`. The same request can therefore report different cards through the two calls, and `plan()` can reach active cards that the limit used to hide behind deprecated ones:

```python
from blue_data_ops.plan import DiscoveryQuery, PipelinePlanner, PlanningRequest, RulePlanGenerator

planner = PipelinePlanner(registry, RulePlanGenerator())
request = PlanningRequest(
    goal="summarize a query",
    discovery_queries=(DiscoveryQuery("query"),),
    max_discovery_cards=2,
)

assert [card.operator_id for card in planner.discover(request).cards] == [
    "multipart_query@2.0.0",
    "nl2query_router@2.0.0",
]
```

`DataPipeline`, `PipelineExecutor`, rule-based generation, and the injected-client LLM path are unaffected and stay the supported way to plan and run operators locally.

### Stored plans

A saved plan record that names a deprecated operator still parses, and its ids still resolve. Given a `record` written earlier by `DataPipeline.to_dict()`, walk the restored plan to see what it depends on:

```python
from blue_data_ops.plan import DataPipeline

restored = DataPipeline.from_dict(record)
inventory = {}
for entity in restored.get_entities(type="OPERATOR").values():
    operator_id = entity["operator_id"]
    registry.resolve(operator_id)
    inventory[operator_id] = registry.get_card(operator_id).deprecated
```

Whether that plan can execute has not changed. A node holding a plan-producing operator was rejected by `PipelineExecutor.preflight()` before this release and still is, because such a node is not materialized.

See [COMPATIBILITY.md](COMPATIBILITY.md#deprecated-in-280) for the full statement, including what 3.0.0 removes.

## Utility compatibility

`blue_data_ops.utils` carries over the Blue helper functions that operators and tools rely on, so code moving off `blue.utils` keeps the same calls and only changes the import path. The functions match Blue's behavior, including its return types and edge cases.

| `blue.utils` | `blue_data_ops.utils` |
|---|---|
| `type_utils.string_to_python_type` | `string_to_python_type` |
| `type_utils.create_pydantic_model` | `create_pydantic_model` |
| `type_utils.validate_parameter_type` | `validate_parameter_type` |
| `tool_utils.annotation_to_type_str` | `annotation_to_type_str` |
| `tool_utils.extract_signature` | `extract_signature` |
| `tool_utils.convert_type_string_to_mcp` | `convert_type_string_to_mcp` |
| `json_utils.merge_json` | `merge_json` |
| `json_utils.json_query` | `json_query` |
| `json_utils.json_query_set` | `json_query_set` |
| `uuid_utils.create_uuid` (`split_ids`, `extract_sid`, `extract_name_id`, `extract_prefix`, `concat_ids`) | `create_uuid` (same names) |
| `string_utils.safe_substitute` | `safe_substitute` |

```python
from blue_data_ops.utils import validate_parameter_type, safe_substitute

validate_parameter_type("3", "int")           # True: same lax coercion as Blue
safe_substitute("$greeting", greeting="hi")   # "hi"
```

Helpers outside the operator surface are not carried over. Most of `json_utils`, the base64 helpers in `string_utils`, and the logging helpers are omitted. The similarity and service helpers work differently here; see [COMPATIBILITY.md](COMPATIBILITY.md).

## Compatibility

See [COMPATIBILITY.md](COMPATIBILITY.md) for deliberate behavior differences that callers and maintainers should preserve across upgrades.

## Running tests

With the `dev` extra installed (see [Installation](#installation)), from the `lib/` directory:

```bash
python -m pytest
```

## Project structure

```
lib/
├── COMPATIBILITY.md             # supported modes and compatibility boundaries
├── MANIFEST.in                  # source-distribution examples and reference files
├── OPERATORS.md                 # generated 36-operator attribute and outcome reference
├── examples/                    # runnable base, SQLite, ML, vector, refinement, and LLM calls
├── pyproject.toml
├── scripts/                     # reference generator and installed-LiteLLM check
├── src/
│   └── blue_data_ops/
│       ├── __init__.py           # public exports
│       ├── operators/
│       │   ├── operator.py       # Operator base
│       │   ├── types.py          # AttributeSpec, DataBundle, error types
│       │   ├── registry.py       # OperatorRegistry (pinned name@version)
│       │   └── *_operator.py     # one module per operator
│       ├── utils/                # Blue-compatible type, tool, JSON, uuid, string helpers
│       ├── llm/                  # LLM client, templating, resolution (litellm-backed)
│       ├── operator_skills/      # versioned resources keyed by exact operator id
│       ├── plan/
│       │   ├── pipeline.py       # serializable DataPipeline record
│       │   ├── refiner.py        # operator-level refinement
│       │   ├── executor.py       # local PipelineExecutor
│       │   ├── planner.py        # PipelinePlanner, rule templates, planning records
│       │   ├── context.py        # DataScope, snapshots, planning error vocabulary
│       │   └── openai_generator.py  # OpenAIPlanGenerator (extra: openai)
│       ├── data/
│       │   ├── registry_seam.py  # facade over a blue-data DataRegistry
│       │   └── provider.py       # registry resolution + default cached provider
│       └── tools/                 # compatibility Tool and helper interfaces
└── tests/
    ├── doubles/                  # in-memory seam and source doubles
    └── unit/
```

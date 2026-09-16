# blue-data-ops

`blue-data-ops 3.0.0` is a standalone Python package for Blue data operators. It includes record transforms, registry-backed database operations, pinned operator discovery, structured execution results, and a local pipeline planner. Operator input and output use `list[list[dict]]`, a list of record groups.

## Requirements

- Python 3.11+
- `blue-data` 0.1.0 or later. This is an eager dependency and must be importable with `blue_data_ops`.

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
  "blue-data-ops[ml,vector,llm]==3.0.0"
```

The artifact index must also provide `blue-data>=0.1.0`. The sibling-checkout commands are the direct path for a contributor.

The optional extras are `ml` for `classify`, `cluster`, and `sklearn_estimator`, `vector` for the three vector operators, `llm` for `nl2llm`, `nl2sql`, `nl2bn`, and the `semantic_*` operators, and `openai` for `OpenAIPlanGenerator`.

```bash
python -m pip install -e "./blue-data-ops/lib[openai]"
```

The `openai` extra pins `openai>=2.54,<3`. The SDK is imported only when an `OpenAIPlanGenerator` needs to create its own client. An LLM-backed `run()` call that cannot import its extra returns an `EXECUTION_FAILED` error in `ExecMeta`.

Read the distribution version separately from an operator-card version:

```python
from importlib.metadata import version

assert version("blue-data-ops") == "3.0.0"
```

## Usage

The credential-free examples live in the repository's top-level `examples/` directory, one level above the directory containing this README. Run them from the repository root:

```bash
python examples/quickstart/core_quickstart.py
PYTHONPATH=examples python examples/quickstart/sqlite_quickstart.py
```

`sqlite_quickstart.py` creates a temporary SQLite database, registers it, performs an insert, and removes the database when it exits. It imports a helper module kept at the examples root, which is what the `PYTHONPATH` prefix is for. `examples/README.md` covers the ML, vector, planner, and live-provider examples. The examples tree is part of the source checkout only; no distribution carries it. The generated `OPERATORS.md` reference for the 33 active exact IDs does ship: in a source checkout it sits beside this README, and in an extracted source distribution it sits at the extraction root. A wheel exposes this README through distribution metadata but does not install those top-level files. To browse them after a wheel install, download and extract the matching `blue-data-ops==3.0.0` source distribution from the same artifact index.

### Registry roles

Use `default_registry()` for the raw compatibility view, `active_registry()` for ordinary 3.0 discovery and execution, and `versioned_registry()` when migration code needs retained history. The active factory has 33 exact cards: 12 at `@2.0.0` and 21 at `@3.0.0`. The history factory has 87 cards.

<!-- blue-data-ops-test: registry-roles -->
```python
from blue_data_ops.operators import active_registry, default_registry, versioned_registry

raw = default_registry()
raw_override = default_registry(avg="2.7.4")
ordinary = active_registry()
history = versioned_registry()

assert raw.resolve("avg@1.0.0").operator_id == "avg@1.0.0"
assert raw_override.resolve("avg@2.7.4").operator_id == "avg@2.7.4"
assert ordinary.resolve("avg@3.0.0").operator_id == "avg@3.0.0"
assert history.resolve("avg@2.0.0").operator_id == "avg@2.0.0"
assert len(raw.list_cards()) == 33
assert len(ordinary.list_cards()) == 33
assert len(history.list_cards()) == 87
```

`default_registry(**versions)` preserves the legacy per-name override for the 33 retained names. An override becomes that card's version after semver validation. For the 21 outcome-enabled names, only an exact `"3.0.0"` override selects the outcome implementation; other versions use the raw implementation. Unknown names are ignored. These cards are raw: their `tags` and `when_to_invoke` fields are empty.

Registry construction does not grant planning authority. A raw override card is not automatically planning-authorized: core 3.0 rejects every card from `default_registry()` as planning authority, even when its ID text matches a supported v2/v3 ID. Use `active_registry()` for the ordinary reviewed selection, or use `versioned_registry()` with an exact allowlist when a rule-based plan deliberately needs a supported retained v2/v3 built-in. Caller-created v2 cards require a caller-owned registry and rule or generator. `OpenAIPlanGenerator` accepts only supported package built-ins from an enriched package registry.

The private in-memory tables that distinguish reviewed built-ins from raw cards are integrity controls for ordinary planner admission. They are not a tamper-proof isolation boundary against arbitrary same-process code that mutates private registry state.

`OperatorRegistry.resolve()` accepts only `name@<MAJOR.MINOR.PATCH>` and raises `ResolveError` on a miss. The eight retired IDs for `multipart_query`, `nl2query_router`, `plan_discover`, and `query_breakdown` at versions 1 and 2 are absent from all 3.0 factories. There is no latest-version fallback at resolution time.

### Direct execution

Concrete operator classes retain their raw v1-compatible `apply()` and `invoke()` calls. `apply()` invokes the transform directly. `invoke()` runs boolean validation first and returns `None` when validation fails. Raw exceptions are not converted to execution metadata. Use `run()` for canonical defaults, structured errors, and normalized empty output.

```python
from blue_data_ops import SelectOperator

operator = SelectOperator()
data = [[{"name": "a", "score": 3}, {"name": "b", "score": 9}]]
attributes = {"operand_key": "score", "operand": ">", "operand_val": 5}

output = operator.invoke(data, attributes)
assert output == [[{"name": "b", "score": 9}]]

output_data, output_attributes, meta = operator.run(data, attributes)
assert output_data == output
assert output_attributes == {}
assert meta.is_empty is False
assert meta.errors == []
```

The internal `_execute()` hook returns `FunctionResult(output_data, output_attributes)`. `run()` normalizes that result and gives every call a fresh output-attributes mapping. `ExecMeta` has `is_empty`, `errors`, `logs`, and `traces`. Error records carry a category, code, exact operator ID, stage, message, retryability flag, and optional suggestion. Categories are `RECOVERABLE`, `FAILED`, and `TIMEOUT`; stages cover defaults, validation, execution, normalization, and the retained error vocabulary.

A successful empty result is `[[]]` with `is_empty=True` and no errors. Mixed multi-group output preserves every group, including empty groups. Invalid input or an execution failure is contained as `[[]]` with an error record rather than raised by `run()`.

Set a wrapper deadline with `properties={"execution.timeout_seconds": <finite-positive-number>}`. The wrapper never retries. The legacy `properties["timeout"]` field remains observable but does not set the deadline.

The three-argument `validate(input_data, attributes, properties)` checks the live attribute schema and returns `False` for invalid values. `explain(output, input_data, attributes)` describes a completed transform, taking the output first. `attributes`, `is_required(name)`, and `default_of(name)` expose the declared attributes. Operators also retain the Blue Tool/Operator signature and parameter metadata surface.

### Registry-backed data operations

`create_database`, `create_table`, `insert_table`, and `data_discover` need a `blue-data` registry. The source-checkout file `examples/quickstart/sqlite_quickstart.py` contains a complete setup. Its central call is:

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
    assert output == [[]]
    assert meta.errors == []
```

You may inject a raw `DataRegistry`; `resolve_registry()` wraps it. Without an injection, pass both `platform.name` and `data_registry.name`. The default provider creates and caches an in-memory registry for that pair.

## Operators

| Category | Active logical operators |
|---|---|
| Filter / shape | `select`, `project`, `delete`, `insert` |
| Join / set | `join`, `union`, `intersect` |
| Aggregate | `argmax`, `argmin`, `max`, `min`, `avg`, `sum` |
| Text | `normalize_text`, `segment_text` |
| ML (`ml` extra) | `classify`, `cluster`, `sklearn_estimator` |
| Vector (`vector` extra) | `vector_embed`, `vector_search`, `vector_similarity` |
| LLM (`llm` extra) | `nl2llm`, `nl2sql`, `nl2bn`, `semantic_extract`, `semantic_filter`, `semantic_join`, `semantic_project`, `semantic_transform` |
| Registry-backed | `create_database`, `create_table`, `insert_table`, `data_discover` |

`sklearn_estimator` accepts any case-insensitive class name returned by `sklearn.utils.all_estimators()`. It trains one in-memory estimator from the first input group, then writes predictions, cluster labels, or transformed vectors to each record. Set `properties.algorithm` and `attributes.vector_key`; classifiers and regressors also require `attributes.label_key`. The fitted model is not persisted.

`nl2llm`, `nl2sql`, `nl2bn`, and the `semantic_*` operators send requests through LiteLLM. Configure the model through call properties; the default is `openai.model: gpt-4o`. `classify` and `sklearn_estimator` use NumPy and scikit-learn. Registry-backed operators use the `blue-data` seam.

This short `nl2llm` call uses a live provider:

```python
from blue_data_ops.operators import active_registry

operator = active_registry().resolve("nl2llm@3.0.0")
output, _, meta = operator.run(
    [[]],
    {
        "query": "Return two example products",
        "attrs": [{"name": "name", "type": "string"}],
    },
    {"openai.model": "gpt-4o-mini"},
)
assert meta.errors == []
```

Install `[llm]` and configure the provider credential before running it. The source-checkout file `examples/feature-demos/nl2sql_sqlite.py` builds a real SQLite schema and defaults to `execute_query=False`. Its case-insensitive prefix check is not a SQL parser or sandbox; callers remain responsible for permissions and query safety.

### Discovery

`find(query, tags=...)` returns cards using deterministic text scoring and an optional exact AND tag filter. A blank query with tags performs tag-only discovery; a blank query without tags returns no cards. `find()` strips surrounding whitespace and lowercases each requested filter token. A filter passes shape validation when the result is nonempty, contains no whitespace, and includes at least one hyphen. It is then matched as a complete tag. Shape validation does not check taxonomy membership or hyphen position, so `domain-`, `-vector`, and `domain_-vector` are well-formed filters but match no built-in card. A malformed filter raises `DiscoveryError`; a well-formed tag that is not present matches no cards. There is no OR or negative-tag syntax. `find_latest(name)` returns the highest version for one exact name. Ordinary discovery should use the active registry.

Built-in active cards use five required axes and one optional axis. A tag states something true in at least one productive public mode.

| Axis | What it tells the caller | Built-in cardinality |
|---|---|---|
| `domain-*` | Primary subject area, not the output type | exactly one |
| `flow-*` | Valid role in a pipeline | one or more |
| `accepts-*` | Kind of upstream input consumed; `accepts-none` means records are not consumed | one or more |
| `produces-*` | Result kind or externally visible effect | one or more |
| `capability-*` | Operation family or specific action | one or more |
| `requires-*` | Unconditional operator-specific runtime requirement | zero or more |

Values are flat exact labels, not a hierarchy. A card may carry both a broad and a specific capability, such as `capability-reduction` and `capability-average`. `accepts-none` does not make the `input_data` argument optional; pass an empty bundle such as `[[]]`. The `requires-*` axis covers operator-specific requirements and does not replace the package installation requirements above. Source checkouts and source distributions include the generated `OPERATORS.md` tag taxonomy with every value found on the active cards and each card's tags. The active `domain-plan` value is a retained compatibility label on `data_discover@2.0.0`; use `capability-metadata-search` or `produces-metadata` when searching for its behavior. It returns metadata and does not produce a plan.

<!-- blue-data-ops-test: tag-discovery -->
```python
from blue_data_ops.operators import active_registry

catalog = active_registry()

available_tags = sorted({tag for card in catalog.list_cards() for tag in card.tags})
assert "capability-metadata-search" in available_tags

vector_steps = catalog.find("", tags=["domain-vector", "flow-transform"])
assert [card.operator_id for card in vector_steps] == [
    "vector_embed@3.0.0",
    "vector_search@3.0.0",
]

cards = catalog.find("filter", tags=["domain-relational", "flow-transform"])
assert [card.operator_id for card in cards] == ["select@2.0.0"]
operator = catalog.resolve(cards[0].operator_id)
```

Inspect `card.tags` when composing filters dynamically. Built-in package cards use the closed vocabulary above. `register()` preserves arbitrary custom tags for compatibility. Filters are normalized as described above, so a custom tag is discoverable only when its stored value equals the normalized filter.

`OperatorEmbeddingIndex` adds embedding search. The caller supplies the embedder and its `space_id`; the package does not choose or install an embedding model.

```python
from blue_data_ops.operators import OperatorEmbeddingIndex, active_registry


class KeywordEmbedder:
    space_id = "readme-keywords-v1"

    def __call__(self, texts: tuple[str, ...]) -> list[list[float]]:
        terms = ("filter", "join", "query")
        return [[1.0, *(float(term in text.casefold()) for term in terms)] for text in texts]


catalog = active_registry()
index = OperatorEmbeddingIndex.build(catalog, KeywordEmbedder())
cards = index.find("filter rows", tags=["produces-data"])
operator = catalog.resolve(cards[0].operator_id) if cards else None
```

`build()` sends every card's name, invocation guidance, description, and ordered tags to the embedder in one batch. With a nonblank query, `find()` returns every tag-matching card in cosine order. It applies no threshold or limit; callers limit the returned list. Invalid vectors, callback failures, and stale snapshots raise `EmbeddingDiscoveryError` with a stable `reason`.

### Operator skill resources

`blue_data_ops.operator_skills` ships 54 exact-version packages: 33 retained `@2.0.0` packages and 21 outcome packages at `@3.0.0`. Every active exact ID has a package. All 54 packages declare levels 2 and 3. `load()` defaults to level 2, which combines the card and live attribute schema with `Operator.md`; level 3 also loads `examples.md`. `describe().declared_levels` reports the levels available for a package. No package in 3.0 includes level-4 `history.md`, so requesting level 4 or another unsupported level raises `OperatorSkillLoadError` with code `NOT_AVAILABLE`. Loading a skill does not invoke the operator or add its text to planner or provider input.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import active_registry

registry = active_registry()
loader = OperatorSkillLoader(registry)
skill = loader.load("nl2sql@3.0.0", level=3)

assert skill.card is registry.get_card("nl2sql@3.0.0")
assert skill.io.attributes["question"].required
```

History inspection is an intentional use of `versioned_registry()`:

```python
from blue_data_ops.operators import versioned_registry

history = versioned_registry()
loader = OperatorSkillLoader(history)
eligible_ids = set(loader.available_operator_ids())
matches = history.find("average", tags=["domain-arithmetic"])
skipped = next(card for card in matches if card.operator_id not in eligible_ids)

assert skipped.operator_id == "avg@1.0.0"
```

`avg@1.0.0` remains searchable in the history registry but has no skill package. Check `available_operator_ids()` before expansion. It validates the package index and intersects it with package-built cards in the loader's registry. `describe()` validates the selected card, index, and manifest, then reports declared resource kinds and levels without opening Markdown. Calling these methods in sequence rereads the index because the loader has no cache. `load()` and `read()` can still fail if a package changes between calls, and neither has a latest-version fallback. Custom registrations are not eligible.

## Outcome operators

The 21 exact `@3.0.0` outcome operators may add shallow `input_shape`, successful `output_shape`, and monotonic `elapsed_ms` measurements to `ExecMeta.traces`. `input_shape` is captured before validation for a structurally valid bundle. `output_shape` appears only after successful normalization. The counts do not alias later caller mutation. Missing measurements are unavailable, not zero.

The `nl2llm@3.0.0` built-in client may report a finite nonnegative `cost` in USD with `cost_basis="estimated"` after exactly one priced provider attempt. A proven local response-cache hit reports `cost=0.0`; provider prompt caching still counts as an attempt. Retries, failures, unknown prices, and injected clients omit those cost fields.

The generated `OPERATORS.md` file in source checkouts and source distributions binds each active exact ID to its live implementation and accepted success, empty, invalid, and failure coordinates. Unsupported coordinates stay labeled with their evidence limit.

## Pipelines and planning

`DataPipeline` is a serializable graph record. `PipelineExecutor` preflights exact IDs, graph structure, attributes, and reachability before execution. It executes nodes in stable topological order and stops at the first structured operator failure.

<!-- blue-data-ops-test: pipeline-execution -->
```python
from blue_data_ops.operators import active_registry
from blue_data_ops.plan import DataPipeline, PipelineExecutor

plan = DataPipeline(label="select high scores")
source = plan.define_input("records")
step = plan.define_operator(
    "select@2.0.0",
    attributes={"operand_key": "score", "operand": ">", "operand_val": 5},
)
result = plan.define_output("selected")
plan.set_plan_input(source)
plan.set_plan_output(result)
plan.connect_nodes(source, step)
plan.connect_nodes(step, result)

run = PipelineExecutor(active_registry()).execute(
    plan,
    [[{"name": "a", "score": 3}, {"name": "b", "score": 9}]],
)
assert run.output_data == [[{"name": "b", "score": 9}]]
assert run.succeeded
assert run.failed_node_id is None
assert len(run.node_runs) == 1

select_run = run.node_runs[0]
assert select_run.operator_id == "select@2.0.0"
assert select_run.output_data == run.output_data
assert select_run.output_attributes == {}
assert select_run.exec_meta.errors == []
```

`PipelineRun.output_data` is the final pipeline output. `PipelineRun.node_runs` records completed operator nodes in execution order; each `NodeRun` exposes `node_id`, `operator_id`, `status`, `output_data`, `output_attributes`, and the operator's `exec_meta`. Read `node.exec_meta.errors`, `is_empty`, `logs`, and `traces` for the structured outcome of that node. `failed_node_id` identifies the first failed node, and `succeeded` is true when it is absent.

`PipelineExecutor.preflight()` and `execute()` raise `PipelineError` for an unusable graph or input. Operator failures after preflight remain contained in `PipelineRun.node_runs[*].exec_meta`. Execution mutates node values and statuses on the supplied plan; round-trip a copy when the original record must stay unchanged.

`PipelinePlanner` runs discovery, bounded data-context collection, generation, selection, compilation, and preflight. A plan generator supplies candidate drafts; the planner owns the other stages.

```python
from blue_data_ops.operators import active_registry
from blue_data_ops.plan import (
    SELECT_THEN_AVERAGE_TEMPLATE,
    DiscoveryQuery,
    PipelinePlanner,
    PlanningRequest,
    RulePlanGenerator,
)

registry = active_registry()
planner = PipelinePlanner(
    registry,
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
assert all(not node.exec_meta.errors for node in run.execution.node_runs)
assert [step.operator_id for step in run.planning.selected.steps] == [
    "select@2.0.0",
    "avg@3.0.0",
]
```

`plan(request)` returns a `PlanningResult` with the request copy, discovery snapshot, candidates, selected draft, compiled pipeline, preflight result, and retained data context. `run(request, input_data)` adds a `PipelineRun`, while `execute(planning, input_data)` executes a copy of a prior planning result. `PlanningRequest` bounds discovery cards, candidates, steps, nodes, and edges. `RequireSinglePlan` is the shipped selector and accepts exactly one candidate; callers may inject a different selector.

`SELECT_THEN_AVERAGE_TEMPLATE` is the shipped filter-then-average rule. `project_then_aggregate_template(name)` supports `"avg"`, `"sum"`, `"min"`, and `"max"`. A `RulePlanTemplate` requires exact discovered operator metadata and caller-supplied attributes for every step. `RulePlanGenerator(rules)` evaluates rules in order and keeps their drafts; its default recognizes the built-in select-then-average request.

Planning failures raise `PlanningError`, a `ValueError` subclass whose `record` contains category, code, stage, message, retryability, and suggestion. Planning stages are `VALIDATION`, `DISCOVERY`, `DATA_CONTEXT`, `GENERATION`, `SELECTION`, `COMPILATION`, and `PREFLIGHT`. Planning raises because no partial pipeline exists to carry the record.

`PipelinePlanner` compiles admitted, supported exact operator IDs returned by its discovery snapshot. Without an allowlist, package built-ins are limited to the `active_registry()` selection. An exact allowlist may admit supported retained v2/v3 built-ins from `versioned_registry()`. A caller-owned registry and rule or generator may admit caller-created v2 cards; custom v1 and v3 cards are unsupported.

A generator that needs schema context receives `DataContextSnapshot`, never rows. `RegistryDataContextProvider` reads source properties, entity names, descriptions, and declared attribute types. Its default limits are 32 entities, 64 attributes per entity, 512 total attributes, 512 description characters, and 131072 serialized bytes. It reads no relations or rows and records `raw_rows: 0` in provenance. A request with `data_scope` requires a provider; a request without a scope does not touch the registry.

### OpenAI plan generation

`OpenAIPlanGenerator` makes one non-streaming Responses call per `generate()` and requires the `openai` extra.

```python
from blue_data_ops.operators import active_registry
from blue_data_ops.plan import OpenAIPlanGenerator, PipelinePlanner

registry = active_registry()
generator = OpenAIPlanGenerator(
    "gpt-4o",
    registry=registry,
    allowed_operator_ids=["select@2.0.0", "avg@3.0.0"],
)
planner = PipelinePlanner(registry, generator)
```

`allowed_operator_ids` is an authorization boundary. The same enriched package registry must have built each supported card, discovery must have returned it, and the card must not produce a side effect. Raw compatibility cards and caller-created cards are not accepted. The decoder checks the same set. Caller-supplied attributes are constraints that the model cannot drop or overwrite. An `nl2sql` step requires a supplied and disclosed schema snapshot.

Set `send_data_context=True` to disclose an available snapshot; otherwise the generator fails before importing the SDK or making provider traffic. Pass `client=` to inject a configured OpenAI client. Without one, the generator constructs `openai.OpenAI()` at first use. Each request uses `store=False`, disables SDK retries, and defaults to `timeout_seconds=60.0`, `max_output_tokens=4096`, and one candidate. Provider failures map to stable planning codes such as `GENERATOR_TIMEOUT`, `GENERATOR_RATE_LIMITED`, and `GENERATOR_UNAVAILABLE`; records exclude response bodies, request payloads, credentials, and provider-specific exception text.

## Migrating from 2.x

Core 3.0 removes the four plan-producing operator names, the refinement API, and their helper modules. Exact resolution of all eight retired v1/v2 package IDs now fails through the package registries. A saved `DataPipeline` containing one of those IDs still parses as data, then fails executor preflight because the active registry cannot resolve it.

The supported manual migration covers two cases. Replace a `DeclarativeOperator` used as an executable leaf with an ordinary `Operator` subclass. For one fixed graph, construct and execute a materialized `DataPipeline` directly, or implement `PlanGenerator.generate()` to return `Sequence[PlanDraft]` for `PipelinePlanner`.

This is a non-drop-in migration. Core 3.0 does not automatically refine an operator or expand old declarative plan definitions. The supported graph example covers one fixed linear expansion; it does not preserve dynamic alternatives, malformed-plan normalization, raw v1 refiner behavior, or a general `DeclarativeOperator` subclass hierarchy. Callers that need those semantics should remain on a compatible core 2.x/MCP 0.x pair, such as core 2.10.0 with MCP 0.12.0.

Use `active_registry()` for new work. Keep `versioned_registry()` only where code deliberately resolves retained 1.x or 2.x behavior. The supported migration boundary is stated above; source checkouts and source distributions also include `COMPATIBILITY.md` with per-surface details.

## Utility compatibility

`blue_data_ops.utils` carries the Blue helpers used by the operator surface: `string_to_python_type`, `create_pydantic_model`, `validate_parameter_type`, `annotation_to_type_str`, `extract_signature`, `convert_type_string_to_mcp`, `merge_json`, `json_query`, `json_query_set`, `create_uuid` and its ID helpers, and `safe_substitute`. Most unrelated Blue JSON, base64, and logging helpers are outside this package. Source checkouts and source distributions document service-client and similarity differences in `COMPATIBILITY.md`.

```python
from blue_data_ops.utils import safe_substitute, validate_parameter_type

assert validate_parameter_type("3", "int")
assert safe_substitute("$greeting", greeting="hi") == "hi"
```

## Compatibility

This README summarizes the compatibility and migration contracts needed by wheel-only users. Source checkouts and source distributions include `COMPATIBILITY.md` for the detailed per-surface matrix.

## Running tests

With the `dev` extra installed, run from `lib/`:

```bash
python -m pytest
```

## Project structure

```text
lib/
├── COMPATIBILITY.md             # compatibility and migration boundaries
├── MANIFEST.in                  # source-distribution resources
├── OPERATORS.md                 # generated 33-operator reference
├── pyproject.toml
├── scripts/                     # reference generator and install checks
├── src/blue_data_ops/
│   ├── operators/               # operator implementations and registries
│   ├── operator_skills/         # resources keyed by exact operator ID
│   ├── plan/                    # DataPipeline, planner, executor, generators
│   ├── data/                    # blue-data registry seam and provider
│   ├── llm/                     # LiteLLM-backed client support
│   ├── tools/                   # compatibility tool interfaces
│   └── utils/                   # Blue-compatible helper functions
└── tests/
```

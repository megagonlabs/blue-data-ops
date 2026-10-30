# Developer Guide

A task-oriented walkthrough of the Python library: run an operator, read what comes back, find an operator you did not know the name of, reach a real database, build and store a pipeline, and let the planner build one for you.
For the exact export list see [api-reference.md](api-reference.md); for per-operator attribute schemas see the generated [operator reference](../lib/OPERATORS.md), which is the source of truth for that detail.

Every block below runs on the base install.
The ML, vector, and LLM sections say which extra they need.

## Setup: pick a registry view

Start from `active_registry()`.
It is the ordinary 3.0 view, and it holds the 33 exact cards that current discovery and execution use.

```python
from blue_data_ops.operators import active_registry

registry = active_registry()
print(len(registry.list_cards()))   # 33
```

The other two views exist for narrower jobs.

| Factory | Cards | When you want it |
|---|---|---|
| `active_registry()` | 33 | everything ordinary: discovery, resolution, execution, planning |
| `default_registry()` | 33 | the raw v1-compatible view, when legacy code passes per-name version overrides |
| `versioned_registry()` | 87 | retained history, when migration code has to resolve a 1.x or 2.x card on purpose |

Raw cards from `default_registry()` carry no tags and no invocation guidance, and the planner rejects every one of them as planning authority even when the id text matches a supported version.
Use `active_registry()` unless you have a reason not to.

## Run an operator

`run()` is the call you want.
It materializes declared defaults, validates the attributes, runs the transform, normalizes empty output, and hands back three things: the output bundle, a fresh output-attributes mapping, and execution metadata.

```python
from blue_data_ops.operators import active_registry

operator = active_registry().resolve("select@2.0.0")
data = [[{"name": "a", "score": 3}, {"name": "b", "score": 9}]]
attributes = {"operand_key": "score", "operand": ">", "operand_val": 5}

output_data, output_attributes, meta = operator.run(data, attributes)
print(output_data)         # [[{'name': 'b', 'score': 9}]]
print(output_attributes)   # {}
print(meta.is_empty)       # False
```

Both the input and the output are `list[list[dict]]` — a list of record groups.
Most operators read the first group; `join`, `union`, `intersect`, and `classify` read two or more.
The output-attributes mapping is fresh on every call, so one operator cannot leak state into the next.

## Read the result

`ExecMeta` has four fields, and each answers a different question.

| Field | What it holds |
|---|---|
| `is_empty` | whether the result is an intentional empty bundle |
| `errors` | structured failure records, empty on success |
| `logs` | operator log lines |
| `traces` | measurements: shape counts, elapsed time, and cost where the operator reports it |

```python
from blue_data_ops.operators import active_registry

operator = active_registry().resolve("avg@3.0.0")
output_data, output_attributes, meta = operator.run([[{"total": 120.0}, {"total": 215.0}]], {"avg_key": "total"})
print(output_data)                   # [[{'avg': 167.5}]]
print(output_attributes)             # {'num_values_used': 2}
print(meta.traces["input_shape"])    # {'groups': 1, 'rows_per_group': [2]}
print(meta.traces["output_shape"])   # {'groups': 1, 'rows_per_group': [1]}
```

An empty result and a failure look different on purpose.
A successful empty result is `[[]]` with `is_empty=True` and no errors.
A contained failure is also `[[]]`, but `is_empty` is `False` and there is a record in `errors`.
Check `errors` first, then `is_empty`.

## Handle a failure

Invalid input does not raise.
It comes back as a record you can branch on.

```python
from blue_data_ops.operators import active_registry

operator = active_registry().resolve("select@2.0.0")
output_data, _, meta = operator.run(
    [[{"name": "a", "score": 3}]],
    {"operand_key": "score", "operand": "??", "operand_val": 5},
)
if meta.errors:
    record = meta.errors[0]
    print(record.category.value)     # RECOVERABLE
    print(record.code.value)         # INVALID_INPUT
    print(record.stage.value)        # VALIDATE
    print(record.operator_id)        # select@2.0.0
    print(record.retryable)          # False
    print(record.suggestion)         # supply a supported operand and a nonnegative eps value
```

Categories are `RECOVERABLE`, `FAILED`, and `TIMEOUT`.
`retryable` is the operator's own judgement about whether the same call could succeed again; a validation failure never is.

LLM connection, timeout, rate-limit and server-error retry hints require matching transport or HTTP-response evidence through the supported OpenAI/LiteLLM path. A local parsing failure or an unclassified wrapper reports a non-retryable request failure. Other providers can therefore lose retry hints when their wrappers do not retain supported evidence. With the tested LiteLLM 1.106.5/OpenAI 2.54.0 stack, a plain connection failure is wrapped as a server error and receives generic advice; read timeouts and HTTP 429/503 responses retain matching hints. This public advice describes the final error record; the LLM client's configured internal retry attempts are separate. A retry hint does not guarantee that an earlier attempt had no effects.

## Know which boundary raises

Operator execution returns its failures.
Everything that has no partial result to attach a record to raises instead.

| Boundary | Failure arrives as |
|---|---|
| `Operator.run()` | an `ErrorRecord` in `ExecMeta.errors` |
| `OperatorRegistry.resolve()` | `ResolveError` |
| `registry.find()` with a malformed tag filter | `DiscoveryError` |
| `OperatorEmbeddingIndex.build()` or `.find()` | `EmbeddingDiscoveryError`, with a stable `reason` |
| `OperatorSkillLoader` | `OperatorSkillLoadError`, with a stable `code` |
| `PipelineExecutor.preflight()` and bad execution input | `PipelineError` |
| an operator failing *after* preflight | `node_run.exec_meta`, not an exception |
| `PipelinePlanner.plan()` and `.run()` | `PlanningError`, carrying a structured `record` |
| the LLM client's transport and provider failures | `LLMError` |

```python
from blue_data_ops.operators import ResolveError, active_registry

registry = active_registry()
try:
    registry.resolve("avg")
except ResolveError as error:
    print(error)   # not a pinned operator id (expected name@<MAJOR.MINOR.PATCH>): 'avg'
```

## Inspect an operator before you call it

Each operator declares its attributes, and the declaration is readable at runtime.
This is what you want when you are generating a form, a prompt, or a validation layer rather than hand-writing a call.

```python
from blue_data_ops.operators import active_registry

registry = active_registry()
operator = registry.resolve("avg@3.0.0")
print(sorted(operator.attributes))                   # ['avg_key', 'output_key']
print(operator.is_required("avg_key"))               # True
print(operator.default_of("output_key"))             # avg
print(operator.attributes["avg_key"].description)    # The key to average the values for

card = registry.get_card("avg@3.0.0")
print(card.name, card.version)                       # avg 3.0.0
print(card.tags[:2])                                 # ('domain-arithmetic', 'flow-aggregate')
```

`explain()` describes a transform after the fact.
It takes the output, the input, and the attributes, in that order, and returns record counts and a transformation ratio.

```python
from blue_data_ops.operators import active_registry

operator = active_registry().resolve("select@2.0.0")
data = [[{"name": "a", "score": 3}, {"name": "b", "score": 9}]]
attributes = {"operand_key": "score", "operand": ">", "operand_val": 5}
output_data, _, _ = operator.run(data, attributes)
summary = operator.explain(output_data, data, attributes)
print(summary["num_input_records"], summary["num_output_records"])   # 2 1
print(summary["transformation_ratio"])                              # 0.5
```

## Bound a call with a deadline

Pass a finite positive `execution.timeout_seconds` in the call properties.
The wrapper enforces it once and never retries.

```python
from blue_data_ops.operators import active_registry

operator = active_registry().resolve("select@2.0.0")
output_data, _, meta = operator.run(
    [[{"score": 9}]],
    {"operand_key": "score", "operand": ">", "operand_val": 5},
    {"execution.timeout_seconds": 5.0},
)
print(output_data, meta.errors)   # [[{'score': 9}]] []
```

A breach returns `OPERATOR_TIMEOUT` with category `TIMEOUT` in `errors`. The deadline bounds waiting; it does not stop the worker, roll back writes or prevent later side effects. Without `execution.timeout_seconds`, `run()` has no deadline. Raw `apply()` and `invoke()` gain no deadline. The legacy bare `timeout` property is inert for operator execution and is no longer seeded in instance metadata. Provider-level LLM `timeout` forwarding is a separate setting. On MCP, a registry tool's timeout returns to the caller while the worker keeps that server's registry lane until the worker finishes; see [deployment setup](mcp.md#deployment-data-registry).

Retained v1/v2 semantic versions validate model replies and report malformed replies through `exec_meta.errors`. Their `semantic_filter` accepts booleans and trimmed, case-insensitive string pairs `true`/`false`, `yes`/`no`, `1`/`0` and `include`/`exclude`. Legacy join accepts complete pair objects with booleans or the strings `true`, `yes`, `1`, `match` and `join` for a match and `false`, `no`, `0` and `exclude` for no match; `include` is rejected. Active v3 join still requires native booleans. Active v3 `semantic_filter` accepts only booleans and `true`/`false` strings. Valid negative and empty replies remain successful. See [legacy semantic response handling](../lib/COMPATIBILITY.md#legacy-semantic-response-handling) before selecting an exact v1/v2 semantic operator.

For retained semantic joins, an embedding preparation failure falls back to all Cartesian pairs, requiring ceil(N*M/batch) model calls, where N and M are the two group sizes and batch is `batch_size`. A failure after optimization sampling can add the sample call to that fallback. The `estimate_cost`/`max_llm_calls` check uses the up-front estimate; a fallback can make more calls than the limit.

## Find an operator by tag

`find(query, tags=...)` scores the query text and ANDs the tag filters.
Built-in cards use six axes, all flat exact labels.

```python
from blue_data_ops.operators import active_registry

catalog = active_registry()

# Tag-only discovery: blank query, filters do the work.
print([card.operator_id for card in catalog.find("", tags=["domain-vector", "flow-transform"])])

# Text plus filters.
print([card.operator_id for card in catalog.find("filter", tags=["domain-relational", "flow-transform"])])

# A blank query with no filters is not a wildcard.
print(len(catalog.find("")))   # 0
```

Filters are stripped and lowercased, then matched as whole tags.
A filter passes shape validation when it is nonempty, contains no whitespace, and holds at least one hyphen — which means `domain-`, `-vector`, and `domain_-vector` are all well-formed and all match nothing.
A malformed filter raises `DiscoveryError`; a well-formed absent tag just returns no cards.
There is no OR syntax and no negation.

```python
from blue_data_ops.operators import DiscoveryError, active_registry

try:
    active_registry().find("", tags=["no hyphen here"])
except DiscoveryError as error:
    print(error)   # malformed filter tag 'no hyphen here'
```

Read `card.tags` when you are composing filters dynamically.
`register()` keeps arbitrary custom tags, but a custom tag is only discoverable when its stored value equals the normalized filter.

## Find an operator by embedding

`OperatorEmbeddingIndex` ranks the same cards by cosine similarity.
You own the embedder and its `space_id`; the package will not pick a model for you.

```python
from blue_data_ops.operators import OperatorEmbeddingIndex, active_registry


class KeywordEmbedder:
    space_id = "guide-keywords-v1"

    def __call__(self, texts: tuple[str, ...]) -> list[list[float]]:
        terms = ("filter", "average", "join")
        return [[1.0, *(float(term in text.casefold()) for term in terms)] for text in texts]


catalog = active_registry()
index = OperatorEmbeddingIndex.build(catalog, KeywordEmbedder())
cards = index.find("filter rows", tags=["produces-data"])
print([card.operator_id for card in cards][:3])
operator = catalog.resolve(cards[0].operator_id)
print(operator.operator_id)
```

`build()` batches every card's name, guidance, description, and ordered tags into one embedder call.
`find()` returns every tag-matching card in cosine order with no threshold and no limit, so truncate the list yourself.
An invalid vector, a failing callback, or a stale snapshot raises `EmbeddingDiscoveryError` with a stable `reason` such as `BUILD_FAILED`.

## Load an operator's resource package

`operator_skills` ships 54 exact-version packages: 33 retained at `@2.0.0` and 21 outcome packages at `@3.0.0`.
Loading one reads text about the operator.
It does not call the operator, and it does not add anything to planner or provider input.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import active_registry

registry = active_registry()
loader = OperatorSkillLoader(registry)

descriptor = loader.describe("nl2sql@3.0.0")
print(descriptor.declared_kinds)     # ('guide', 'examples')
print(descriptor.declared_levels)    # (2, 3)

skill = loader.load("nl2sql@3.0.0", level=3)
print(skill.card.operator_id)                      # nl2sql@3.0.0
print(skill.io.attributes["question"].required)    # True
```

Level 2 is the default and combines the card and the live attribute schema with the operator guide.
Level 3 adds worked examples.
Nothing in 3.0 declares level 4, so asking for it raises `OperatorSkillLoadError` with code `NOT_AVAILABLE`.

Check eligibility before you expand a card from the history view.
Not every historical card has a package.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

history = versioned_registry()
loader = OperatorSkillLoader(history)
eligible = set(loader.available_operator_ids())
print(len(eligible))   # 54

matches = history.find("average", tags=["domain-arithmetic"])
skipped = next(card for card in matches if card.operator_id not in eligible)
print(skipped.operator_id)   # avg@1.0.0
```

`available_operator_ids()` revalidates the package index every call, because the loader holds no cache.
A package that changes between two calls can make the second one fail, and there is no latest-version fallback.

## Work against a real database

Six operators reach a database through a `blue-data` registry: `create_database`, `create_table`, `insert_table`, `data_discover`, `nl2sql`, and `nl2bn`.
Wrap the registry in a `RegistrySeam` and pass it in the call properties.
This block creates a throwaway SQLite database, makes a table, inserts a row, reads it back, and finds the table by search.

```python
from tempfile import TemporaryDirectory

from blue_data.registry.data_registry import DataRegistry
from blue_data.source.json.memory_json_source import MemoryJSONSource
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource
from blue_data_ops import RegistrySeam
from blue_data_ops.operators import active_registry

registry = active_registry()
with TemporaryDirectory() as directory:
    source = SQLiteDBSource(
        "demo_sqlite",
        properties={"connection": {"protocol": "sqlite", "database_directory": directory}},
    )
    data_registry = DataRegistry(store=MemoryJSONSource(), rebuild=False)
    data_registry.register_source(source)
    data_registry.sync_source(source.name, recursive=True)
    seam = RegistrySeam(data_registry)
    properties = {"data_registry": seam}

    _, _, created = registry.resolve("create_database@2.0.0").run(
        [[]], {"source": "demo_sqlite", "database": "shop"}, properties
    )
    print(created.errors)   # []

    _, _, table = registry.resolve("create_table@2.0.0").run(
        [[]],
        {
            "source": "demo_sqlite",
            "database": "shop",
            "collection": "public",
            "table": "orders",
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "region", "type": "TEXT"},
                {"name": "total", "type": "REAL"},
            ],
        },
        properties,
    )
    print(table.errors)   # []

    inserted, insert_attributes, insert_meta = registry.resolve("insert_table@3.0.0").run(
        [[{"id": 1, "region": "east", "total": 215.0}]],
        {"source": "demo_sqlite", "database": "shop", "table": "orders"},
        properties,
    )
    print(insert_attributes, insert_meta.errors)   # {'num_rows_insert': 1} []

    print(seam.execute_query("SELECT id, total FROM orders", "demo_sqlite", "shop", "public"))

    discovered, _, discover_meta = registry.resolve("data_discover@2.0.0").run(
        [[]],
        {"search_query": "orders", "approximate": False, "concept_type": "entity"},
        properties,
    )
    print([record["name"] for record in discovered[0]])   # ['orders']
```

`data_discover` returns `type`, `name`, `id`, and `scope` for each match, plus a search
`score` when available. A source may also include `properties.kind` when it names a
supported source family. Discovery does not return stored descriptions, connection
settings, or metadata for any record type. `include_metadata=True` is rejected with an
input error.

Blue Platform 1.0 and 1.1 returned descriptions and raw properties from the registry.
This package uses a narrower discovery result because registered records can contain
connection details or arbitrary text. Use the returned name and scope to select a source
or schema record; the operator that uses the source resolves its connection through the
registry.
Pass `scope` to narrow a search. The `source`, `database`, and `collection` fields
refine an explicit scope.

`columns` is a list of `{"name": ..., "type": ...}` mappings; a bare type mapping fails validation.
SQLite sources always resolve to the `public` collection, whatever you pass.
The seam above is one of three ways to supply the registry.

| What you pass in `properties` | What happens |
|---|---|
| `{"data_registry": seam}` | used as given |
| `{"data_registry": raw_data_registry}` | `resolve_registry()` wraps the raw `blue_data` registry in a seam |
| `{"platform.name": ..., "data_registry.name": ...}` | the default provider builds and caches an in-memory registry for that pair |
| neither | `resolve_registry()` returns `None` and the operator reports a failure |

## Build a pipeline by hand

`DataPipeline` is a graph record: input nodes, operator nodes, output nodes, and edges.
`PipelineExecutor` preflights the whole thing before running any of it.

```python
from blue_data_ops.operators import active_registry
from blue_data_ops.plan import DataPipeline, PipelineExecutor

plan = DataPipeline(label="average the high scores")
source = plan.define_input("records")
select = plan.define_operator(
    "select@2.0.0",
    attributes={"operand_key": "score", "operand": ">", "operand_val": 5},
)
average = plan.define_operator("avg@3.0.0", attributes={"avg_key": "score"})
sink = plan.define_output("mean")
plan.set_plan_input(source)
plan.set_plan_output(sink)
plan.connect_nodes(source, select)
plan.connect_nodes(select, average)
plan.connect_nodes(average, sink)

run = PipelineExecutor(active_registry()).execute(
    plan,
    [[{"name": "a", "score": 3}, {"name": "b", "score": 9}, {"name": "c", "score": 11}]],
)
print(run.succeeded)                                  # True
print(run.output_data)                                # [[{'avg': 10.0}]]
print(len(run.node_runs))                             # 2
print([node.operator_id for node in run.node_runs])   # ['select@2.0.0', 'avg@3.0.0']
```

`PipelineRun.output_data` is the final output.
`node_runs` holds one `NodeRun` per completed operator node in execution order, each exposing `node_id`, `operator_id`, `status`, `output_data`, `output_attributes`, and that node's `exec_meta`.
Pipeline edges carry `output_data`. Each `NodeRun.output_attributes` records that
operator's additional results. The next operator receives its planned input
attributes, independent of the preceding node's output attributes.

A structured operator failure stops execution without raising.
Read the failed node's metadata to find out why.

```python
from blue_data_ops.operators import active_registry
from blue_data_ops.plan import DataPipeline, PipelineExecutor

plan = DataPipeline(label="reject bad attributes")
source = plan.define_input("records")
step = plan.define_operator(
    "select@2.0.0",
    attributes={"operand_key": "score", "operand": "??", "operand_val": 5},
)
sink = plan.define_output("selected")
plan.set_plan_input(source)
plan.set_plan_output(sink)
plan.connect_nodes(source, step)
plan.connect_nodes(step, sink)

run = PipelineExecutor(active_registry()).execute(plan, [[{"score": 9}]])
print(run.succeeded)                                 # False
print(run.failed_node_id is not None)                # True
print(run.node_runs[0].exec_meta.errors[0].code.value)   # INVALID_INPUT
```

Execution mutates node values and statuses on the plan you handed it.
Round-trip a copy when the original record has to stay unchanged.

## Store and replay a pipeline

`to_dict()` is the portable serialization boundary, and `from_dict()` reads it back.
Operator entities store only pinned ids, so a stored plan never carries a bare name, a deployment route, or a host address.

```python
import json

from blue_data_ops.operators import active_registry
from blue_data_ops.plan import DataPipeline, PipelineExecutor

plan = DataPipeline(label="keep the high scores")
source = plan.define_input("records")
step = plan.define_operator("select@2.0.0", attributes={"operand_key": "score", "operand": ">", "operand_val": 5})
sink = plan.define_output("selected")
plan.set_plan_input(source)
plan.set_plan_output(sink)
plan.connect_nodes(source, step)
plan.connect_nodes(step, sink)

document = json.dumps(plan.to_dict())
restored = DataPipeline.from_dict(json.loads(document))
print(restored.get_label())   # keep the high scores

run = PipelineExecutor(active_registry()).execute(restored, [[{"score": 9}]])
print(run.succeeded, run.output_data)   # True [[{'score': 9}]]
```

## Plan from a goal

`PipelinePlanner` turns a goal into a compiled pipeline.
It runs discovery, bounded data-context collection, generation, selection, compilation, and preflight; your generator supplies candidate drafts and the planner owns the rest.

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
planner = PipelinePlanner(registry, RulePlanGenerator([SELECT_THEN_AVERAGE_TEMPLATE]))
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

result = planner.plan(request)
print([step.operator_id for step in result.selected.steps])   # ['select@2.0.0', 'avg@3.0.0']

run = planner.run(request, [[{"total": 120.0}, {"total": 215.0}, {"total": 50.0}]])
print(run.execution.output_data)   # [[{'average_total': 167.5}]]
```

Three entry points do different amounts of work.
`plan(request)` returns a `PlanningResult` with the request copy, the discovery snapshot, the candidates, the selected draft, the compiled pipeline, the preflight result, and any retained data context.
`run(request, input_data)` adds a `PipelineRun`.
`execute(planning, input_data)` runs a copy of a planning result you already have.

A rule template needs exact discovered metadata plus caller-supplied attributes for every step.
`SELECT_THEN_AVERAGE_TEMPLATE` is the filter-then-average rule; `project_then_aggregate_template(name)` builds the projection variant for `"avg"`, `"sum"`, `"min"`, and `"max"`.

```python
from blue_data_ops.operators import active_registry
from blue_data_ops.plan import (
    DiscoveryQuery,
    PipelinePlanner,
    PlanningRequest,
    RulePlanGenerator,
    project_then_aggregate_template,
)

template = project_then_aggregate_template("sum")
print(template.label)   # project-then-sum

planner = PipelinePlanner(active_registry(), RulePlanGenerator([template]))
request = PlanningRequest(
    goal="total the order values",
    discovery_queries=(
        DiscoveryQuery("project", tags=("capability-projection",)),
        DiscoveryQuery("sum", tags=("capability-sum",)),
    ),
    operator_attributes={
        "project": {"kept_keys": ["total"]},
        "sum": {"sum_key": "total", "output_key": "total_value"},
    },
)
run = planner.run(request, [[{"total": 120.0, "region": "east"}, {"total": 215.0, "region": "west"}]])
print(run.execution.output_data)   # [[{'total_value': 335.0}]]
```

Planning raises where operator execution returns.
There is no partial pipeline to hang a record on, so `PlanningError` carries the record instead.

```python
from blue_data_ops.operators import active_registry
from blue_data_ops.plan import (
    DiscoveryQuery,
    PipelinePlanner,
    PlanningError,
    PlanningRequest,
    RulePlanGenerator,
)

planner = PipelinePlanner(active_registry(), RulePlanGenerator())
request = PlanningRequest(
    goal="nothing this generator recognizes",
    discovery_queries=(DiscoveryQuery("join", tags=("capability-join",)),),
)
try:
    planner.plan(request)
except PlanningError as error:
    print(error.record.stage.value)     # SELECTION
    print(error.record.code.value)      # NO_CANDIDATES
    print(error.record.suggestion)      # Adjust discovery or generation so at least one plan is produced.
```

`PlanningError` subclasses `ValueError`.
Stages are `VALIDATION`, `DISCOVERY`, `DATA_CONTEXT`, `GENERATION`, `SELECTION`, `COMPILATION`, and `PREFLIGHT`.
`PlanningRequest` also bounds how many discovery cards, candidates, steps, nodes, and edges a run may produce.

Custom generators must follow two admission boundaries.
The planner compiles only admitted, supported exact ids that its own discovery returned, so a generator cannot introduce an operator the caller filtered out.
Without an allowlist, built-ins are limited to the `active_registry()` selection; an exact allowlist may admit retained v2/v3 built-ins from `versioned_registry()`, and a caller-owned registry with a caller-owned rule may admit caller-created v2 cards.

## Plan with a provider

`OpenAIPlanGenerator` needs the `openai` extra.
It makes one non-streaming Responses call per `generate()` and constructs `openai.OpenAI()` at first use unless you inject a client with `client=`.

```python
from blue_data_ops.operators import active_registry
from blue_data_ops.plan import OpenAIPlanGenerator, PipelinePlanner

registry = active_registry()
generator = OpenAIPlanGenerator(
    "gpt-6-luna",
    registry=registry,
    allowed_operator_ids=["select@2.0.0", "avg@3.0.0"],
)
planner = PipelinePlanner(registry, generator)
print(type(generator).__name__)   # OpenAIPlanGenerator
```

`allowed_operator_ids` is an authorization boundary, not a hint.
The same enriched package registry must have built each card, discovery must have returned it, and the card must not produce a side effect; the decoder checks the same set again.
Raw compatibility cards and caller-created cards are refused.
Attributes you supply are constraints the model cannot drop or overwrite.

Schema disclosure is opt-in.
Set `send_data_context=True` to hand an available `DataContextSnapshot` to the provider; without it, a snapshot reaching `generate()` fails before the SDK import rather than being dropped quietly.
The snapshot carries entity names, descriptions, and declared attribute types, never rows, and its provenance records `raw_rows: 0`.
An `nl2sql` step additionally requires a supplied and disclosed schema snapshot.

Provider failures map to stable codes such as `GENERATOR_TIMEOUT`, `GENERATOR_RATE_LIMITED`, and `GENERATOR_UNAVAILABLE`.
Records never carry a response body, a request payload, a credential, or provider exception text, so the record shape survives an SDK message change.

## Call the LLM-backed operators

Eight operators go through LiteLLM: `nl2llm`, `nl2sql`, `nl2bn`, and the five `semantic_*` operators.
They need the `llm` extra and a provider credential in the environment.
`<your-key>` below is a placeholder; substitute your own key and keep it out of version control.

```bash
export OPENAI_API_KEY=<your-key>
```

Select the model with the `openai.model` call property; the default is `gpt-6-luna`.

```python
from blue_data_ops.operators import active_registry

operator = active_registry().resolve("nl2llm@3.0.0")
output_data, _, meta = operator.run(
    [[]],
    {
        "query": "Return two example products",
        "attrs": [{"name": "name", "type": "string"}, {"name": "price", "type": "float"}],
    },
    {"openai.model": "gpt-4o-mini"},
)
print(output_data if not meta.errors else meta.errors[0].code.value)
```

Without the extra or without the credential, that prints `EXECUTION_FAILED` and `output_data` is `[[]]`.
Nothing raises, so the same branch handles both.

`nl2sql` can run the SQL it writes.
Generation is the default and returns `[[{"sql": "..."}]]`. Supply `source`, `protocol`, `database`, and `collection` for schema lookup. Execution requires a host-configured `ReadOnlySQLExecutor` and a boolean `execute_query=True`; see [LLM settings](llm-settings.md#sql-execution). Caller registry selectors are denied during execution. The fixed SELECT check measures query shape; the bound database connection enforces read-only access.

`nl2llm@3.0.0` may report an estimated USD `cost` in `ExecMeta.traces` after exactly one priced attempt.
A proven local cache hit reports `0.0`.
Retries, failures, unknown prices, and injected clients leave the cost fields out entirely, so treat a missing cost as unknown rather than free.

## ML and vector work

`classify`, `cluster`, and `sklearn_estimator` need the `ml` extra.
`classify` fits on the first input group and predicts on the rest.

```python
from blue_data_ops.operators import active_registry

classifier = active_registry().resolve("classify@3.0.0")
training = [
    {"label": "low", "vector": [0.0, 0.0]},
    {"label": "low", "vector": [0.0, 1.0]},
    {"label": "high", "vector": [10.0, 10.0]},
    {"label": "high", "vector": [10.0, 11.0]},
]
samples = [{"vector": [0.0, 0.5]}, {"vector": [10.0, 10.5]}]
output_data, _, meta = classifier.run(
    [training, samples],
    {"vector_key": "vector", "label_key": "label", "random_state": 42},
)
print([record["predicted_label"] for record in output_data[1]])   # ['low', 'high']
```

`cluster` assigns indices with KMeans, DBSCAN, or a Gaussian mixture.
Pick the algorithm in the properties and the shape in the attributes.

```python
from blue_data_ops.operators import active_registry

operator = active_registry().resolve("cluster@3.0.0")
records = [
    {"id": 1, "vector": [0.0, 0.0]},
    {"id": 2, "vector": [0.1, 0.1]},
    {"id": 3, "vector": [9.0, 9.0]},
    {"id": 4, "vector": [9.1, 9.2]},
]
output_data, _, meta = operator.run(
    [records],
    {"vector_key": "vector", "n_cluster": 2},
    {"algorithm": "kmeans"},
)
print([record["cluster_index"] for record in output_data[0]])   # [0, 0, 1, 1]
```

`sklearn_estimator` accepts any case-insensitive class name `sklearn.utils.all_estimators()` returns.
Name it in `properties.algorithm`, point `attributes.vector_key` at the feature vector, and add `attributes.label_key` for a classifier or a regressor.
The fitted model is not persisted.

```python
from blue_data_ops.operators import active_registry

operator = active_registry().resolve("sklearn_estimator@2.0.0")
training = [
    {"grade": "pass", "vector": [0.0, 0.0]},
    {"grade": "pass", "vector": [0.0, 1.0]},
    {"grade": "fail", "vector": [9.0, 9.0]},
    {"grade": "fail", "vector": [9.1, 8.0]},
]
output_data, _, meta = operator.run(
    [training],
    {"vector_key": "vector", "label_key": "grade"},
    {"algorithm": "DecisionTreeClassifier"},
)
print(sorted(output_data[0][0]))   # ['grade', 'prediction', 'vector']
```

The three vector operators need the `vector` extra when text has to be embedded.
Scoring embeddings you already hold needs neither a model nor a download.

```python
from blue_data_ops.operators import active_registry

operator = active_registry().resolve("vector_similarity@3.0.0")
left = [{"id": "query", "embedding": [1.0, 0.0, 0.0]}]
right = [{"id": "candidate", "embedding": [0.9, 0.1, 0.0]}]
output_data, _, meta = operator.run([left, right], {})
print(round(output_data[0][0]["similarity.score"], 4))   # 0.9939
print(sorted(output_data[0][0]))   # ['id', 'left_id', 'right_id', 'similarity.score']
```

## Migrate from 2.x

Core 3.0 removes four plan-producing operator names, all eight of their v1/v2 exact ids, and the refinement API.
[`lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md) is the source of truth for the whole boundary; this is the part you meet first.

The retained history is still resolvable, and the retired ids are not.

```python
from blue_data_ops.operators import ResolveError, versioned_registry

history = versioned_registry()
print(history.resolve("select@1.0.0").operator_id)   # select@1.0.0
print(history.resolve("avg@2.0.0").operator_id)      # avg@2.0.0
try:
    history.resolve("plan_discover@2.0.0")
except ResolveError as error:
    print(error)   # no operator registered as 'plan_discover@2.0.0'
```

A stored pipeline that names a retired id still parses as data, then fails preflight.
The failure is loud and early rather than halfway through a run.

```python
import json

from blue_data_ops.operators import active_registry
from blue_data_ops.plan import DataPipeline, PipelineError, PipelineExecutor

stored = DataPipeline(label="saved 2.x plan")
source = stored.define_input("records")
step = stored.define_operator("query_breakdown@2.0.0", attributes={})
sink = stored.define_output("out")
stored.set_plan_input(source)
stored.set_plan_output(sink)
stored.connect_nodes(source, step)
stored.connect_nodes(step, sink)

reloaded = DataPipeline.from_dict(json.loads(json.dumps(stored.to_dict())))
print(reloaded.get_label())   # saved 2.x plan
try:
    PipelineExecutor(active_registry()).preflight(reloaded)
except PipelineError as error:
    print("query_breakdown@2.0.0" in str(error))   # True
```

The supported migration covers two cases.
Replace a `DeclarativeOperator` used as an executable leaf with an ordinary `Operator` subclass.
For one fixed graph, build and execute a materialized `DataPipeline` directly, or implement `PlanGenerator.generate()` to return `Sequence[PlanDraft]` for `PipelinePlanner`.

This is not drop-in.
Core 3.0 does not refine an operator automatically and does not expand old declarative plan definitions.
The supported graph successor covers one fixed linear expansion; it does not preserve dynamic alternatives, malformed-plan normalization, raw v1 refiner behavior, or a general `DeclarativeOperator` hierarchy.
Code that needs those semantics belongs on a compatible core 2.x and MCP 0.x pair, such as core 2.10.0 with MCP 0.12.0.

Use `active_registry()` for new work, and keep `versioned_registry()` only where the code deliberately resolves retained 1.x or 2.x behavior.

## Run the tests

With the `dev` extra installed, from `lib/`:

```bash
python -m pytest
```

The suite substitutes stubs for `litellm` and `sentence-transformers`, so the default run needs no download and no credential.

## Next steps

- [features.md](features.md) — the same capabilities as a survey, one example each
- [api-reference.md](api-reference.md) — the exact public surface
- [architecture.md](architecture.md) — how the modules fit together
- [extending.md](extending.md) — writing your own operator, registry, generator, or embedder
- [../examples/README.md](../examples/README.md) — whole programs you can run as they are
- [mcp.md](mcp.md) — the same operators as MCP tools

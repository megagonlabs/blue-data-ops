# Features

What `blue-data-ops` does, one section per capability, with a short runnable example for each.
The generated [operator reference](../lib/OPERATORS.md) is the source of truth for per-operator metadata; this page shows the shape of each capability rather than restating 33 operator tables.

## An operator catalog pinned by exact version

Thirty-three logical operators, each addressed as `name@<MAJOR.MINOR.PATCH>`.
Twelve are active at `@2.0.0` and the other twenty-one at `@3.0.0`, so the version you resolve is part of the contract rather than a detail of the release.

| Category | Active logical operators |
|---|---|
| Filter and shape | `select`, `project`, `delete`, `insert` |
| Join and set | `join`, `union`, `intersect` |
| Aggregate | `argmax`, `argmin`, `max`, `min`, `avg`, `sum` |
| Text | `normalize_text`, `segment_text` |
| ML (`ml` extra) | `classify`, `cluster`, `sklearn_estimator` |
| Vector (`vector` extra) | `vector_embed`, `vector_search`, `vector_similarity` |
| LLM (`llm` extra) | `nl2llm`, `nl2sql`, `nl2bn`, `semantic_extract`, `semantic_filter`, `semantic_join`, `semantic_project`, `semantic_transform` |
| Registry-backed | `create_database`, `create_table`, `insert_table`, `data_discover` |

```python
from blue_data_ops.operators import active_registry

registry = active_registry()
print(len(registry.list_cards()))                        # 33
print(registry.resolve("project@3.0.0").operator_id)     # project@3.0.0
print(registry.find_latest("select").operator_id)        # select@2.0.0
```

`resolve()` takes an exact id and nothing else.
There is no latest-version fallback, so a pinned plan keeps resolving to the same implementation.

## Structured execution results

`run()` is the canonical boundary.
It materializes declared defaults, validates, normalizes empty output to `[[]]`, and returns the output bundle, a fresh output-attributes mapping, and an `ExecMeta`.

```python
from blue_data_ops.operators import active_registry

operator = active_registry().resolve("avg@3.0.0")
output_data, output_attributes, meta = operator.run([[{"total": 120.0}, {"total": 215.0}]], {"avg_key": "total"})
print(output_data)         # [[{'avg': 167.5}]]
print(output_attributes)   # {'num_values_used': 2}
print(meta.is_empty, meta.errors)   # False []
```

Input and output are both `list[list[dict]]` — a list of record groups.
A successful empty result is `[[]]` with `is_empty=True` and no errors, which is a different thing from a failure.

## Errors returned as data

Invalid input and execution failures come back inside `ExecMeta.errors` rather than as exceptions.
Each record carries a category, a stable code, the exact operator id, the stage it failed at, a message, a retryability flag, and sometimes a suggestion.

```python
from blue_data_ops.operators import active_registry

operator = active_registry().resolve("select@2.0.0")
output_data, _, meta = operator.run(
    [[{"name": "a", "score": 3}]],
    {"operand_key": "score", "operand": "??", "operand_val": 5},
)
print(output_data)                  # [[]]
record = meta.errors[0]
print(record.category.value, record.code.value, record.stage.value)   # RECOVERABLE INVALID_INPUT VALIDATE
print(record.suggestion)            # supply a supported operand and a nonnegative eps value
```

Categories are `RECOVERABLE`, `FAILED`, and `TIMEOUT`.
Stages cover defaults, validation, execution, and normalization.
Resolution, pipeline preflight, and planning still raise, because those have no partial result to carry a record; [guide.md](guide.md) lists which boundary does which.

## Raw Blue-compatible call shapes

The v1 call shapes are still there beside `run()`.
`apply()` calls the transform directly, `invoke()` runs boolean validation first and returns `None` when it fails, and neither converts an exception into metadata.

```python
from blue_data_ops import SelectOperator

operator = SelectOperator()
data = [[{"name": "a", "score": 3}, {"name": "b", "score": 9}]]
attributes = {"operand_key": "score", "operand": ">", "operand_val": 5}

print(operator.apply(data, attributes))     # [[{'name': 'b', 'score': 9}]]
print(operator.invoke(data, attributes))    # [[{'name': 'b', 'score': 9}]]
print(operator.validate(data, attributes, {}))   # True
print(operator.invoke(data, {**attributes, "operand": "??"}))   # None
```

Operators also keep the Blue `Tool`/`Operator` metadata surface, including `get_signature()` and the parameter accessors.

## Attribute schemas you can read at runtime

Every operator declares its attributes, and the declaration is queryable.
A caller building a form or a prompt does not need to hard-code the parameter list.

```python
from blue_data_ops.operators import active_registry

operator = active_registry().resolve("avg@3.0.0")
print(sorted(operator.attributes))                   # ['avg_key', 'output_key']
print(operator.is_required("avg_key"))               # True
print(operator.default_of("output_key"))             # avg
print(operator.attributes["avg_key"].description)    # The key to average the values for
```

`explain()` describes a finished transform, given its output, its input, and the attributes it ran with.

## A wrapper deadline

Set `execution.timeout_seconds` in the call properties to bound one `run()`.
The wrapper never retries, and a breach is reported as a `TIMEOUT` record rather than an exception.

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

The legacy `properties["timeout"]` field is still observable, but it does not set the deadline.

## Execution measurements

The 21 operators active at `@3.0.0` may add shallow shape counts and a monotonic elapsed time to `ExecMeta.traces`.
`input_shape` is captured before validation; `output_shape` appears only after a successful normalization, so its absence tells you the call did not get that far.

```python
from blue_data_ops.operators import active_registry

operator = active_registry().resolve("avg@3.0.0")
_, _, meta = operator.run([[{"total": 120.0}, {"total": 215.0}]], {"avg_key": "total"})
print(meta.traces["input_shape"])    # {'groups': 1, 'rows_per_group': [2]}
print(meta.traces["output_shape"])   # {'groups': 1, 'rows_per_group': [1]}
print(sorted(meta.traces))           # ['elapsed_ms', 'input_shape', 'output_shape']
```

A missing measurement means unavailable, not zero.
The `nl2llm@3.0.0` built-in client can also report an estimated USD `cost` after exactly one priced provider attempt.

## Three registry views

The same catalog is exposed three ways, because discovery, execution, and migration want different things from it.

| Factory | Cards | Use it for |
|---|---|---|
| `active_registry()` | 33 | ordinary 3.0 discovery and execution |
| `default_registry()` | 33 | the raw v1-compatible view, with per-name version overrides |
| `versioned_registry()` | 87 | retained history, when migration code must resolve a 1.x or 2.x card |

```python
from blue_data_ops.operators import active_registry, default_registry, versioned_registry

print(len(active_registry().list_cards()))       # 33
print(len(default_registry().list_cards()))      # 33
print(len(versioned_registry().list_cards()))    # 87
print(versioned_registry().resolve("avg@1.0.0").operator_id)   # avg@1.0.0
```

Raw cards carry no tags and no invocation guidance, and the planner refuses them as planning authority.

## Tag discovery

`find()` scores the query text and ANDs an optional exact tag filter.
Built-in cards use five required axes and one optional one, all flat labels rather than a hierarchy.

| Axis | What it tells the caller | Built-in cardinality |
|---|---|---|
| `domain-*` | primary subject area, not the output type | exactly one |
| `flow-*` | valid role in a pipeline | one or more |
| `accepts-*` | kind of upstream input consumed | one or more |
| `produces-*` | result kind or externally visible effect | one or more |
| `capability-*` | operation family or specific action | one or more |
| `requires-*` | unconditional operator-specific runtime requirement | zero or more |

```python
from blue_data_ops.operators import active_registry

catalog = active_registry()
print([card.operator_id for card in catalog.find("", tags=["domain-vector", "flow-transform"])])
print([card.operator_id for card in catalog.find("filter", tags=["domain-relational"])])
print(len(catalog.find("")))   # 0
```

A blank query with tags does tag-only discovery.
A blank query with no tags returns nothing.
There is no OR syntax and no negative tags; a well-formed tag that no card carries matches nothing.
[`lib/OPERATORS.md`](../lib/OPERATORS.md) lists every value in use and each card's tags.

## Embedding discovery

`OperatorEmbeddingIndex` ranks the same cards by cosine similarity against a query.
You supply the embedder and its `space_id`; the package neither chooses nor installs an embedding model.

```python
from blue_data_ops.operators import OperatorEmbeddingIndex, active_registry


class KeywordEmbedder:
    space_id = "features-keywords-v1"

    def __call__(self, texts: tuple[str, ...]) -> list[list[float]]:
        terms = ("filter", "average", "join")
        return [[1.0, *(float(term in text.casefold()) for term in terms)] for text in texts]


catalog = active_registry()
index = OperatorEmbeddingIndex.build(catalog, KeywordEmbedder())
print([card.operator_id for card in index.find("filter rows", tags=["produces-data"])][:3])
```

`build()` sends each card's name, guidance, description, and ordered tags to the embedder in one batch.
`find()` applies no threshold and no limit, so the caller truncates.

## Operator resource packages

`blue_data_ops.operator_skills` ships 54 exact-version resource packages: 33 retained at `@2.0.0` and 21 outcome packages at `@3.0.0`.
Every active exact id has one.
Loading a package reads text; it does not invoke the operator or feed anything to a planner or a provider.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import active_registry

registry = active_registry()
loader = OperatorSkillLoader(registry)

print(loader.describe("nl2sql@3.0.0").declared_levels)   # (2, 3)
skill = loader.load("nl2sql@3.0.0", level=3)
print(skill.card.operator_id)                            # nl2sql@3.0.0
print(skill.io.attributes["question"].required)          # True
```

Level 2 combines the card and live attribute schema with the operator guide; level 3 adds worked examples.
No package in 3.0 carries level 4, so asking for it raises `OperatorSkillLoadError` with code `NOT_AVAILABLE`.

## Registry-backed database operations

Six operators use a `blue-data` registry.
`create_database`, `create_table`, `insert_table`, and `data_discover` create, modify, or read registered data; `nl2bn` and `nl2sql` use the registry while generating and, when enabled, executing queries.
Pass the seam in the call properties.

```python
from blue_data.registry.data_registry import DataRegistry
from blue_data.source.json.memory_json_source import MemoryJSONSource
from blue_data_ops import resolve_registry

seam = resolve_registry({"data_registry": DataRegistry(store=MemoryJSONSource(), rebuild=False)})
print(type(seam).__name__)   # RegistrySeam
print(resolve_registry({}))  # None
```

`resolve_registry()` takes a `RegistrySeam` as given and wraps a raw `blue_data` `DataRegistry`.
Without an injection, pass `platform.name` and `data_registry.name` and the default provider builds and caches an in-memory registry for that pair.
[guide.md](guide.md) walks the whole create-table, insert, read-back, discover sequence against a throwaway SQLite database.

## Portable pipelines

`DataPipeline` is a serializable graph record, so a plan can be stored, shipped, and replayed.
`PipelineExecutor` preflights exact ids, structure, attributes, and reachability, then runs nodes in stable topological order and stops at the first structured operator failure.

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
run = PipelineExecutor(active_registry()).execute(restored, [[{"score": 9}]])
print(run.succeeded, run.output_data)   # True [[{'score': 9}]]
```

Operator entities store only pinned ids, never bare names, deployment routes, or host addresses, so a serialized plan stays deterministic and deployment-neutral.

## Goal-driven planning

`PipelinePlanner` takes a goal and runs discovery, bounded data-context collection, generation, selection, compilation, and preflight.
A plan generator supplies candidate drafts; the planner owns every other stage.
One template constant and one template factory ship with it, covering five linear shapes between them.

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
print([step.operator_id for step in run.planning.selected.steps])   # ['project@3.0.0', 'sum@2.0.0']
print(run.execution.output_data)                                   # [[{'total_value': 335.0}]]
```

`SELECT_THEN_AVERAGE_TEMPLATE` covers filter-then-average, and `project_then_aggregate_template(name)` builds the projection variant for `"avg"`, `"sum"`, `"min"`, and `"max"`.
The planner compiles only admitted, supported ids that its own discovery returned, so a generator cannot smuggle in an operator the caller filtered out.

## Provider-backed plan generation

`OpenAIPlanGenerator` makes one non-streaming Responses call per `generate()` and needs the `openai` extra.
`allowed_operator_ids` is an authorization boundary rather than a hint: the decoder checks the same set the constructor was given.

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
print(type(planner).__name__)   # PipelinePlanner
```

Caller-supplied attributes are constraints the model cannot drop or overwrite.
Each request uses `store=False`, disables SDK retries, and defaults to a 60-second timeout, 4096 output tokens, and one candidate.
Provider failures map to stable codes such as `GENERATOR_TIMEOUT` and `GENERATOR_RATE_LIMITED`, and the records exclude response bodies, request payloads, credentials, and provider exception text.

## Schema context without rows

A generator that needs to know the shape of the data gets a `DataContextSnapshot`, never records.
`RegistryDataContextProvider` reads source properties, entity names, descriptions, and declared attribute types, and records `raw_rows: 0` in its provenance.

```python
from blue_data_ops.plan import DataScope

scope = DataScope(source="demo_sqlite", database="shop", collection="public")
print(scope.source, scope.database, scope.collection)   # demo_sqlite shop public
```

Its default limits are 32 entities, 64 attributes per entity, 512 total attributes, 512 description characters, and 131072 serialized bytes.
Disclosure to a provider is opt-in: without `send_data_context=True`, a snapshot reaching `generate()` fails before the SDK import rather than being dropped in silence.

## LLM-backed operators

Eight operators send requests through LiteLLM: `nl2llm`, `nl2sql`, `nl2bn`, and the five `semantic_*` operators.
Configure the model through call properties; the default is `openai.model: gpt-6-luna`.
A missing credential or a missing extra is contained, not raised.

```python
from blue_data_ops.operators import active_registry

operator = active_registry().resolve("nl2llm@3.0.0")
output_data, _, meta = operator.run(
    [[]],
    {"query": "Return two example products", "attrs": [{"name": "name", "type": "string"}]},
    {"openai.model": "gpt-4o-mini"},
)
print(output_data if not meta.errors else meta.errors[0].code.value)
```

With `OPENAI_API_KEY` set and the `llm` extra installed, that prints the generated records.
Without either, it prints `EXECUTION_FAILED` and `output_data` is `[[]]`.
`nl2sql` generates SQL by default. Execution requires an explicitly host-bound read-only executor and `execute_query=True`; stock CLI/MCP operators cannot acquire one from request properties. See [SQL execution](llm-settings.md#sql-execution) for configuration and limits.

## ML operators

`classify` fits a model on the first input group and predicts on the rest.
`cluster` assigns cluster indices with KMeans, DBSCAN, or a Gaussian mixture.
`sklearn_estimator` accepts any case-insensitive class name that `sklearn.utils.all_estimators()` returns, trains it in memory, and writes predictions onto each record without persisting the model.

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

All three need the `ml` extra.

## Vector operators

`vector_embed` turns text into embeddings, `vector_search` ranks records against a query, and `vector_similarity` scores two groups against each other.
Similarity over embeddings you already hold needs no model and no download.

```python
from blue_data_ops.operators import active_registry

operator = active_registry().resolve("vector_similarity@3.0.0")
left = [{"id": "query", "embedding": [1.0, 0.0, 0.0]}]
right = [{"id": "candidate", "embedding": [0.9, 0.1, 0.0]}]
output_data, _, meta = operator.run([left, right], {})
print(round(output_data[0][0]["similarity.score"], 4))   # 0.9939
```

Field names are required only when text has to be embedded first.
The `vector` extra covers all three.

## Blue helper compatibility

`blue_data_ops.utils` carries the Blue helpers the operator surface depends on, under the same names and with the same behavior, so porting code does not mean rewriting its type and template handling.

```python
from blue_data_ops.utils import safe_substitute, string_to_python_type, validate_parameter_type

print(validate_parameter_type("3", "int"))          # True
print(safe_substitute("$greeting there", greeting="hi"))   # hi there
print(string_to_python_type("list[str]"))           # typing.List[str]
```

Helpers outside that surface are deliberately absent.
[`lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md) lists what was left out and why, including the service-client and similarity differences.

## MCP server

`blue-data-ops-mcp` exposes the same 33 operators as MCP tools over the structured execution contract, with no refinement companions.
Each tool is named `ops_` plus its logical operator name — `ops_select`, `ops_avg` — and each tool's `_meta` carries its exact operator id, unprefixed.

```python
import asyncio

from blue_data_ops_mcp import create_server
from mcp.shared.memory import create_connected_server_and_client_session


async def main() -> None:
    server = create_server(operator_ids=("select@2.0.0",))
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        listing = await client.list_tools()
        print([tool.name for tool in listing.tools])   # ['ops_select']


asyncio.run(main())
```

`create_server()` returns a configured server you can embed; the installed `blue-data-ops-mcp` command starts streamable HTTP on `127.0.0.1:8010/mcp`.
See [mcp.md](mcp.md) for the full tool shape and the client configuration.

## Command line

`blue-data-ops-cli` installs `blue-ops`, which reaches the same operators from a shell: 24 commands over `profile`, `catalog`, `operator`, `pipeline` and `metadata`, with `operator resource` under `operator`.

```bash
blue-ops operator run select@2.0.0 --input-file examples/cli/orders.json \
  --attribute operand_key=total --attribute 'operand=>' --attribute operand_val=100
```

A record bundle arrives as a file or on standard input, never as an argument, and `--format table|json|nl` decides how the result is rendered.
Settings resolve through four tiers — command option, environment variable, profile, built-in default — and a stored pipeline runs with `blue-ops pipeline run`.
See [cli.md](cli.md) for the command tree, the configuration parameters, and the ten exit codes.

## Interfaces

The repository provides the Python library, MCP adapter, and `blue-ops` command.

HTTP requires the shared API key by default on both streamable HTTP and SSE.
See the [HTTP bind, authentication and mounted lifespan contract](mcp.md#http-authentication-and-bind-settings)
for environment overrides, the explicit no-key opt-out and the SDK Host/Origin limits.

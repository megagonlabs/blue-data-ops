# blue-data-ops — Scenarios

These are the ways the library is used in practice, each grounded in a runnable script under [`../examples/README.md`](../examples/README.md) or in the package README.
Every operator reference is a pinned ID, because that is what callers actually write.

---

## Scenario 1: Shaping and Aggregating Records In Process

The smallest useful case, and the one most callers start from.
A caller already holds records — rows pulled from a service, a parsed file, a page of API results — and wants them filtered, projected, combined, or reduced without standing anything up.
It resolves the operators it needs from the active registry and calls `run()` on each, threading one operator's output bundle into the next as ordinary Python values.

Nothing is registered, nothing is configured, and no external service is contacted.
The unit of data throughout is `list[list[dict]]`: a list of record groups, where the group boundary is what multi-input operators like `join` and `union` read.

**Example:**

```python
from blue_data_ops.operators import active_registry

registry = active_registry()
select = registry.resolve("select@2.0.0")
average = registry.resolve("avg@3.0.0")

orders = [
    [
        {"id": 1, "region": "east", "total": 42.0},
        {"id": 2, "region": "west", "total": 125.0},
        {"id": 3, "region": "east", "total": 215.0},
    ]
]

large, _, select_meta = select.run(
    orders,
    {"operand_key": "total", "operand": ">", "operand_val": 100},
)
mean, _, average_meta = average.run(
    large,
    {"avg_key": "total", "output_key": "average_total"},
)

assert not select_meta.errors and not average_meta.errors
assert mean == [[{"average_total": 170.0}]]
```

`examples/quickstart/core_quickstart.py` runs the same shape across `select`, `avg`, `normalize_text`, and `union`.

---

## Scenario 2: Reading and Writing a Registered Data Source

A caller wants operators to use registered data rather than only in-memory records.
Six operators use a `blue-data` registry: `create_database`, `create_table`, `insert_table`, `data_discover`, `nl2bn`, and `nl2sql`.
The first four create, modify, or read registered data; `nl2bn` and `nl2sql` use the registry while generating and, when enabled, executing queries.
The caller registers its source with `blue-data`, wraps the registry in a `RegistrySeam`, and passes the seam through call properties under `data_registry`.

The seam is the only place the package imports `blue-data`, so the operator itself never sees the underlying registry's argument order or result shapes.
A caller that would rather not build a registry can pass `platform.name` and `data_registry.name` instead and let the default provider construct and cache an in-memory one.

**Example:**

```python
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from blue_data.registry.data_registry import DataRegistry
from blue_data.source.json.memory_json_source import MemoryJSONSource
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource

from blue_data_ops import RegistrySeam
from blue_data_ops.operators import active_registry

with TemporaryDirectory() as directory:
    with sqlite3.connect(Path(directory) / "shop.db") as connection:
        connection.execute(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, region TEXT, total REAL)"
        )
        connection.executemany(
            "INSERT INTO orders VALUES (?, ?, ?)",
            [(1, "east", 42.0), (2, "west", 125.0), (3, "east", 215.0)],
        )

    source = SQLiteDBSource(
        "demo_sqlite",
        properties={"connection": {"database_directory": directory}},
    )
    registry = DataRegistry(store=MemoryJSONSource(), rebuild=False)
    registry.register_source(source)
    registry.sync_source(source.name, recursive=True)
    seam = RegistrySeam(registry)

    insert_table = active_registry().resolve("insert_table@3.0.0")
    rows, attributes, meta = insert_table.run(
        [[{"id": 4, "region": "north", "total": 310.0}]],
        {"source": "demo_sqlite", "database": "shop", "table": "orders"},
        {"data_registry": seam},
    )

    assert not meta.errors
    assert attributes == {"num_rows_insert": 1}
```

`insert_table@3.0.0` passes the inserted records through unchanged and reports the row count it observed as an output attribute.
`examples/quickstart/sqlite_quickstart.py` builds a ten-row database and adds `create_database` and `data_discover` on top of the same seam.

---

## Scenario 3: Fitting a Model Over Record Vectors

A caller has feature vectors on its records and wants a label, a cluster assignment, or a transformed vector written back onto each one.
`classify` and `cluster` cover the fixed algorithm choices; `sklearn_estimator` accepts any case-insensitive class name that `sklearn.utils.all_estimators()` returns and dispatches on whether that estimator is a classifier, regressor, clusterer, or transformer.

`classify` and `sklearn_estimator` fit from the first input group, then write an output key onto every record in every group, so the training group comes back annotated too.
`cluster` reads the first group and returns that one group.
The fitted model is not persisted — a caller that needs a stable model across calls owns that itself.
These operators need the `ml` extra, and NumPy and scikit-learn are imported inside the executing method rather than at package import.

**Example:**

```python
from blue_data_ops.operators import active_registry

registry = active_registry()
training = [
    {"label": "low", "vector": [0.0, 0.0]},
    {"label": "low", "vector": [0.0, 1.0]},
    {"label": "high", "vector": [10.0, 10.0]},
    {"label": "high", "vector": [10.0, 11.0]},
]
samples = [{"vector": [0.0, 0.5]}, {"vector": [10.0, 10.5]}]

labelled, _, classify_meta = registry.resolve("classify@3.0.0").run(
    [training, samples],
    {"vector_key": "vector", "label_key": "label", "random_state": 42},
)
predicted, _, estimator_meta = registry.resolve("sklearn_estimator@2.0.0").run(
    [training, samples],
    {"vector_key": "vector", "label_key": "label"},
    {"algorithm": "RandomForestClassifier"},
)

assert not classify_meta.errors and not estimator_meta.errors
assert [record["predicted_label"] for record in labelled[1]] == ["low", "high"]
assert [str(record["prediction"]) for record in predicted[1]] == ["low", "high"]
```

`classify` writes `predicted_label`; `sklearn_estimator` writes `prediction`.
`examples/quickstart/ml_quickstart.py` is the decision-tree case on its own.

---

## Scenario 4: Ranking by Similarity Without Downloading a Model

A caller that already has embeddings — from its own pipeline, a vector store, or a service it controls — wants similarity scoring and nearest-neighbour ranking without this package choosing an embedding model for it.
`vector_similarity` compares two record lists and accepts an omitted `fields` attribute when both sides already carry embeddings.
`vector_search` ranks candidates against a text or vector query, and `vector_embed` is there for the case where text does still need embedding.

Only the embedding path pulls `sentence-transformers` from the `vector` extra.
Comparing supplied vectors needs NumPy and nothing more.

**Example:**

```python
from blue_data_ops.operators import active_registry

similarity = active_registry().resolve("vector_similarity@3.0.0")
left = [{"id": "left", "embedding": [1.0, 0.0]}]
right = [{"id": "right", "embedding": [1.0, 0.0]}]

scored, _, meta = similarity.run([left, right], {})

assert not meta.errors
assert scored[0][0]["similarity.score"] == 1.0
assert scored[0][0]["id"] == "left_right"
```

`examples/quickstart/vector_quickstart.py` is this call, with no model download on any path.

---

## Scenario 5: Turning a Question Into Structured Records

A caller has a natural-language request and wants records back in a shape it declared.
`nl2llm` takes a query and an `attrs` list describing the fields it wants, sends the request through LiteLLM, and returns the decoded JSON as a record group.
The model is chosen through call properties; the default is `openai.model: gpt-4o`.

The LLM extra is loaded lazily like the others, so a caller without `[llm]` installed gets an `EXECUTION_FAILED` record carrying an install suggestion rather than an import error.

**Example:**

```python
import os

from blue_data_ops.operators import active_registry

if "OPENAI_API_KEY" not in os.environ:
    raise SystemExit("Set OPENAI_API_KEY before running this live-provider example.")

operator = active_registry().resolve("nl2llm@3.0.0")
output, _, meta = operator.run(
    [[]],
    {
        "query": "Return two example products",
        "attrs": [
            {"name": "name", "type": "string"},
            {"name": "price", "type": "float"},
        ],
    },
    {"openai.model": "gpt-4o-mini"},
)

if meta.errors:
    raise RuntimeError(meta.errors[0].message)
print(output)
```

The empty `[[]]` bundle is how a caller invokes an operator tagged `accepts-none`: the argument is still required, it just carries no records.
`examples/feature-demos/nl2llm.py` is this script.

---

## Scenario 6: Generating SQL Against a Registered Schema

A caller wants a question answered from a database it has registered, without writing the query.
`nl2sql` reads the collection's schema through the seam, generates SQL, and optionally executes it.
Execution is opt-in through `execute_query`, and `validate_query_prefixes` gates which statement kinds are allowed to run.

The prefix check is a case-insensitive string comparison, not a SQL parser or a sandbox.
Permissions on the connection and review of the generated query stay with the caller.

**Example:**

```python
import os

from blue_data_ops.operators import active_registry

if "OPENAI_API_KEY" not in os.environ:
    raise SystemExit("Set OPENAI_API_KEY before running this live-provider example.")

# `seam` is the RegistrySeam built in Scenario 2, over the same `shop` database.
operator = active_registry().resolve("nl2sql@3.0.0")
output, _, meta = operator.run(
    [[]],
    {
        "question": "Which region has the highest total order value?",
        "source": "demo_sqlite",
        "protocol": "sqlite",
        "database": "shop",
        "collection": "public",
    },
    {
        "data_registry": seam,
        "execute_query": False,
        "validate_query_prefixes": ["SELECT"],
        "openai.model": "gpt-4o-mini",
    },
)

if meta.errors:
    raise RuntimeError(meta.errors[0].message)
print(output)
```

`seam` here is the `RegistrySeam` built in Scenario 2.
`examples/feature-demos/nl2sql_sqlite.py` builds the schema, defaults to `execute_query=False`, and takes `--execute` to opt in.

---

## Scenario 7: Filtering and Reshaping Records by Meaning

A caller has records whose interesting content is prose, and a condition it can only state in words.
The five `semantic_*` operators cover that: `semantic_filter` keeps records matching a described condition, `semantic_extract` pulls entities out of text fields, `semantic_project` selects and renames from a described projection, `semantic_join` matches two datasets under a described predicate, and `semantic_transform` derives described output fields.

These read like their relational counterparts and slot into the same pipelines.
Their cost profile is different, since each one sends the records it is judging to a provider.

**Example:**

```python
import os

from blue_data_ops.operators import active_registry

if "OPENAI_API_KEY" not in os.environ:
    raise SystemExit("Set OPENAI_API_KEY before running this live-provider example.")

operator = active_registry().resolve("semantic_filter@3.0.0")
output, _, meta = operator.run(
    [
        [
            {"name": "chair", "description": "solid oak dining chair"},
            {"name": "lamp", "description": "small metal desk lamp"},
        ]
    ],
    {"filter_conditions": {"description": "made mostly from wood"}},
    {"openai.model": "gpt-4o-mini"},
)

if meta.errors:
    raise RuntimeError(meta.errors[0].message)
print(output)
```

`examples/feature-demos/semantic_filter.py` is this script.

---

## Scenario 8: Running a Fixed Graph and Reading Per-Node Outcomes

A caller has settled on a sequence of operators and wants it stored, shipped, replayed, and observed as one unit.
It builds a `DataPipeline`, wires the nodes, and hands the graph to a `PipelineExecutor` holding the registry the IDs must resolve against.
`preflight()` validates the graph and resolves every pinned ID without running anything; `execute()` then runs the nodes in topological order and stops at the first structured operator failure.

The returned `PipelineRun` carries the final output plus one `NodeRun` per completed operator node, each with that node's own output, output attributes, and execution metadata.
This is the case where the difference between a raw `@2.0.0` card and an outcome `@3.0.0` card becomes visible: the outcome operators attach `input_shape`, `output_shape`, and `elapsed_ms` to their traces, and the raw ones leave traces empty.

**Example:**

```python
from blue_data_ops.operators import active_registry
from blue_data_ops.plan import DataPipeline, PipelineExecutor

plan = DataPipeline(label="average large orders")
source = plan.define_input("orders")
large = plan.define_operator(
    "select@2.0.0",
    attributes={"operand_key": "total", "operand": ">", "operand_val": 100},
)
mean = plan.define_operator(
    "avg@3.0.0",
    attributes={"avg_key": "total", "output_key": "average_total"},
)
answer = plan.define_output("average")
plan.set_plan_input(source)
plan.set_plan_output(answer)
plan.connect_nodes(source, large)
plan.connect_nodes(large, mean)
plan.connect_nodes(mean, answer)

executor = PipelineExecutor(active_registry())
assert executor.preflight(plan).operator_ids == ("select@2.0.0", "avg@3.0.0")

run = executor.execute(
    DataPipeline.from_dict(plan.to_dict()),
    [[{"id": 1, "total": 42.0}, {"id": 2, "total": 125.0}, {"id": 3, "total": 215.0}]],
)

assert run.succeeded and run.failed_node_id is None
assert run.output_data == [[{"average_total": 170.0}]]
assert run.node_runs[1].output_attributes == {"num_values_used": 2}
assert set(run.node_runs[1].exec_meta.traces) == {"input_shape", "output_shape", "elapsed_ms"}
assert run.node_runs[0].exec_meta.traces == {}
```

Execution mutates node values and statuses on the plan it is given, which is why the example round-trips through `from_dict(plan.to_dict())` and keeps the original record clean.
`examples/feature-demos/operator_outcomes.py` extends this to the successful-empty and invalid-input cases and shows that the rejected run writes nothing to the database.

---

## Scenario 9: Compiling a Pipeline From a Stated Goal

A caller knows what it wants in words and which attributes each step needs, but would rather not hard-code the operator IDs.
`PipelinePlanner` takes a `PlanningRequest` carrying the goal, the discovery queries, and the per-operator attributes, then runs the stages in order: discovery, data-context collection, generation, selection, compilation, and preflight.
With a `RulePlanGenerator`, generation is deterministic and offline — the shipped templates check the discovered metadata against what they expect and refuse to build if it has drifted.

Discovery is allowed to return more than the plan uses.
Compilation is what narrows it: a step whose operator was not discovered, not allowed, or not admitted fails there rather than at execution.

**Example:**

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

result = planner.run(request, [[{"total": 120.0}, {"total": 215.0}, {"total": 50.0}]])

assert result.execution.output_data == [[{"average_total": 167.5}]]
assert [step.operator_id for step in result.planning.selected.steps] == [
    "select@2.0.0",
    "avg@3.0.0",
]
assert result.planning.discovery.operator_ids == (
    "semantic_filter@3.0.0",
    "select@2.0.0",
    "avg@3.0.0",
)
```

`semantic_filter@3.0.0` appears in the snapshot because it matches the word "filter" and carries `capability-filter`.
It never reaches the compiled pipeline, because the template asks discovery for exactly one `select` and one `avg`.

---

## Scenario 10: Choosing an Operator by Similarity Instead of Keyword

The built-in text scoring matches substrings.
A caller whose goal text does not share vocabulary with the operator descriptions can supply its own embedder instead, build an `OperatorEmbeddingIndex` over the same registry, and hand the index to the planner.
Discovery then ranks tag-matching cards by cosine similarity rather than by keyword hit.

The caller owns the embedder and its `space_id`; the package neither picks nor installs an embedding model.
The index is a snapshot, and a card whose metadata has changed underneath it raises `EmbeddingDiscoveryError` with reason `STALE_INDEX` rather than returning a stale answer.

**Example:**

```python
import re
from collections.abc import Sequence

from blue_data_ops.operators import OperatorEmbeddingIndex, active_registry


class KeywordEmbedder:
    space_id = "orders-keywords-v1"
    _FILTER_WORDS = frozenset({"filter", "keep", "select", "where"})
    _AVERAGE_WORDS = frozenset({"average", "avg", "mean"})

    def __call__(self, texts: tuple[str, ...]) -> Sequence[Sequence[float]]:
        vectors: list[tuple[float, float, float]] = []
        for text in texts:
            words = set(re.findall(r"[a-z0-9_]+", text.casefold()))
            vectors.append(
                (
                    float(len(words & self._FILTER_WORDS)),
                    float(len(words & self._AVERAGE_WORDS)),
                    1.0,
                )
            )
        return vectors


catalog = active_registry()
index = OperatorEmbeddingIndex.build(catalog, KeywordEmbedder())
cards = index.find("mean order total", tags=["capability-average"])

assert [card.operator_id for card in cards] == ["avg@3.0.0"]
assert index.registry is catalog
```

`examples/integration-demos/embedding_planner.py` feeds this index into `PipelinePlanner` and plans against the goal text rather than the operator names.

---

## Scenario 11: Letting a Model Propose the Plan

A caller whose goals do not fit a fixed template can hand generation to `OpenAIPlanGenerator`, which makes one non-streaming Responses request per `generate()` and returns ordinary `PlanDraft` candidates.
The planner keeps everything else: normalization, selection, compilation, and preflight all run afterwards against the live registry.

`allowed_operator_ids` is the authorization boundary, not a ranking hint.
A card reaches the model only when the caller allowlisted it, discovery returned it, this exact registry built it, it pins a supported `@2.0.0` or `@3.0.0` version, and it carries no `produces-side-effect` tag.
The decoder re-checks the same set, so a model naming anything else fails before a draft exists.

Schema disclosure is a second, separate opt-in.
A `DataContextSnapshot` reaching `generate()` without `send_data_context=True` raises `DATA_CONTEXT_DISCLOSURE_REQUIRED` before the SDK import, the client, and any provider traffic — the snapshot is never quietly dropped, because planning without the schema would answer a different question than the one the caller asked.

**Example:**

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

Provider failures map onto stable planning codes such as `GENERATOR_TIMEOUT`, `GENERATOR_RATE_LIMITED`, and `GENERATOR_UNAVAILABLE`.
No response body, request payload, credential, provider identifier, or exception text is interpolated into the record, so the record shape survives a change in the SDK's own messages.

---

## Scenario 12: Reading an Operator's Own Documentation Before Calling It

An agent or a code generator deciding how to call an operator needs more than a one-line description, and it should not have to parse the implementation.
Every active exact ID has a resource package declaring a guide and a worked-examples file.
`OperatorSkillLoader` validates the binding, checks each file's SHA-256 against its manifest, and returns the text together with the operator's live attribute schema and its declared input and output shapes.

Loading a resource does not invoke the operator, and it does not add the text to planner or provider input.
Disclosure is the caller's decision, made after it has seen what it would be disclosing.

**Example:**

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import active_registry

registry = active_registry()
loader = OperatorSkillLoader(registry)

descriptor = loader.describe("avg@3.0.0")
view = loader.load("avg@3.0.0", level=max(descriptor.declared_levels))

assert descriptor.declared_kinds == ("guide", "examples")
assert descriptor.declared_levels == (2, 3)
assert view.card is registry.get_card("avg@3.0.0")
assert view.io.input_shape == "List[List[Dict]]"
assert view.io.attributes["avg_key"].required
assert len(loader.available_operator_ids()) == 33
```

Level 2 is the card plus the live attribute schema plus the guide; level 3 adds the examples.
`examples/feature-demos/operator_skill_discovery.py` also shows the ineligible case: `avg@1.0.0` stays searchable in the history registry and has no resource package, so `available_operator_ids()` is the check to make before expanding anything.

---

## Scenario 13: Serving the Operators to an Agent

An LLM agent needs to call these operators without a Python import.
The MCP adapter registers the 33 active operators as primary tools over the canonical `run()` boundary, adds `ops_` to each logical name, and carries the exact pinned ID in `_meta`.
`create_server()` returns a configured `FastMCP` instance for embedding; `serve()` starts it over streamable HTTP, bound by default to `127.0.0.1:8000/mcp`.

A call that satisfies the container schema but fails operator validation is still a successful MCP result, with the record inside `exec_meta`.
`isError` is reserved for an unknown tool, malformed top-level arguments, or a projection failure — the things that are wrong with the call rather than with the data.

**Example:**

```python
import asyncio

from blue_data_ops_mcp import create_server
from mcp.shared.memory import create_connected_server_and_client_session


async def main() -> None:
    server = create_server(operator_ids=("select@2.0.0",))
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        listing = await client.list_tools()
        assert [tool.name for tool in listing.tools] == ["ops_select"]
        assert listing.tools[0].meta["operator_id"] == "select@2.0.0"

        result = await client.call_tool(
            "ops_select",
            {
                "input_data": [[{"name": "a", "score": 3}, {"name": "b", "score": 9}]],
                "attributes": {"operand_key": "score", "operand": ">", "operand_val": 5},
            },
        )
        if result.isError:
            raise RuntimeError(result.content[0].text)
        assert result.structuredContent["output_data"] == [[{"name": "b", "score": 9}]]


asyncio.run(main())
```

Passing `operator_ids` replaces the default selection with an exact pinned subset, which is how a deployment narrows what an agent can reach.
[`../platform/ops-mcp/README.md`](../platform/ops-mcp/README.md) is the source of truth for the adapter.

---

## Scenario 14: Migrating a 2.x Caller

A caller on core 2.x upgrading to 3.0 finds four operator names gone — `multipart_query`, `nl2query_router`, `plan_discover`, and `query_breakdown` — along with all eight of their v1 and v2 exact IDs and the refinement API.
A stored `DataPipeline` naming one of them still parses through `from_dict()`, then fails executor preflight at exact resolution, which is where the caller learns what changed.

The supported migration has two shapes.
A `DeclarativeOperator` used as an executable leaf becomes an ordinary `Operator` subclass.
A declarative plan definition becomes either a materialized `DataPipeline` the caller constructs and executes directly, or a `PlanGenerator.generate()` implementation returning `Sequence[PlanDraft]` for `PipelinePlanner`.

This migration is not drop-in.
Automatic refinement, expansion of old declarative plan definitions, dynamic alternatives, and malformed-plan normalization are not preserved, and a caller that needs them stays on a compatible core 2.x and MCP 0.x pair.
Where 1.x or 2.x behavior is deliberately wanted, `versioned_registry()` resolves it by exact ID and `default_registry()` keeps the raw compatibility view with its per-name version override.

**Example:**

```python
from blue_data_ops.operators import ResolveError, active_registry, versioned_registry

history = versioned_registry()
assert history.resolve("avg@1.0.0").operator_id == "avg@1.0.0"
assert history.resolve("avg@2.0.0").operator_id == "avg@2.0.0"

try:
    active_registry().resolve("multipart_query@2.0.0")
except ResolveError as error:
    print(error)  # no operator registered as 'multipart_query@2.0.0'
```

[`../lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md) is the source of truth for the per-surface migration boundaries.

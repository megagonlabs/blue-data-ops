# Quick Start

Install `blue-data-ops` from a source checkout, then run an operator, a two-step pipeline, and the planner.
No credentials, nothing to download beyond the two checkouts.
For the wheel path, the optional extras, and the provider-backed operators, see [installation.md](installation.md).

## 1. Put the two checkouts under one parent directory

`blue-data` is a source dependency of `blue-data-ops`, so the two must be siblings; run every command below from that shared parent.

```bash
ls -d blue-data blue-data-ops
```

## 2. Create and activate a virtual environment

The package's own tooling expects the environment at `lib/.venv`, so put it there.

```bash
python3 -m venv blue-data-ops/lib/.venv
source blue-data-ops/lib/.venv/bin/activate
```

## 3. Install `blue-data` first, then this package

The base install carries all 33 operators; the ML, vector, and LLM operators need the extras in [installation.md](installation.md).

```bash
python -m pip install -e ./blue-data/lib
python -m pip install -e ./blue-data-ops/lib
```

## 4. Check the install

`active_registry()` is the ordinary 3.0 view of the catalog, and it holds 33 exact operator cards.

```bash
python -c "from blue_data_ops.operators import active_registry; print(len(active_registry().list_cards()))"
```

## 5. Run one operator

`run()` returns the output bundle, a fresh output-attributes mapping, and execution metadata; input and output are both `list[list[dict]]`, a list of record groups.

```python
from blue_data_ops import SelectOperator

operator = SelectOperator()
data = [[{"name": "a", "score": 3}, {"name": "b", "score": 9}]]
attributes = {"operand_key": "score", "operand": ">", "operand_val": 5}

output_data, output_attributes, meta = operator.run(data, attributes)
print(output_data)  # [[{'name': 'b', 'score': 9}]]
print(meta.errors)  # []
```

## 6. Find an operator instead of naming its class

`find()` scores the query text and ANDs the tag filters, then `resolve()` binds the exact `name@<MAJOR.MINOR.PATCH>` id it returned.

```python
from blue_data_ops.operators import active_registry

catalog = active_registry()
cards = catalog.find("filter", tags=["domain-relational", "flow-transform"])
print([card.operator_id for card in cards])  # ['select@2.0.0']

operator = catalog.resolve(cards[0].operator_id)
output_data, _, _ = operator.run(
    [[{"name": "a", "score": 3}, {"name": "b", "score": 9}]],
    {"operand_key": "score", "operand": ">", "operand_val": 5},
)
print(output_data)  # [[{'name': 'b', 'score': 9}]]
```

## 7. Chain two operators into a pipeline

A `DataPipeline` is a graph record; `PipelineExecutor` preflights it, then runs the nodes in topological order.

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
print(run.succeeded)                                   # True
print(run.output_data)                                 # [[{'avg': 10.0}]]
print([node.operator_id for node in run.node_runs])    # ['select@2.0.0', 'avg@3.0.0']
```

## 8. Let the planner build that pipeline from a goal

`PipelinePlanner` runs discovery, generation, selection, compilation, and preflight; the shipped rule generator turns a filter-then-average goal into the same two steps.

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

run = planner.run(request, [[{"total": 120.0}, {"total": 215.0}, {"total": 50.0}]])
print([step.operator_id for step in run.planning.selected.steps])  # ['select@2.0.0', 'avg@3.0.0']
print(run.execution.output_data)                                   # [[{'average_total': 167.5}]]
```

## Next steps

- [features.md](features.md) — what the library can do, with a short example per feature
- [guide.md](guide.md) — the same material organized task by task, plus registry-backed tables, operator resources, and migration from 2.x
- [../examples/README.md](../examples/README.md) — whole programs you can run as they are
- [mcp.md](mcp.md) — serve the same operators as MCP tools
- [cli.md](cli.md) — run the same operators from a shell

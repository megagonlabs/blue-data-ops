# blue-data-ops

`blue-data-ops 2.0.0` is the standalone Python package for Blue data operators. It includes record-oriented transforms, registry-backed database operations, pinned operator discovery, and structured execution results. Operator input and output use `list[list[dict]]`: a list of record groups.

## Requirements

- Python 3.10+
- `blue-data` 0.1.0 or later. It is an eager import-time dependency and must be importable whenever `blue_data_ops` is imported. Registry-backed operators access it through the data seam.

## Installation

From the repository root, install the package and the extras needed by your deployment:

```bash
python -m venv .venv && source .venv/bin/activate
python -m pip install "./lib[ml,vector,llm]"
```

For development:

```bash
python -m pip install -e "./lib[dev]"
```

If your artifact index is configured separately, install the released artifact instead:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==2.0.0"
```

The resolver also obtains `blue-data>=0.1.0` from that index. For an offline source install, install the `blue-data` checkout or wheel first, then install `./lib`. The optional extras are `ml` for `classify` and `cluster`, `vector` for the three vector operators, and `llm` for the `nl2*` and `semantic_*` operators plus `query_breakdown`.

## Usage

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

`create_database`, `create_table`, `insert_table`, and `data_discover` need a `blue-data` registry. Create the `DataSource` with `blue-data`, register it, then pass the seam in `properties`:

```python
from blue_data_ops import CreateDatabaseOperator, RegistrySeam
from blue_data.registry.data_registry import DataRegistry

registry = DataRegistry(name="orders", rebuild=True)
seam = RegistrySeam(registry)
seam.register_source(source)  # source is a blue_data.source.source.DataSource

CreateDatabaseOperator().invoke(
    [[]],
    {"source": source.name, "database": "main"},
    {"data_registry": seam},
)
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
| Plan-producing | `multipart_query`, `nl2query_router`, `plan_discover`, `query_breakdown` |

The `nl2*` and `semantic_*` operators plus `query_breakdown` send requests through [litellm](https://github.com/BerriAI/litellm); configure the model per call via properties (default `openai.model: gpt-4o`). `classify` uses NumPy and scikit-learn from the `ml` extra. Registry-backed operators talk to `blue-data` through the data seam.

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

An empty result is still successful. `run()` normalizes any empty group shape to `[[]]`, sets `is_empty=True`, and leaves `errors` empty:

```python
empty_data, _, empty_meta = op.run(
    [[{"score": 3}]],
    {"operand_key": "score", "operand": ">", "operand_val": 99},
)
assert empty_data == [[]]
assert empty_meta.is_empty is True
assert empty_meta.errors == []
```

Invalid input and execution failures are data, not raised operator exceptions. The failure output is `[[]]`, and the error record identifies the boundary:

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

`apply()` and `invoke()` remain the raw v1-compatible paths through v2.x. `apply()` calls the transform directly. `invoke()` runs boolean `validate()` and then `apply()`, returning `None` when validation is false. They do not provide canonical default materialization or contained `ExecMeta`; use `run()` when the caller needs those semantics. See [COMPATIBILITY.md](COMPATIBILITY.md) for the migration boundary.

The rest of the compatibility surface remains public: `validate()` checks the live attribute schema and never raises, `explain()` describes a completed transform, and `attributes`, `is_required(name)`, and `default_of(name)` expose the declared attributes.

### Refinement and plan representation

The four plan-producing operators expose raw `refiner()` and normalized `refine()` calls. `refiner()` keeps the v1 serialized-record shape. `refine()` returns `(list[DataPipeline], ExecMeta)` and reports empty or failed refinement through the same metadata model as `run()`.

```python
from blue_data_ops.plan import DataPipeline, RefinableOperator

refinable = versioned_registry().resolve("multipart_query@2.0.0")
assert isinstance(refinable, RefinableOperator)
input_data = []
attributes = {}
plans, refine_meta = refinable.refine(input_data, attributes)
records = [plan.to_dict() for plan in plans]
restored = [DataPipeline.from_dict(record) for record in records]
```

`DataPipeline.to_dict()` and `DataPipeline.from_dict()` are the portable representation boundary. A pipeline records pinned operator IDs, nodes, and edges. `PipelineExecutor` runs a materialized pipeline locally:

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

The executor resolves every pinned ID before it calls an operator, traverses the graph in stable topological order, forwards predecessor groups, and records each completed operator in `run.node_runs`. A successful empty result continues through the graph. The first structured node error stops the run and sets `failed_node_id`.

Only materialized plans are executable. Call `refine()` first, choose one returned plan, and pass that plan to the executor. An execution node that still resolves to a `RefinableOperator` is rejected during preflight. The executor does not retry, replan, select alternatives, dispatch remotely, or provide Redis/pubsub synchronization. Execution updates node values and statuses on the supplied plan; round-trip a copy first if the original record must remain unchanged.

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
├── pyproject.toml
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
│       ├── plan/                 # serializable plans, refinement, local executor
│       └── data/
│           ├── registry_seam.py  # facade over a blue-data DataRegistry
│           └── provider.py       # registry resolution + default cached provider
└── tests/
    ├── doubles/                  # in-memory seam and source doubles
    └── unit/
```

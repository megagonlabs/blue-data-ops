# blue-data-ops

Python library of Blue data operators — record-oriented transforms (filter, project, join, set,
aggregate, text) and registry-backed database operations. Each operator is a class with a declared
attribute schema, validation, and invocation.

## Requirements

- Python 3.10+
- **blue-data** 0.1.0 or later (installed independently); used only by the data seam.

## Installation

Install `blue-data` first, then install this package from source into the same environment:

```bash
python -m venv .venv && source .venv/bin/activate
cd lib
python -m pip install -e ".[dev]"
```

Optional extras:

```bash
python -m pip install -e ".[ml]"      # classify, cluster
python -m pip install -e ".[vector]"  # vector_embed, vector_search, vector_similarity
python -m pip install -e ".[llm]"     # nl2llm, nl2sql, nl2bn, semantic_*
```

## Usage

```python
from blue_data_ops import SelectOperator

op = SelectOperator()
data = [[
    {"name": "a", "score": 3},
    {"name": "b", "score": 9},
]]

# invoke = validate, then apply; returns None when attributes are invalid
out = op.invoke(data, {"operand_key": "score", "operand": ">", "operand_val": 5})
# [[{"name": "b", "score": 9}]]

op.attributes            # declared attribute schema (name -> AttributeSpec)
op.validate(data, {})    # False — operand_key/operand/operand_val are required
```

Registry-backed operators (`create_database`, `create_table`, `insert_table`, `data_discover`)
resolve their data registry from `properties` — inject a `RegistrySeam`, or pass `platform.name` +
`data_registry.name` to use the default provider. The example below is conceptual — `source` is a
`blue-data` `DataSource`; see the blue-data docs to construct one.

```python
from blue_data_ops import CreateDatabaseOperator, resolve_registry

seam = resolve_registry({"platform.name": "p", "data_registry.name": "r"})
seam.register_source(source)

CreateDatabaseOperator().invoke(
    [[]],
    {"source": source.name, "database": "main"},
    {"data_registry": seam},
)
```

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

LLM operators send requests through [litellm](https://github.com/BerriAI/litellm); configure the
model per call via properties (default `openai.model: gpt-4o`). Registry-backed operators talk to
`blue-data` through the data seam.

### `OperatorRegistry`

`OperatorRegistry` (in `blue_data_ops.operators`) registers operators under an immutable
`name@<MAJOR.MINOR.PATCH>` id, resolves pinned ids exactly (`resolve`), and discovers by
name/description/tags (`find`, `find_latest`). `default_registry()` preloads every operator in this
package at `1.0.0` and needs no `blue-data`:

```python
from blue_data_ops.operators import default_registry

registry = default_registry()             # every operator, pinned at 1.0.0
op = registry.resolve("select@1.0.0")     # exact pinned id -> Operator
cards = registry.find("join")             # rule-based discovery -> [OperatorCard, ...]
latest = registry.find_latest("nl2sql")   # highest-version card for a name
```

### `Operator`

| Method | Description |
|---|---|
| `apply(input_data, attributes, properties=None)` | Run the transform; input and output are `list[list[dict]]` |
| `validate(input_data, attributes, properties=None)` | Check attributes against the declared schema; never raises |
| `invoke(...)` | `validate`, then `apply`; returns `None` when invalid |
| `explain(output, input_data, attributes)` | Describe a completed transformation |
| `attributes` / `is_required(name)` / `default_of(name)` | The declared attribute schema |

## Compatibility

See [COMPATIBILITY.md](COMPATIBILITY.md) for deliberate behavior differences that callers and
maintainers should preserve across upgrades.

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
│       ├── llm/                  # LLM client, templating, resolution (litellm-backed)
│       └── data/
│           ├── registry_seam.py  # facade over a blue-data DataRegistry
│           └── provider.py       # registry resolution + default cached provider
└── tests/
    ├── doubles/                  # in-memory seam and source doubles
    └── unit/
```

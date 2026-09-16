# blue-data-ops

A Python library of Blue data operators addressed by exact version: record transforms, registry-backed database operations, vector and ML operators, and a local pipeline planner.

→ **[Documentation](docs/README.md)** · **[Quick start](docs/quickstart.md)** · **[Examples](examples/README.md)**

## What it does

- Resolves operators by exact ID, so `avg@3.0.0` means one implementation and keeps meaning it after the next release. The active registry holds 33 cards: 12 at `@2.0.0` and 21 at `@3.0.0`.
- Keeps 87 historical cards in a separate registry view. Migration code can resolve an older version without changing what ordinary discovery returns.
- Finds operators by keyword and by six tag axes, or by cosine distance over an embedding index the caller supplies. See [tag discovery](lib/README.md#discovery) and the generated [tag reference](lib/OPERATORS.md#tag-taxonomy).
- Returns one shape from every operator: output records, output attributes, and execution metadata that carries errors instead of raising them.
- Plans and runs small pipelines from a stated goal and a set of discovery queries. The rule-based generator does this without calling a provider.
- Carries 54 resource packages keyed by exact operator ID, read only when a caller asks for one, so operator documentation never lands in a prompt by accident.
- Exposes the 33 active operators as MCP execution tools from a second distribution.

## Repository layout

```text
blue-data-ops/
├── README.md              # this file
├── design/                # architecture and the decisions behind it
├── docs/                  # user documentation, starting at docs/README.md
├── examples/              # runnable scripts, grouped by purpose
├── lib/                   # the blue-data-ops library
├── platform/mcp/          # the blue-data-ops-mcp server
└── .gitignore             # build output, environments, caches, local databases
```

## Requirements

- Python 3.11 or later.
- `blue-data` 0.1.0 or later. The library imports it eagerly, so it has to be installed before `blue_data_ops` will import.
- A source checkout of `blue-data` beside this one, under a shared parent directory:

```text
workspace/
├── blue-data/
└── blue-data-ops/
```

The core declares `pydantic`, `jsonmerge`, `jsonpath-ng`, and `tenacity`, which pip installs along with it.
Optional extras pull the heavier dependencies only when you want those operators.

| Extra | Adds | Needed for |
|---|---|---|
| `ml` | numpy, scikit-learn | `classify`, `cluster`, `sklearn_estimator` |
| `vector` | numpy, sentence-transformers | `vector_embed`, `vector_search`, `vector_similarity` |
| `llm` | litellm, tenacity, diskcache, jinja2 | `nl2llm`, `nl2sql`, `nl2bn`, and the `semantic_*` operators |
| `openai` | openai | `OpenAIPlanGenerator` |
| `dev` | pytest, ruff, pyright, build, twine | working on this repository |

`dev` also brings in the `ml` and `openai` dependencies, so add `llm` and `vector` on top of it when you need those operators.

## Quick start

From the directory that holds `blue-data/` and `blue-data-ops/`, create an environment and install both packages:

```bash
python -m venv blue-data-ops/lib/.venv
source blue-data-ops/lib/.venv/bin/activate
python -m pip install -e ./blue-data/lib
python -m pip install -e "./blue-data-ops/lib[dev]"
```

Check the install from the library directory, then come back up and run the first example:

```bash
cd blue-data-ops/lib
python -m pytest
cd ..
python examples/quickstart/core_quickstart.py
```

That prints a filtered record group, its average, a normalized text field, and a union.

The full walkthrough, with a pipeline and the MCP route, is in [docs/quickstart.md](docs/quickstart.md).

## Packages

| Package | Description |
|---|---|
| [lib/](lib/README.md) | `blue-data-ops` 3.0.0 — the operator library, its registries, the resource packages, and the local planner |
| [platform/mcp/](platform/mcp/README.md) | `blue-data-ops-mcp` 0.13.0 — an MCP server exposing 33 primary execution tools, one per active operator |

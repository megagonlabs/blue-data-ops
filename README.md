# blue-data-ops

Reusable data operators for Blue's agentic data flows.

Blue coordinates AI agents that use existing data and tools, while `blue-data` catalogs the structure and meaning of available sources. `blue-data-ops` gives agents and applications a standard atomic unit for each data operation: an operator performs a defined step through a shared execution contract, whether called directly, connected in a pipeline, or selected by a planner.

→ **[Full documentation](docs/README.md)** · **[Quick start](docs/quickstart.md)** · **[Installation](docs/installation.md)** · **[Examples](examples/README.md)** · **[CLI](docs/cli.md)** · **[MCP](docs/mcp.md)**

## What it does

- **Standardize data operations** with reusable operators that share an execution contract across eight families: filtering and shaping, joins and set operations, aggregation, text processing, machine learning, vector operations, LLM and semantic operations, and registry-backed discovery and database operations.
- **Work with registered data**: discover sources, create databases and tables, insert records, and turn natural-language requests into queries that can be executed against a configured backend when enabled.
- **Use ML, vector, and LLM operators** for classification, clustering, embeddings, vector search and similarity, semantic filtering, extraction, and other LLM-based operations when their optional dependencies are installed.
- **Discover** operators by keyword, six tag axes, or a caller-supplied embedding index. The active registry holds 33 cards, and a versioned registry retains 87. An exact ID such as `avg@3.0.0` continues to identify the same implementation after a release.
- **Plan and run** data flows with `DataPipeline`, `PipelineExecutor`, and a rule-based or OpenAI-backed `PipelinePlanner`.
- **Call** the active operators from Python, the `blue-ops` command, or MCP clients. The MCP server exposes 33 `ops_`-prefixed tools. The library's `run()` result carries output records, optional output attributes, and execution metadata, including errors.

See [features](docs/features.md) for the capabilities, [examples](examples/README.md) for runnable programs, and the [library guide](lib/README.md) for operator contracts, settings, and the 54 exact-version reference packages.

## Repository layout

```text
blue-data-ops/
├── README.md              # this overview
├── CHANGELOG.md           # release history
├── LICENSE                # repository license
├── design/                # architecture and design decisions
├── docs/                  # user guides and API reference
├── examples/              # runnable programs and CLI sample inputs
│   └── cli/               # order records and planning request used by the CLI guide
├── lib/                   # blue-data-ops Python library and install script
├── platform/
│   ├── ops-cli/           # blue-ops command
│   └── ops-mcp/           # blue-data-ops-mcp server
├── ruff.toml              # repository lint configuration
└── .gitignore             # local output and environment exclusions
```

## Requirements

- Python 3.12 recommended; release verification covers Python 3.11 and 3.12.
- A `blue-data` checkout beside this repository for the source installer. The library requires `blue-data>=1.0.0` at import time.
- Provider credentials for LLM-backed operators and OpenAI planning; record transforms and the rule-based planner need none.

For the source-install commands, keep the two checkouts under one parent:

```text
workspace/
├── blue-data/
└── blue-data-ops/
```

The installer looks for `../blue-data/lib` relative to this checkout. If that checkout is elsewhere, set `BLUE_DATA_PATH` to its `lib` directory.

OpenAI-backed calls read `OPENAI_API_KEY`. See [model settings](docs/llm-settings.md) for other providers. Enter the key without putting its value in shell history:

```bash
# export BLUE_DATA_PATH=/absolute/path/to/blue-data/lib  # for a non-sibling checkout
printf 'OpenAI API key: '
read -rs OPENAI_API_KEY && export OPENAI_API_KEY
printf '\n'
```

Optional extras:

| Extra | Used for |
|---|---|
| `ml` | classification, clustering, and scikit-learn estimators |
| `vector` | embeddings, vector search, and vector similarity |
| `llm` | natural-language and semantic operators |
| `openai` | the OpenAI-backed pipeline generator |

The [installation guide](docs/installation.md) lists the dependencies, the development extra, and the separate CLI and MCP installers.

## Quick start

From the directory containing both `blue-data/` and `blue-data-ops/`:

```bash
python3.12 -m venv blue-data-ops/lib/.venv
source blue-data-ops/lib/.venv/bin/activate
./blue-data-ops/lib/scripts/install.sh
python blue-data-ops/examples/quickstart/core_quickstart.py
```

The example filters order records, computes their average, normalizes a text field, and unions record groups. The install script first installs the sibling `blue-data` checkout, then the library with its development dependencies. For Conda, package-specific installs, pipelines, and planning, continue with the [full quick start](docs/quickstart.md).

## Packages

| Package | Description |
|---|---|
| [lib/](lib/README.md) | `blue-data-ops` 1.0.0: the Python `blue_data_ops` library, operator registry, resources, and local planner; installs no console command |
| [platform/ops-cli/](platform/ops-cli/README.md) | `blue-data-ops-cli` 1.0.0: installs the `blue-ops` command for profiles, catalogs, operators, pipelines, and metadata |
| [platform/ops-mcp/](platform/ops-mcp/README.md) | `blue-data-ops-mcp` 1.0.0: installs the `blue-data-ops-mcp` command serving the active operators as MCP tools |

## Conduct and disclosures

See the [Code of Conduct](CODE_OF_CONDUCT.md),
[disclosures](docs/disclosures.md), and [NOTICE](NOTICE).

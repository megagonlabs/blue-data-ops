# Installation

Every supported way to install the two distributions in this repository, and what each one gives you.
[`lib/README.md`](../lib/README.md) is the package README and stays the source of truth for the library's own requirements and minimal usage; this page covers both packages and the paths between them.

## Packages

| Package | Version | Path | Depends on |
|---|---|---|---|
| `blue-data-ops` | `3.0.0` | [`lib/`](../lib/README.md) | Python >= 3.11, `blue-data>=0.1.0` |
| `blue-data-ops-mcp` | `0.13.0` | [`platform/mcp/`](../platform/mcp/README.md) | Python >= 3.11, `blue-data-ops==3.0.0` |

Install `blue-data-ops` first.
The adapter pins it exactly, so the two versions move together.

There are no install scripts in this repository.
Install with `pip` directly, using one of the three paths below.

## Requirements

- Python 3.11 or later.
- `blue-data` 0.1.0 or later. The library imports it eagerly, so it must be importable before `blue_data_ops` is.
- For a source checkout, `blue-data` and `blue-data-ops` under the same parent directory:

```text
workspace/
├── blue-data/
└── blue-data-ops/
```

The core runtime dependencies are `blue-data>=0.1.0`, `pydantic>=2`, `jsonmerge==1.9.2`, `jsonpath-ng`, and `tenacity`.
Everything heavier sits behind an extra.

## Path 1: editable source install

Run these from the parent directory that holds both checkouts.

```bash
python3 -m venv blue-data-ops/lib/.venv
source blue-data-ops/lib/.venv/bin/activate
python -m pip install -e ./blue-data/lib
python -m pip install -e ./blue-data-ops/lib
```

Add the extras you need in the same command:

```bash
python -m pip install -e "./blue-data-ops/lib[ml,vector,llm]"
```

This is the direct path for a contributor, and the one [quickstart.md](quickstart.md) follows.

## Optional extras

| Extra | Packages | Needed for |
|---|---|---|
| `ml` | `numpy`, `scikit-learn` | `classify`, `cluster`, `sklearn_estimator` |
| `vector` | `numpy`, `sentence-transformers` | `vector_embed`, `vector_search`, `vector_similarity` |
| `llm` | `litellm>=1.98,<2`, `tenacity`, `diskcache`, `jinja2` | `nl2llm`, `nl2sql`, `nl2bn`, and the five `semantic_*` operators |
| `openai` | `openai>=2.54,<3` | `OpenAIPlanGenerator` |
| `dev` | `numpy`, `scikit-learn`, `tenacity`, `diskcache`, `jinja2`, `openai>=2.54,<3`, `pytest`, `pytest-asyncio`, `pytest-recording`, `pytest-cov`, `ruff`, `pyright`, `build`, `twine` | running the tests, the linters, and the build |

`dev` deliberately leaves out `litellm` and `sentence-transformers`.
The test suite substitutes deterministic stubs for those two from `lib/tests/stubs/`, so the default test run needs neither the download nor a provider.
Install `llm` or `vector` alongside `dev` when you want to exercise the real libraries.

The base install carries all 33 operator cards, so discovery, resolution, and pipeline construction work without any extra.
An operator whose extra is missing does not raise on import; its `run()` call returns `[[]]` with an `EXECUTION_FAILED` record in the execution metadata.
[guide.md](guide.md) shows what that looks like.

`sentence-transformers` pulls a deep dependency tree and is the slowest extra to install.
Install `vector` only when you need embedding generation or search; `vector_similarity` over embeddings you already have needs nothing beyond `numpy`.

## Path 2: built wheel

Build from `lib/` with the `dev` extra installed.
`python -m build` writes `blue_data_ops-3.0.0-py3-none-any.whl` and `blue_data_ops-3.0.0.tar.gz` into `lib/dist/`.

```bash
cd blue-data-ops/lib
python -m build
python -m pip install "dist/blue_data_ops-3.0.0-py3-none-any.whl[ml,vector,llm]"
```

A wheel installs the importable package and its resources: the operator implementations, the `operator_skills/` resource packages, the plan JSON schemas, and `py.typed`.
It does not install the top-level documentation files.
[`lib/README.md`](../lib/README.md) reaches you through distribution metadata, and [`lib/OPERATORS.md`](../lib/OPERATORS.md) and [`lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md) are in the checkout and the source distribution.
Extract the matching sdist if you need those two next to a wheel install.
The [examples](../examples/README.md) are in the checkout only: they sit above the packaged directory, so no wheel or source distribution carries them.

## Path 3: released artifact

If your artifact index is configured separately, install the published distributions instead of building them.
The index must also provide `blue-data>=0.1.0`.

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==3.0.0" \
  "blue-data-ops-mcp==0.13.0"
```

## The MCP adapter

Install the core first, then the adapter.
From the repository root:

```bash
python -m pip install ../blue-data/lib
python -m pip install "./lib[ml,vector,llm]"
python -m pip install ./platform/mcp
```

The adapter pins `mcp==1.27.2` and `pydantic>=2.11,<3` on top of the core's dependencies.
It serves 33 primary tools, the same selection the core's `active_registry()` returns.
There is no console entry point; start it from Python, as [mcp.md](mcp.md) shows.

## Provider credentials

The LLM-backed operators resolve a provider client when they are called, and `OpenAIPlanGenerator` constructs one at first use.
Supply the credential through the provider's own environment variable rather than through a call argument.
`<your-key>` is a placeholder for your own key, which belongs in the environment and not in a committed file.

```bash
export OPENAI_API_KEY=<your-key>
```

The default model is `gpt-4o`, selected by the `openai.model` call property.
Nothing else in the package reads a credential: the record transforms, the registry-backed operations, discovery, the executor, and the rule-based planner all run offline.

## Confirming an install

```bash
python -c "from importlib.metadata import version; print(version('blue-data-ops'))"
python -c "from blue_data_ops.operators import active_registry; print(len(active_registry().list_cards()))"
```

The first prints the distribution version, `3.0.0`.
The second prints `33`, the number of active operator cards.
Those two numbers move independently: an operator card carries its own version, and twelve of the 33 are active at `@2.0.0` while the other twenty-one are at `@3.0.0`.

## Running the tests

With the `dev` extra installed, from `lib/`:

```bash
python -m pytest
```

The adapter has its own suite.
From `platform/mcp/`:

```bash
python -m pytest
```

Both configurations set `asyncio_mode = "auto"` and report coverage on `src`.
Ruff and Pyright read their settings from the same `pyproject.toml`:

```bash
python -m ruff format --check .
python -m ruff check .
python -m pyright
```

## Next steps

- [quickstart.md](quickstart.md) — five minutes from an install to a running pipeline
- [features.md](features.md) — what the library can do, with a short example per feature
- [guide.md](guide.md) — the task-by-task walkthrough
- [../examples/README.md](../examples/README.md) — which scripts need which extra, and which need a credential

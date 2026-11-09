# Installation

Every supported way to install the three distributions in this repository, and what each one gives you.
[`lib/README.md`](../lib/README.md) is the package README and stays the source of truth for the library's own requirements and minimal usage; this page covers all three packages and the paths between them.

## Packages

| Package | Version | Path | Depends on |
|---|---|---|---|
| `blue-data-ops` | `1.0.0` | [`lib/`](../lib/README.md) | Python >=3.12,<3.14, `blue-data>=1.0.0,<2` |
| `blue-data-ops-mcp` | `1.0.0` | [`platform/ops-mcp/`](../platform/ops-mcp/README.md) | Python >=3.12,<3.14, `blue-data-ops==1.0.0` |
| `blue-data-ops-cli` | `1.0.0` | [`platform/ops-cli/`](../platform/ops-cli/README.md) | Python >=3.12,<3.14, `blue-data-ops[ml,vector,llm]==1.0.0`, `click>=8.0`, `rich>=13.0` |

Install `blue-data-ops` first.
Both interface packages pin it exactly, so their versions move with it.

Each package carries `scripts/install.sh`, which runs the `pip` commands below in the right order and resolves `blue-data` from the sibling checkout.
The paths below are those commands spelled out, for an install that is not a source checkout or a `blue-data` that lives somewhere else.

## Requirements

- Python 3.12 or 3.13 (`requires-python = ">=3.12,<3.14"`).
- `blue-data` 1.0.0 or later. The library imports it eagerly, so it must be importable before `blue_data_ops` is.
- For a source checkout, `blue-data` and `blue-data-ops` under the same parent directory:

```text
workspace/
├── blue-data/
└── blue-data-ops/
```

The core runtime dependencies are `blue-data>=1.0.0,<2`, `pydantic>=2`, `jsonmerge==1.9.2`, `jsonpath-ng<2`, and `tenacity<10`.
Everything heavier sits behind an extra.
Editable installs also need the build requirements declared by each package, including `setuptools>=77.0.3` and `wheel`. Configure a package index or provide a wheelhouse containing these and the runtime dependencies before installing in a fresh environment.

Python 3.12 and 3.13 are the supported interpreters (`requires-python = ">=3.12,<3.14"`). The [historical CPython 3.15 compatibility-wheel notes](history/python315-compatibility-wheels.md) are outside the declared range; pip refuses that install. Other platforms and free-threaded Python 3.15 have not been verified.

Select a source whose metadata satisfies `blue-data>=1.0.0,<2`. The verified 1.0 source
includes `blue_data.server` and the `server` extra; the 0.1.0 development source cannot
satisfy this release. The preflight checks source identity and layout; pip enforces
the core dependency range when installing the core. Set `BLUE_DATA_PATH` to a compatible `lib` directory and
`PYTHON` to the intended interpreter when using `scripts/install.sh`. MCP additionally
validates and installs that same source's `[server]` extra. CLI alone does not need it.

All three distributions in this checkout declare 1.0.0. If an environment already contains
a numerically higher core version, select `==1.0.0` explicitly; an unqualified upgrade may
retain or choose the higher version.

## Path 1: editable source install

Run these from the parent directory that holds both checkouts.

Select Python 3.12 or 3.13, then create and activate a standard virtual environment:

```bash
python3.12 --version
python3.12 -m venv blue-data-ops/lib/.venv
source blue-data-ops/lib/.venv/bin/activate
```

or a Conda environment:

```bash
conda create --name blue-data-ops python=3.12 pip
conda activate blue-data-ops
```

If Conda reports that activation is unavailable, run `conda init zsh` once (replace `zsh` with your shell), reopen the shell, and return to the directory that holds both checkouts.

With either environment active, install the two source packages. Their `pyproject.toml` files declare the dependency requirements:

```bash
python -m pip install -e ./blue-data/lib
python -m pip install -e ./blue-data-ops/lib
```

Installation, runtime use, and pytest work in either environment. The repository's Pyright configuration still looks for `lib/.venv`, so use the standard virtual-environment path when running the Pyright check.

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
| `llm` | `litellm>=1.98,<2`, `tenacity<10`, `diskcache<6`, `openai>=2.54,<3` | `nl2llm`, `nl2sql`, `nl2bn`, and the five `semantic_*` operators |
| `openai` | `openai>=2.54,<3` | `OpenAIPlanGenerator` |
| `dev` | `numpy`, `scikit-learn`, `tenacity<10`, `diskcache<6`, `openai>=2.54,<3`, `pytest`, `pytest-asyncio`, `pytest-recording`, `pytest-cov`, `ruff==0.17.3`, `pyright==1.1.414`, `build`, `twine` | running the tests, the linters, and the build |

The package bounds `jsonpath-ng` below 2, `tenacity` below 10, and `diskcache` below 6 without adding minimum versions. `blue-data` retains its `>=1.0.0` minimum and adds `<2`.

Both `openai` and `llm` require `openai>=2.54,<3`; `openai` leaves out LiteLLM. Other Blue packages declare their own extras.

Prompt rendering uses one standard-library dollar-placeholder pass and requires no direct Jinja2 dependency.

`dev` leaves out LiteLLM, SQL drivers, the CLI/MCP packages, and sentence-transformers. Deterministic operator tests use stubs from `lib/tests/stubs/`; cases that require a genuine optional package skip individually with a reason when it is absent. Tests that use installed packages also run separately, as shown below. Both runs are offline and need no provider key or model download.

The base install carries all 33 operator cards, so discovery, resolution, and pipeline construction work without any extra.
An operator whose extra is missing does not raise on import; its `run()` call returns `[[]]` with an `EXECUTION_FAILED` record in the execution metadata.
[guide.md](guide.md) shows what that looks like.

`sentence-transformers` pulls a deep dependency tree and is the slowest extra to install.
Install `vector` only when you need embedding generation or search; `vector_similarity` over embeddings you already have needs nothing beyond `numpy`.

## Path 2: built wheel

Install the `build` frontend (also included in `dev`) for all three builds. The backend requirements and runtime dependencies still need a configured package index or wheelhouse. Run these commands from the directory containing both checkouts.
`lib/scripts/build.sh` clears the component's `build/` and `dist/`, runs `python -m build`, then checks the wheel.
It writes `blue_data_ops-1.0.0-py3-none-any.whl` and `blue_data_ops-1.0.0.tar.gz` into `lib/dist/`.
The check compares the wheel's package files with the `src/` working tree. It runs in the build and publish wrappers; a direct `python -m build` neither cleans nor invokes it.

```bash
python -m pip install build
python -m pip install ./blue-data/lib
cd blue-data-ops
(cd lib && ./scripts/build.sh)
python -m pip install "./lib/dist/blue_data_ops-1.0.0-py3-none-any.whl[ml,vector,llm]"
```

To install locally built interface wheels too, stay at the `blue-data-ops` repository root:

```bash
(cd platform/ops-mcp && ./scripts/build.sh)
python -m pip install ./platform/ops-mcp/dist/blue_data_ops_mcp-1.0.0-py3-none-any.whl
(cd platform/ops-cli && ./scripts/build.sh)
python -m pip install ./platform/ops-cli/dist/blue_data_ops_cli-1.0.0-py3-none-any.whl
```

A wheel installs the importable package and its resources: the operator implementations, the `operator_skills/` resource packages, the plan JSON schemas, and `py.typed`.
It does not install the top-level documentation files.
[`lib/README.md`](../lib/README.md) reaches you through distribution metadata, and [`lib/OPERATORS.md`](../lib/OPERATORS.md) and [`lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md) are in the checkout and the source distribution.
Extract the matching sdist if you need those two next to a wheel install.
The [examples](../examples/README.md) are in the checkout only: they sit above the packaged directory, so no wheel or source distribution carries them.

## Path 3: released artifact

If your artifact index is configured separately, install the published distributions instead of building them.
The index must also provide `blue-data>=1.0.0,<2`.

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==1.0.0" \
  "blue-data-ops-mcp==1.0.0" \
  "blue-data-ops-cli==1.0.0"
```

MCP wheel installs also need `blue-data[server]>=1.0.0,<2`; install it from a compatible
source with `[server]` or from the configured index.

## The MCP adapter

Install the core first, then the adapter.
From the repository root:

```bash
python -m pip install "../blue-data/lib[server]"
python -m pip install "./lib[ml,vector,llm]"
python -m pip install ./platform/ops-mcp
```

`platform/ops-mcp/scripts/install.sh` runs those three steps through the library's own installer, and adds the dev extras on top.

The adapter also requires `blue-data[server]>=1.0.0,<2` for the shared HTTP guards and requires `mcp>=1.28.1,<2` and `pydantic>=2.11,<3` on top of the core's dependencies.
It serves 33 primary tools, the same selection the core's `active_registry()` returns, each named `ops_` plus its operator name.
Installing it puts one command on `PATH`, `blue-data-ops-mcp`, which serves on the loopback defaults; [mcp.md](mcp.md) covers the rest.

## The `blue-ops` command

Install the core first, then the command.
From the repository root:

```bash
python -m pip install ../blue-data/lib
python -m pip install "./lib[ml,vector,llm]"
python -m pip install ./platform/ops-cli
```

`platform/ops-cli/scripts/install.sh` runs those three steps through the library's own installer, and adds the dev extras on top.
The package pins the core at `blue-data-ops[ml,vector,llm]==1.0.0`, so the three extras arrive with it whether or not the second command above named them.
The core `llm` extra already installs `openai>=2.54,<3` for `blue-ops pipeline add --planner openai`; the CLI's explicit `openai` extra remains available. `metadata inspect` reports module importability, not which extras were requested or whether an installed version is certified.

Installing it puts one command on `PATH`, `blue-ops`.
Confirm it, and see what the install resolved to:

```bash
blue-ops metadata inspect
```

[cli.md](cli.md) covers the command tree, the configuration tiers, the output formats, and the exit codes.

HTTP defaults to `127.0.0.1:8010/mcp` and denies requests without the configured
`BLUE_DATA_OPS_MCP_KEY`. See [HTTP configuration and mounting](mcp.md#http-authentication-and-bind-settings)
for both transports, bind overrides, the deliberate no-key opt-out and lifespan handling.

## Provider credentials

The LLM-backed operators resolve a provider client when they are called, and `OpenAIPlanGenerator` constructs one at first use.
Supply the credential through the provider's own environment variable rather than through a call argument.
`<your-key>` is a placeholder for your own key, which belongs in the environment and not in a committed file.

```bash
export OPENAI_API_KEY="<your-key>"
```

The default model is `gpt-6-luna`, selected by the `openai.model` call property.
Nothing else in the package reads a credential: the record transforms, the registry-backed operations, discovery, the executor, and the rule-based planner all run offline.
For another operator provider, set `BLUE_DATA_LLM_PROVIDER` and its credential in
the process environment. See the [Anthropic example and planner boundary](llm-settings.md#choosing-a-model-for-an-llm-operator).

## Confirming an install

```bash
python -c "from importlib.metadata import version; print(version('blue-data-ops'))"
python -c "from blue_data_ops.operators import active_registry; print(len(active_registry().list_cards()))"
```

The first prints the distribution version, `1.0.0`.
The second prints `33`, the number of active operator cards.
Those numbers move independently: an operator card carries its own version. Of the 33 active cards, twelve are at `@2.0.0`, twenty at `@3.0.0`, and `nl2sql` at `@4.0.0`.

## Running the tests

With the `dev` extra installed, from `lib/`:

```bash
python -m pytest
```

To run the tests that need LiteLLM, SQL drivers and the CLI/MCP packages, install them from the repository root and run the same library suite:

```bash
python -m pip install "./lib[dev,llm]" psycopg2-binary mysql-connector-python \
  "../blue-data/lib[server]" "./platform/ops-cli[dev]" "./platform/ops-mcp[dev]"
(cd lib && python -m pytest)
```

With these packages installed, their integration tests run; the skip report names anything still missing. Four response-cache tests also need `blue-data-llm-source`: with its checkout under the same parent directory, also run `python -m pip install ../blue-data-llm-source/lib`. Two Bayesian-network tests need the `bn` extra of `blue-data`: `python -m pip install "../blue-data/lib[bn,server]"`. Native-extension cases still require a compatible native build. The CLI's core pin installs the `vector` extra, so this profile includes `sentence-transformers`; deterministic vector tests still use the stub and download no model.

Each interface package has its own suite.
From `platform/ops-mcp/` and from `platform/ops-cli/`:

```bash
python -m pytest
```

After only one package's install script, the tests that also drive the other interface skip with `optional integration blue_data_ops_cli is not installed` (MCP suite) or `optional integration blue_data_ops_mcp is not installed` (CLI suite). The profile above installs both, so they run there.

All three configurations set `asyncio_mode = "auto"` and report coverage on `src`.
Ruff and Pyright read their settings from the same `pyproject.toml`; run them from `lib/`, `platform/ops-cli/` or `platform/ops-mcp/` with the environment activated:

```bash
python -m ruff format --check .
python -m ruff check .
python -m pyright
```

## Next steps

- [quickstart.md](quickstart.md) — five minutes from an install to a running pipeline
- [features.md](features.md) — what the library can do, with a short example per feature
- [guide.md](guide.md) — the task-by-task walkthrough
- [cli.md](cli.md) — the same operators from a shell
- [../examples/README.md](../examples/README.md) — which scripts need which extra, and which need a credential

## Python 3.15 compatibility wheels (historical)

Python 3.15 is outside the declared range and pip refuses the install. The complete [historical compatibility-wheel recipe](history/python315-compatibility-wheels.md) records the earlier builds, dependency profile, platform limits and scripts.

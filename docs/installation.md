# Installation

Every supported way to install the three distributions in this repository, and what each one gives you.
[`lib/README.md`](../lib/README.md) is the package README and stays the source of truth for the library's own requirements and minimal usage; this page covers all three packages and the paths between them.

## Packages

| Package | Version | Path | Depends on |
|---|---|---|---|
| `blue-data-ops` | `1.0.0` | [`lib/`](../lib/README.md) | Python >= 3.11, `blue-data>=1.0.0` |
| `blue-data-ops-mcp` | `1.0.0` | [`platform/ops-mcp/`](../platform/ops-mcp/README.md) | Python >= 3.11, `blue-data-ops==1.0.0` |
| `blue-data-ops-cli` | `1.0.0` | [`platform/ops-cli/`](../platform/ops-cli/README.md) | Python >= 3.11, `blue-data-ops[ml,vector,llm]==1.0.0`, `click>=8.0`, `rich>=13.0` |

Install `blue-data-ops` first.
Both interface packages pin it exactly, so their versions move with it.

Each package carries `scripts/install.sh`, which runs the `pip` commands below in the right order and resolves `blue-data` from the sibling checkout.
The paths below are those commands spelled out, for an install that is not a source checkout or a `blue-data` that lives somewhere else.

## Requirements

- Python 3.12 recommended; release verification covers Python 3.11 and 3.12.
- `blue-data` 1.0.0 or later. The library imports it eagerly, so it must be importable before `blue_data_ops` is.
- For a source checkout, `blue-data` and `blue-data-ops` under the same parent directory:

```text
workspace/
├── blue-data/
└── blue-data-ops/
```

The core runtime dependencies are `blue-data>=1.0.0`, `pydantic>=2`, `jsonmerge==1.9.2`, `jsonpath-ng`, and `tenacity`.
Everything heavier sits behind an extra.
Editable installs also need the build requirements declared by each package, including `setuptools>=68` and `wheel`. Configure a package index or provide a wheelhouse containing these and the runtime dependencies before installing in a fresh environment.

Python 3.11 and 3.12 are the standard release test interpreters, with 3.12 recommended. Regular CPython 3.15 on macOS ARM64 uses the compatibility-wheel installation below. Other platforms and free-threaded Python 3.15 have not been verified.

Select a source whose metadata satisfies blue-data 1.0.0 or later. The verified 1.0 source
includes `blue_data.server` and the `server` extra; the 0.1.0 development source cannot
satisfy this release. The installers validate the selected metadata and ask pip to resolve
the source and floor together. Set `BLUE_DATA_PATH` to a compatible `lib` directory and
`PYTHON` to the intended interpreter when using `scripts/install.sh`. MCP additionally
validates and installs that same source's `[server]` extra. CLI alone does not need it.

All three distributions in this checkout declare 1.0.0. If an environment already contains
a numerically higher core version, select `==1.0.0` explicitly; an unqualified upgrade may
retain or choose the higher version. Before publishing, check that all three 1.0.0
distribution names are available on the intended package index. Published versions are
immutable; resolve any version conflict before uploading.

## Path 1: editable source install

Run these from the parent directory that holds both checkouts.

Select Python 3.12 (or the supported minimum, 3.11), then create and activate a standard virtual environment:

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

With either environment active, install the two packages:

```bash
python -m pip install -e ./blue-data/lib "blue-data>=1.0.0"
python -m pip install -e ./blue-data-ops/lib "blue-data-ops==1.0.0"
```

Installation, runtime use, and pytest work in either environment. The repository's Pyright configuration still looks for `lib/.venv`, so use the standard virtual-environment path when running the Pyright check.

Add the extras you need in the same command:

```bash
python -m pip install -e "./blue-data-ops/lib[ml,vector,llm]" "blue-data-ops==1.0.0"
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

Jinja2 remains in the compatibility bundle; prompt rendering uses one standard-library dollar-placeholder pass.

`dev` deliberately leaves out `litellm` and `sentence-transformers`.
The test suite substitutes deterministic stubs for those two from `lib/tests/stubs/`, so the default test run needs neither the download nor a provider.
Install `llm` or `vector` alongside `dev` when you want to exercise the real libraries.

The base install carries all 33 operator cards, so discovery, resolution, and pipeline construction work without any extra.
An operator whose extra is missing does not raise on import; its `run()` call returns `[[]]` with an `EXECUTION_FAILED` record in the execution metadata.
[guide.md](guide.md) shows what that looks like.

`sentence-transformers` pulls a deep dependency tree and is the slowest extra to install.
Install `vector` only when you need embedding generation or search; `vector_similarity` over embeddings you already have needs nothing beyond `numpy`.

## Path 2: built wheel

Build with the `dev` extra installed. Run these commands from the directory containing both checkouts.
`lib/scripts/build.sh` clears the component's `build/` and `dist/`, runs `python -m build`, then checks the wheel.
It writes `blue_data_ops-1.0.0-py3-none-any.whl` and `blue_data_ops-1.0.0.tar.gz` into `lib/dist/`.
The core checker expects `.py`, `.json`, `.md` and `py.typed` files from the `src/` working tree, excluding `__pycache__`.
It examines every ZIP member, rejects duplicate or noncanonical names, outside members and undeclared package files of any suffix, and compares expected file bytes.
Package directory records must be parents of expected files; current dist-info directory records must be parents of actual metadata files.
The adapters also reject noncanonical names before their existing membership checks.
The check runs in the build and publish wrappers; a direct `python -m build` neither cleans nor invokes it.
The guard compares with the working tree rather than Git HEAD and does not validate dist-info contents, RECORD or entry points.
It adds no general sdist-contamination guarantee and does not clear `*.egg-info`.
Wheel lookup and the metadata prefix assume the version in `pyproject.toml` is already canonical.

```bash
python -m pip install ./blue-data/lib "blue-data>=1.0.0"
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
The index must also provide `blue-data>=1.0.0`.

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==1.0.0" \
  "blue-data-ops-mcp==1.0.0" \
  "blue-data-ops-cli==1.0.0"
```

MCP wheel installs also need `blue-data[server]>=1.0.0`; install it from a compatible
source with `[server]` or from the configured index.

## The MCP adapter

Install the core first, then the adapter.
From the repository root:

```bash
python -m pip install "../blue-data/lib[server]" "blue-data[server]>=1.0.0"
python -m pip install "./lib[ml,vector,llm]" "blue-data-ops==1.0.0"
python -m pip install ./platform/ops-mcp "blue-data-ops-mcp==1.0.0"
```

`platform/ops-mcp/scripts/install.sh` runs those three steps through the library's own installer, and adds the dev extras on top.

The adapter also requires `blue-data[server]>=1.0.0` for the shared HTTP guards and requires `mcp>=1.28.1,<2` and `pydantic>=2.11,<3` on top of the core's dependencies.
It serves 33 primary tools, the same selection the core's `active_registry()` returns, each named `ops_` plus its operator name.
Installing it puts one command on `PATH`, `blue-data-ops-mcp`, which serves on the loopback defaults; [mcp.md](mcp.md) covers the rest.

## The `blue-ops` command

Install the core first, then the command.
From the repository root:

```bash
python -m pip install ../blue-data/lib "blue-data>=1.0.0"
python -m pip install "./lib[ml,vector,llm]" "blue-data-ops==1.0.0"
python -m pip install ./platform/ops-cli "blue-data-ops-cli==1.0.0"
```

`platform/ops-cli/scripts/install.sh` runs those three steps through the library's own installer, and adds the dev extras on top.
The package pins the core at `blue-data-ops[ml,vector,llm]==1.0.0`, so the three extras arrive with it whether or not the second command above named them.
Add its own `openai` extra for the provider-backed planner behind `blue-ops pipeline add --planner openai`.

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
Those two numbers move independently: an operator card carries its own version, and twelve of the 33 are active at `@2.0.0` while the other twenty-one are at `@3.0.0`.

## Running the tests

With the `dev` extra installed, from `lib/`:

```bash
python -m pytest
```

Each interface package has its own suite.
From `platform/ops-mcp/` and from `platform/ops-cli/`:

```bash
python -m pytest
```

All three configurations set `asyncio_mode = "auto"` and report coverage on `src`.
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
- [cli.md](cli.md) — the same operators from a shell
- [../examples/README.md](../examples/README.md) — which scripts need which extra, and which need a credential

## Python 3.15 compatibility wheels

Regular CPython 3.15 on macOS ARM64 can use local `fastuuid==0.14.0+blue.1` and `litellm==1.106.5+blue.1` wheels. These builds are selected with `lib/scripts/python315-constraints.txt`; published dependency ranges stay unchanged. These local versions are not on PyPI.

LiteLLM 1.106.5 excludes 3.15 in its metadata and imports the removed `sre_constants` and `sre_parse` modules. `patch-litellm-python315-wheel.py` replaces those two imports with CPython's `re._constants` and `re._parser`, updates the wheel RECORD and restricts this build to Python 3.15. It checks the official wheel's SHA-256 before writing and preserves native code, tags and licenses. The private regex modules need rechecking on future interpreters.

Fastuuid's upstream build uses a PyO3 version whose direct build gate excludes 3.15. `build-python315-wheel.py` enables `abi3-py310` on the genuine native implementation and builds with regular CPython 3.12–3.14. It verifies the pinned upstream source hash and preserves the license. Renaming a CPython-specific binary or changing only Requires-Python cannot provide native compatibility.

To prepare a wheelhouse on macOS ARM64, use new directories and a regular CPython 3.12–3.14 build environment with `maturin==1.15.0`, Cargo >=1.78, Rust and the Xcode command-line tools. The native build needs PyPI/crates.io access unless its inputs are already cached. From the repository root:

```bash
python3.12 lib/scripts/build-python315-wheel.py \
  --sdist /path/to/fastuuid-0.14.0.tar.gz \
  --work-dir .native315 --wheel-dir .wheels315
python3.12 lib/scripts/patch-litellm-python315-wheel.py \
  /path/to/litellm-1.106.5-cp310-abi3-macosx_11_0_arm64.whl \
  --wheel-dir .wheels315
```

The fastuuid source SHA-256 is `178947fc2f995b38497a74172adee64fdeb8b7ec18f2a5934d037641ba265d26`; the official LiteLLM ARM64 wheel SHA-256 is `25d71b305f7d0c67b990f21993f4aa9cd62c5a48ca0400b9b7aba6a355e2ad0b`. Both scripts refuse an unexpected input; the patcher refuses to replace an output wheel. Keep third-party licenses with any distributed wheelhouse.

For a minimal library/LLM installation in a new regular Python 3.15 environment, point `BLUE_DATA_PATH` at a compatible exported blue-data 1.0 library source and `PIP_FIND_LINKS` at the prepared wheelhouse:

```bash
python3.15 -m venv .venv315
source .venv315/bin/activate
export PIP_FIND_LINKS="$PWD/.wheels315"
export PYYAML_FORCE_LIBYAML=0
python -m pip install -e "$BLUE_DATA_PATH" 'blue-data>=1.0.0'
python -m pip install -c lib/scripts/python315-constraints.txt -e './lib[llm]'
python -m pip check
python -c 'import blue_data_ops, litellm, fastuuid; print("imports OK")'
```

PyYAML 6.0.3 has a supported pure-Python build selected by `PYYAML_FORCE_LIBYAML=0`; its source build needs setuptools and Cython and executes upstream packaging code. The tested route uses that implementation, without the optional LibYAML accelerator. Keep the constraints and wheelhouse when adding packages to this environment. Resolve the complete dependency closure rather than using `--no-deps` or changing only package metadata.

To install the CLI and MCP adapters in that environment, include the SDK's server extra and the CLI's ML/vector dependencies:

```bash
python -m pip install -e "${BLUE_DATA_PATH}[server]"
python -m pip install -c lib/scripts/python315-constraints.txt \
  -e './lib[ml,vector,llm]' -e ./platform/ops-cli -e ./platform/ops-mcp
python -m pip check
blue-ops --version
python -c 'from importlib.metadata import version; print(version("blue-data-ops-mcp"))'
```

The verified dependency profile uses regular CPython 3.15.0 on macOS ARM64, NumPy 2.5.4, SciPy 1.18.1, scikit-learn 1.9.1, sentence-transformers 6.2.0, PyTorch 2.15.0, FastAPI 0.162.0 and MCP 1.30.0, with the compatibility builds above. The current SciPy and PyTorch wheels in this profile target macOS 14 or later. Native imports and small numerical/estimator operations are checked separately from unit tests that replace model downloads and provider responses. No embedding model download is required by those offline tests. A fresh installation can resolve newer dependency versions, so verify its complete closure before substituting them. Linux, Windows, Intel macOS and free-threaded Python remain unverified.

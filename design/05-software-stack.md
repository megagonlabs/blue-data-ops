# blue-data-ops — Software Stack

What the repository is built on: the language floor, the three publishable distributions, every declared dependency, and the tooling that gates a change.
The coding rules those tools enforce are [08-coding-style.md](08-coding-style.md).

---

## Language and runtime

| Concern | Choice |
|---|---|
| Language | Python |
| Minimum version | 3.11 |
| Typing | annotations throughout, `from __future__ import annotations` in every module that declares one, a `py.typed` marker in all three distributions |
| Package manager | pip |
| Project config | `pyproject.toml`, one per distribution |
| Build backend | `setuptools.build_meta` |

Python 3.12 and 3.13 are supported: all three distributions declare `requires-python = ">=3.12,<3.14"`, and 3.12 is the Ruff
`target-version` and the Pyright `pythonVersion`. Adding another version
requires adding it to the supported test matrix and updating
`lib/scripts/check_real_llm_install.py`, which currently rejects earlier versions.

---

## Three distributions

The repository publishes three packages from one source tree.

| Package | Version | Path | Requires |
|---|---|---|---|
| `blue-data-ops` | `1.0.0` | `lib/` | Python >= 3.11 |
| `blue-data-ops-mcp` | `1.0.0` | `platform/ops-mcp/` | Python >= 3.11, `blue-data-ops==1.0.0` |
| `blue-data-ops-cli` | `1.0.0` | `platform/ops-cli/` | Python >= 3.11, `blue-data-ops[ml,vector,llm]==1.0.0` |

### The core carries no server dependency

`blue-data-ops` declares five runtime dependencies; none provides a server, protocol, or transport.

```python
# lib/pyproject.toml
dependencies = [
    "blue-data>=1.0.0",
    "pydantic>=2",
    "jsonmerge==1.9.2",
    "jsonpath-ng",
    "tenacity",
]
```

`mcp` appears in `platform/ops-mcp/pyproject.toml` and nowhere else, and `click` and `rich` appear in `platform/ops-cli/pyproject.toml` and nowhere else.
No module under `lib/src/blue_data_ops/` imports any of them, and no module under `lib/src/` imports a web framework, an ASGI server, an argument parser, or a socket library.
Installing the core without either adapter does not install MCP or CLI dependencies.

Each interface distribution pins the core to an exact version so an environment uses a pair whose result envelope was tested together.
A documentation-only release does not move any version.

### What each distribution ships

| Distribution | Wheel contents | Extra source-distribution contents |
|---|---|---|
| `blue-data-ops` | `blue_data_ops/` including `py.typed`, `plan/_schemas/*.json`, and the `operator_skills/` JSON and Markdown resources | `COMPATIBILITY.md`, `OPERATORS.md`, `scripts/*.py`, `scripts/*.sh`, and three test fixtures named in `MANIFEST.in` |
| `blue-data-ops-mcp` | `blue_data_ops_mcp/` including `py.typed` | — |
| `blue-data-ops-cli` | `blue_data_ops_cli/` including `py.typed` and `profile_spec.json` | — |

The operator resource packages are declared as package data, so a wheel install can still load a skill.
The generated operator reference and the compatibility document are source-distribution files; a wheel exposes `lib/README.md` through distribution metadata and does not install the other top-level files.

---

## Core dependencies

The core has five runtime dependencies.

| Package | Constraint | Why it is a runtime dependency |
|---|---|---|
| `blue-data` | `>=0.1.0` | the data registry the four registry-backed operators plus `nl2sql` and `nl2bn` read through. Imported eagerly, in `data/` only |
| `pydantic` | `>=2` | the lax attribute-type validation that `utils.validate_parameter_type` and `create_pydantic_model` are built on |
| `jsonmerge` | `==1.9.2` | backs the Blue-compatible `merge_json`, pinned exactly because the merge behavior is the compatibility contract |
| `jsonpath-ng` | unpinned | imported directly by `llm/templating` and `utils/json_utils`, so it is declared directly rather than relied on transitively through `blue-data` |
| `tenacity` | unpinned | `llm/client` imports it at module import time for its retry decorator, which puts it below the `llm` extra |

`tenacity` also appears in the `llm` extra.
That duplication is deliberate: the extra names the full set an LLM-backed call needs, and the core declaration is what makes the module importable at all.

### blue-data usage

`data/registry_seam.py` and `data/provider.py` are the only two modules in the package that import `blue_data`.

| Imported name | Module | Role |
|---|---|---|
| `DataRegistry` | `blue_data.registry.data_registry` | the registry the seam wraps and the default provider constructs |
| `DataSource` | `blue_data.source.source` | the type `RegistrySeam.register_source()` accepts |

The seam calls a fixed set of registry methods and nothing else: `create_source_database`, `create_source_database_collection_entity`, `set_source_database_description`, `set_source_database_collection_entity_description`, `set_record_data`, `get_record`, `get_source_properties`, `list_collection_entities`, `list_entity_attributes`, `connect_source`, `register_source`, `execute_query`, `get_data_source_schema`, `search_records`, `search_records_hierarchical`, and `build_index`.

`blue-data` ships no `py.typed`, so its imports are the package's one untyped-library boundary.
The seam holds a single `Any`-typed delegate attribute and crosses that boundary once, which is why unknown member types stop in `data/` rather than spreading into every caller.

Concrete sources — SQLite, in-memory JSON, and the rest — come from `blue-data` and are the caller's choice.
This package neither imports nor recommends one.

---

## Optional extras

Every extra except `tenacity` is a lazy import; `llm/client.py` imports `tenacity` at module import time, which is why it is a core dependency rather than only an `llm` one.
The module that needs a heavy dependency imports it inside the function that uses it, so installing the core without the extra keeps `import blue_data_ops` working and turns a missing dependency into an error record at call time.

| Extra | Packages | Operators and features it enables |
|---|---|---|
| `ml` | `numpy`, `scikit-learn` | `classify`, `cluster`, `sklearn_estimator` |
| `vector` | `numpy`, `sentence-transformers` | `vector_embed`, `vector_search`, `vector_similarity` |
| `llm` | `litellm>=1.98,<2`, `tenacity`, `diskcache`, `jinja2` | `nl2llm`, `nl2sql`, `nl2bn`, and the five `semantic_*` operators |
| `openai` | `openai>=2.54,<3` | `OpenAIPlanGenerator` |
| `dev` | `ml` and `openai`, plus `tenacity`, `diskcache` and `jinja2` from `llm`, and the test, lint, type-check and build tools. It does not pull `litellm` or `sentence-transformers`, so add `llm` or `vector` to exercise those operators | working on the package |

Two notes on the boundaries.

`sentence-transformers` is needed only when text has to be embedded.
`vector_similarity` accepts an omitted `fields` attribute when both inputs already carry embeddings, and that path needs NumPy and nothing more.

The `openai` extra is bounded to the 2.x Responses API surface the plan generator was written against.
It is a planner-only seam: nothing else in the package imports the SDK, and the LLM-backed operators go through LiteLLM instead.

### Provider libraries

| Package | Constraint | Imported from | Import site |
|---|---|---|---|
| `litellm` | `>=1.98,<2` | `llm/client.py` | inside `_call_provider`, `_acall_provider`, and the cost helpers |
| `diskcache` | unpinned | `llm/client.py` | inside `_cache_lookup`, only when `llm.cache` is set |
| `jinja2` | unpinned | compatibility bundle | renderer does not import it |
| `numpy` | unpinned | the ML and vector operators, `semantic_join`, and their outcome variants | inside the executing method, via `importlib.import_module` |
| `scikit-learn` | unpinned | `classify`, `cluster`, `sklearn_estimator` | inside the executing method, via `importlib.import_module` |
| `sentence-transformers` | unpinned | the vector operators, `semantic_join`, and their outcome variants | inside the model loader, via `importlib.import_module` |
| `openai` | `>=2.54,<3` | `plan/openai_generator.py` | inside `_resolve_client`, only when no client was injected |

LiteLLM is the provider abstraction for operator-level calls, which keeps those operators provider-agnostic and injectable through `properties["llm_client"]`.
The model is chosen per call through properties, defaulting to `openai.model: gpt-6-luna`.
Credentials are read by the provider library from its own environment variables; this package neither reads nor stores one.

---

## MCP adapter stack

| Concern | Choice |
|---|---|
| Protocol library | `mcp`, bounded `>=1.28.1,<2` |
| Server class | `mcp.server.fastmcp.FastMCP` |
| Transport | streamable HTTP, stateful, default `127.0.0.1:8010/mcp` |
| Result modelling | `pydantic`, pinned `>=2.11,<3` |
| Core pin | `blue-data-ops==1.0.0` |

The adapter's own Pydantic floor is higher than the core's because it declares response models with `ConfigDict(extra="forbid")` and a JSON-schema annotation on the attributes parameter.
`RunResult`, `ExecMetaModel`, and `ErrorRecordModel` are the three models, and together they are the wire contract.

`create_server()` and `serve()` both accept `host`, `port`, and `path`.
The loopback default is a deliberate starting point rather than a recommendation to change: exposing the server beyond loopback is a decision the deployment makes with its own review.

---

## Tooling

| Concern | Tool | Config |
|---|---|---|
| Lint and import order | Ruff (`E`, `F`, `I`, `UP`), line length 100 | `lib/pyproject.toml`, `platform/ops-mcp/pyproject.toml`, `platform/ops-cli/pyproject.toml` |
| Type check | Pyright, strict | the same three files |
| Tests | pytest, `asyncio_mode = "auto"`, coverage on `src` | the same three files |
| Build | `setuptools>=68` + `wheel`, `python -m build` | the same three files |
| Lint scope outside the packages | Ruff, from the repository root | `ruff.toml`, which adds no rules: it extends `lib/pyproject.toml` and sets `src = ["lib/src"]` |
| License | BSD 3-Clause with an attribution and NOTICE requirement | `LICENSE` at the repository root, one copy for all three distributions. No `pyproject.toml` declares it; see the note below |
| Release notes | one entry per released version | `CHANGELOG.md` at the repository root |

Ruff supplies both the linter and the formatter, so a single `line-length = 100` setting governs each.
Pyright runs in strict mode over `src`, with `tests/stubs` on its extra path in the core so the deterministic fakes for LiteLLM and sentence-transformers resolve during analysis.

Two sets of per-file Ruff exceptions exist, both narrow and both carrying their reason in the config file.
Three modules keep their established `str, Enum` public error representation.
Eight operator modules are exempt from the line-length rule because their prompt templates are protocol text whose exact bytes affect provider requests.

There is no CI configuration in the repository, and no `.github/` directory.
The gates above are run locally, and [11-testing-strategy.md](11-testing-strategy.md) records which ones a given change needs.

### Development tools

| Package | Role | Declared in |
|---|---|---|
| `pytest` | test runner | every `dev` extra |
| `pytest-asyncio` | async test support, with `asyncio_mode = "auto"` | every `dev` extra |
| `pytest-cov` | coverage over `src` | every `dev` extra |
| `pytest-recording` | HTTP cassette support, declared for recorded provider work; the tracked suites record nothing today | core `dev` extra |
| `ruff` | lint and import order | every `dev` extra |
| `pyright` | strict type checking | every `dev` extra |
| `build` | wheel and source distribution | every `dev` extra |
| `twine` | distribution checks | every `dev` extra |

---

## Testing

| Concern | Choice |
|---|---|
| Runner | pytest |
| Core scope | `lib/tests/unit/`, mirroring the source packages |
| Adapter scope | `platform/ops-mcp/tests/` |
| CLI scope | `platform/ops-cli/tests/unit/` |
| Coverage | `--cov=src --cov-report=term-missing`, configured in both `pyproject.toml` files |
| Offline guarantee | test doubles and stub modules, no live provider in the default run |

`lib/tests/doubles/` holds in-memory doubles for the data seam: `RegistrySeamDouble` records every call so an operator suite can assert its boundary interactions without a database, and `SQLSourceDouble` stands in for the connect-cursor-commit protocol that `insert_table` drives.
`lib/tests/stubs/` holds deterministic fakes for `litellm` and `sentence_transformers`, resolved by Pyright through `extraPaths` and by pytest through `conftest.py`.
`lib/tests/installed/` holds checks that run against built distributions rather than the source tree.

`lib/tests/unit/test_examples.py` is the runnability gate for the example scripts: it executes the eight offline examples in a subprocess, syntax-checks the four provider-backed ones, and runs the OpenAI planner example in process with deterministic provider doubles.
`test_readme_usage.py` and `test_operator_reference.py` keep the shipped READMEs and the generated reference consistent with the code.

---

## Scripts

Each distribution carries `build.sh`, `install.sh`, and `publish.sh` under its own `scripts/` directory, which is the family's convention.
They wrap `python -m build`, `pip install -e`, and a checked `twine upload`; none of them is installed as a command, and none is a deployment tool.

| Script | Role |
|---|---|
| `build.sh` | clear the component's `build/` and `dist/`, run `python -m build`, then check wheel membership and bytes against `src/` |
| `install.sh` | an editable install of that package and whatever it needs first — the library's resolves `blue-data` from its checkout, and the two service scripts install the library ahead of themselves |
| `publish.sh` | require `TWINE_REPOSITORY_URL`, check the current wheel and source distribution, then upload only those files |

`lib/scripts/` also holds three Python development tools, invoked with `python`.

| Script | Role |
|---|---|
| `generate_operator_reference.py` | regenerates `lib/OPERATORS.md` from the active registry and generator fixtures. `OPERATORS.md` is never hand-edited |
| `check_real_llm_install.py` | confirms LiteLLM resolves to a real installation rather than the test stub, and fails on a Python version below 3.11 |
| `check_wheel_contents.py` | checks every core wheel member against expected source/resources; see [the boundary and limits](12-deployment-ops.md) |

---

## Summary

| Package | Constraint | Source | Role |
|---|---|---|---|
| `blue-data` | `>=0.1.0` | internal | data registry and sources; the one eager external dependency |
| `pydantic` | `>=2` (core), `>=2.11,<3` (adapter) | PyPI | attribute-type validation; MCP result models |
| `jsonmerge` | `==1.9.2` | PyPI | Blue-compatible JSON object merge |
| `jsonpath-ng` | unpinned | PyPI | JSONPath query and set, LLM output extraction |
| `tenacity` | unpinned | PyPI | retry for provider calls; imported at module import time |
| `mcp` | `>=1.28.1,<2` | PyPI | MCP server SDK — `platform/ops-mcp/` only |
| `click` | `>=8.0` | PyPI | command parsing — `platform/ops-cli/` only |
| `rich` | `>=13.0` | PyPI | table and console rendering — `platform/ops-cli/` only |
| `numpy` | unpinned | PyPI | `ml` and `vector` extras |
| `scikit-learn` | unpinned | PyPI | `ml` extra |
| `sentence-transformers` | unpinned | PyPI | `vector` extra, embedding generation only |
| `litellm` | `>=1.98,<2` | PyPI | `llm` extra, provider dispatch for LLM-backed operators |
| `diskcache` | unpinned | PyPI | `llm` extra, opt-in response cache |
| `jinja2` | unpinned | PyPI | retained `llm` compatibility declaration |
| `openai` | `>=2.54,<3` | PyPI | `openai` extra, plan generation only |
| `setuptools` | `>=68` | PyPI | build backend |
| `wheel` | unpinned | PyPI | build requirement |
| `pytest`, `pytest-asyncio`, `pytest-cov` | unpinned | PyPI | test stack |
| `pytest-recording` | unpinned | PyPI | cassette support in the core `dev` extra; no cassettes are tracked |
| `ruff`, `pyright` | unpinned | PyPI | lint, import order, strict type checking |
| `build`, `twine` | unpinned | PyPI | distribution build and checks |

HTTP requires the shared API key by default on both streamable HTTP and SSE.
See the [HTTP bind, authentication and mounted lifespan contract](../docs/mcp.md#http-authentication-and-bind-settings)
for environment overrides, the explicit no-key opt-out and the SDK Host/Origin limits.

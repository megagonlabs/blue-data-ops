# blue-data-ops — Testing Strategy

What each test level in this repository checks, what stands in for the things it will not touch, and how to run any of it.

## Overview

The repository has no CI configuration or `.github/` directory.
Contributors run the commands below locally.
See [12-deployment-ops.md](12-deployment-ops.md) for what that means at release time.

There are three suites, one per distribution, each configured in its own `pyproject.toml` and run from its own directory:

- **`lib/tests/`** — the library suite.
  Fast, offline, and runnable with no credential and no model download.
- **`platform/ops-mcp/tests/`** — the adapter suite.
  Exercises registration, the wire projection, and the MCP protocol itself, over an in-process transport.
- **`platform/ops-cli/tests/unit/`** — the command suite.
  Runs every command through Click's own runner against a throwaway CLI home, and fails the run if the real `~/.blue-ops` appears or disappears.

Within `lib/tests/unit/` the levels are distinguished by what they prove rather than by directory, because they share fixtures and run in one pass.
Section 4 lists them.

---

## 1. Tooling

| Tool | Purpose |
|---|---|
| `pytest` | The runner. Both suites use it directly; there is no `tox.ini`, `noxfile.py`, or `Makefile` |
| `pytest-asyncio` | Async support, with `asyncio_mode = "auto"`, so an `async def test_*` needs no decorator |
| `pytest-cov` | Coverage, wired into `addopts` so it reports on every invocation |
| `pytest-recording` | Declared in the core `dev` extra; no test uses it today, and there are no cassettes in the repository |

All four are `dev` extras of `blue-data-ops`.
The two interface packages' `dev` extras are smaller; of these four they declare `pytest`, `pytest-asyncio`, and `pytest-cov`.

---

## 2. Configuration

From [`lib/pyproject.toml`](../lib/pyproject.toml):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["src", "."]
testpaths = ["tests/unit"]
addopts = "--cov=src --cov-report=term-missing"

[tool.coverage.run]
source = ["src"]
```

Each line is doing a specific job:

| Setting | Effect |
|---|---|
| `pythonpath = ["src", "."]` | Puts both the package and the repository-relative `tests` package on the path, so a bare `pytest` works without exporting `PYTHONPATH` and `tests.doubles`, `tests.stubs`, and `tests.installed` import as packages |
| `testpaths = ["tests/unit"]` | Collection reaches `tests/unit/` only, which keeps `doubles/`, `stubs/`, `fixtures/`, and `installed/` importable but never collected |
| `addopts` | Coverage is on by default rather than opt-in; a bare run prints the missing lines |
| `[tool.coverage.run]` | Measures `src` only, so test and helper lines do not inflate the number |

Coverage is reported on every run, but no minimum threshold is enforced.

[`platform/ops-mcp/pyproject.toml`](../platform/ops-mcp/pyproject.toml) carries the same block with two differences: `testpaths = ["tests"]`, because the adapter's suite has no `unit/` subdirectory to separate, and `pythonpath = ["src", "../../lib/src"]`, which names the library root explicitly rather than leaving it to an install.
[`platform/ops-cli/pyproject.toml`](../platform/ops-cli/pyproject.toml) carries the same two roots and keeps `testpaths = ["tests/unit"]`.

---

## 3. Test Layout

```text
lib/tests/
├── conftest.py                    # loads the sentence-transformers stub before any operator reaches its lazy import
├── unit/
│   ├── operators/                 # one module per operator, plus the cross-version and boundary suites
│   ├── operator_skills/           # loader, index and manifest conformance, disclosure boundary, release gate harness
│   ├── plan/                      # pipeline record, planner stages, executor preflight, data context, generator seam
│   ├── data/                      # the registry seam and provider, against real blue-data sources
│   ├── llm/                       # client, templating, provider resolution, usage and cost accounting
│   ├── utils/                     # type parsing, JSON merge and query, UUID and string helpers
│   ├── test_examples.py           # runs offline examples and the double-backed planner example; syntax-checks provider scripts
│   ├── test_operator_reference.py # asserts OPERATORS.md is byte-identical to the generator's output
│   ├── test_readme_usage.py       # executes the marked code fences in the shipped READMEs
│   └── test_deprecation.py        # the retained warning category and the absence of the removed surfaces
├── doubles/
│   └── data.py                    # RegistrySeamDouble and SQLSourceDouble, recording every boundary call
├── stubs/
│   ├── litellm/                   # deterministic completion stand-in that never calls a network
│   └── sentence_transformers/     # deterministic encoder stand-in that never downloads a model
├── fixtures/                      # JSON reference documents and digest-pinned generator inputs
└── installed/
    ├── operator_skill_release_gate.py    # wheel metadata, resource index, and digest checks over built artifacts
    ├── operator_skill_owner_checks.py    # executes the example pages inside a resource package
    └── operator_skill_disclosure.py      # audits which resource files an import path actually opens

platform/ops-mcp/tests/
├── conftest.py                    # module-scoped sentence-transformers stand-in for this suite
├── test_registration.py           # the operator selections, snapshot binding, and what a bad selection does
├── test_schema.py                 # the input and output schema projected for each tool
├── test_invocation.py             # direct calls and protocol calls must agree, including on failure
├── test_protocol.py               # session lifecycle, concurrency, cancellation, malformed requests
└── test_portability.py            # distribution metadata, the public surface, and the adapter's import boundaries

platform/ops-cli/tests/unit/
├── conftest.py                    # a throwaway CLI home, the Click runner, and the library seams
├── test_surface.py                # the command tree, the shared options, and every format over every result command
├── test_help.py                   # help text for the root, each component, and each command
├── test_non_flat_surface.py       # that no command is reachable outside its component
├── test_formats.py                # table, json and nl over one command each, and the JSON payload keys
├── test_errors.py                 # the ten exit codes and the one-line stderr shape
├── test_catalog.py                # catalog list, inspect and select, and the refusal of `raw`
├── test_operator.py               # operator list, search, inspect and run
├── test_resource.py               # operator resource list, inspect and export, against the real registry
├── test_pipeline.py               # pipeline add, import, export, list, inspect, remove and run
├── test_profile.py                # profile add, remove, list, config, inspect and select
├── test_configstore.py            # the profile store: atomic writes, modes, symlinks, blank values
├── test_meta_parity.py            # that metadata inspect agrees with the installed distributions
├── test_registry_wiring.py        # the blue-data symbols this package depends on, which the checker cannot see
├── test_secret_canary.py          # sentinel values shaped like key material, looked for in every output channel
└── test_readme.py                 # every command the package README documents, run against a throwaway home
```

`tests/unit/` mirrors `src/blue_data_ops/` package for package, so the tests for a module are where the module is.
Each mirrored subdirectory except `utils/` carries an `__init__.py`, which keeps its shared helper modules importable as `tests.unit.<package>.<helper>` and keeps identically-named files in sibling directories from colliding at collection.

Helper modules inside a test directory take the `_` prefix — `_semantic_test_helpers.py`, `_registry_catalog_expectations.py`, `_data_context_helpers.py` — and are imported relatively by the tests beside them.
Those relative imports are the one place in the repository where they appear; the source packages use absolute imports only.

---

## 4. Test Levels

| Level | Where | What it proves |
|---|---|---|
| Operator behavior | `unit/operators/test_<operator>.py` | One operator's transform, validation, defaults, and empty-input handling, against literal record groups |
| Cross-version contract | `unit/operators/test_v2_*.py`, `test_v3_*.py` | A card resolved at `@2.0.0` still behaves as it did, and a card at `@3.0.0` produces the outcome shape it claims |
| Registry and catalog | `unit/operators/test_registry.py`, `test_v3_catalog.py` | Immutable registration, exact resolution with no latest fallback, and the composition of each registry view |
| Import boundaries | `unit/operators/test_portability.py` | `blue` is imported nowhere, `blue_data` is imported only inside `data/`, and `select_operator.py` reaches neither |
| Optional dependencies | `unit/operators/test_heavy_dependencies.py` | The declared extras match what the operators actually reach for, and a guard path resolves no backend |
| Resource packages | `unit/operator_skills/` | Index and manifest conformance, digest verification, and that an ineligible card discloses nothing |
| Planning and execution | `unit/plan/` | Graph validation, executor preflight, planner stage order, and the admission rules on a generated plan |
| Documentation | `unit/test_readme_usage.py`, `test_operator_reference.py`, `test_examples.py` | Shipped prose and shipped scripts still match the code — see section 7 |
| Built artifacts | `unit/operator_skills/test_release_gate.py` and friends, over `tests/installed/` | A wheel carries the resource packages it claims, at the digests it claims — see section 8 |
| Adapter | `platform/ops-mcp/tests/` | Tool registration, schema projection, and that a protocol call and a direct call return the same thing |

The import-boundary tests enforce an architecture constraint rather than runtime behavior.
`test_portability.py` parses every module in the installed package with `ast` and rejects disallowed import roots, preserving `data/` as the single `blue-data` boundary.

---

## 5. Doubles, Stubs, and Fixtures

The tests use three kinds of stand-in.

**Doubles** replace a collaborator whose real behavior is not what the test is about.
`tests/doubles/data.py` provides `RegistrySeamDouble`, which implements the data seam's surface and records every call so an operator test can assert on its boundary interactions offline, and `SQLSourceDouble`, which stands in for the returned SQL source's connect, cursor, `executemany`, commit, and disconnect sequence.
The cursor double reproduces one sqlite3 detail on purpose: `rowcount` reflects the last `executemany`, not a running total.

**Stubs** replace an optional heavy dependency that is not installed.
`tests/stubs/litellm/` returns a deterministic completion derived from the prompt and never touches a network, and exposes a `fail_next` list that a test pushes an exception onto to simulate a provider failure.
`tests/stubs/sentence_transformers/` returns an embedding derived from a SHA-256 digest of the input text, so similarity results are stable and no model is ever downloaded.

The two stubs reach the test run by different routes.
`lib/tests/conftest.py` imports the sentence-transformers stub and installs it into `sys.modules` before collection, so an operator's lazy `import_module("sentence_transformers")` finds it.
`litellm` is found through the `tests/stubs` entry that the same `conftest.py` puts on `sys.path`.
Pyright resolves both through `extraPaths = ["src", "tests/stubs"]`.

`lib/tests/conftest.py` is short enough to read whole, and it is the entire shared setup for the library suite:

```python
from __future__ import annotations

import sys
from pathlib import Path

from tests.stubs import sentence_transformers as sentence_transformers_stub

# sentence-transformers is intentionally absent from the development dependencies;
# load the deterministic test stub before an operator reaches its lazy model import.
sys.path.insert(0, str(Path(__file__).parent / "stubs"))
sys.modules["sentence_transformers"] = sentence_transformers_stub

# Shared fixtures for the blue-data-ops test suite belong here; operator-specific
# fixtures stay beside their tests.
```

In practice almost every fixture is local: a test module defines its own `op()` and its own reset hook rather than reaching for a repository-wide one.
The adapter suite's `conftest.py` follows the same idea with its own inline stand-in rather than importing the library's.

**Fixtures**, in the data sense, are the JSON documents under `tests/fixtures/`.
Two are generator inputs whose SHA-256 digests are asserted by `test_operator_reference.py`, so the suite detects any change to the input used for the generated operator reference.
The rest are recorded catalogs and outcome tables that the cross-version suites compare against.

`numpy` and `scikit-learn` get no stub.
Where a test needs them it declares that with `pytest.importorskip`, and where an operator needs them and cannot find them the expected result is an `EXECUTION_FAILED` record rather than a skip.

---

## 6. Network, Credentials, and Skipping

No test reaches an external service.
There is no cassette tier, no `@pytest.mark.vcr`, and no recorded HTTP interaction anywhere in the repository, which is what makes a bare `pytest` safe with no `OPENAI_API_KEY` set.

Two tests exercise network libraries without contacting external services.
`unit/plan/test_openai_generator.py` constructs a real `openai.OpenAI` client whose transport is an `httpx.MockTransport`, so the SDK's own request building and response parsing are exercised while nothing leaves the process.
In the adapter suite, `test_protocol.py` drives the server through the SDK's in-memory session for most cases and through `httpx.ASGITransport` for the malformed-request cases; its one socket call is a deliberate connection to a closed loopback port, proving that an unreachable server surfaces as a transport exception rather than something else.

Skipping is narrow and explicit:

| Mechanism | Used for |
|---|---|
| `pytest.importorskip("blue_data")` at module scope | Suites that need a real `blue-data` registry: `unit/data/`, the registry-backed operators, `test_readme_usage.py` |
| `pytest.importorskip("numpy")` inside a test | The few assertions that need a real array |
| One `pytest.mark.skipif` | The `openai` extra, in `unit/plan/test_openai_generator.py`, guarded on whether the SDK imports |

`parametrize` and the single `skipif` above are the only pytest markers the repository uses.
There are no custom markers, no marker registry, and no `-m` selection to learn.

---

## 7. Documentation Tests

Three modules check the shipped READMEs, generated reference, and examples.

**`test_readme_usage.py`** collects every fence in [`lib/README.md`](../lib/README.md) and [`platform/ops-mcp/README.md`](../platform/ops-mcp/README.md) that carries an HTML marker comment, and executes it:

```markdown
<!-- blue-data-ops-test: registry-roles -->
```

It asserts that every marker in the file matched a fence, so a marker that drifts away from its block fails rather than being skipped silently.
It then runs mutation checks: it edits one line of the registry fence, and the test fails if the edited version still passes.
Beyond the fences, it asserts specific sentences and install commands are present in the shipped READMEs, and it reads the version, Python floor, Ruff target, and Pyright version straight out of `pyproject.toml`.

**`test_operator_reference.py`** re-runs `scripts/generate_operator_reference.py` in process and asserts that the committed `OPERATORS.md` is byte-identical to the result.
The generated file is never hand-edited.
The same module checks that the generator inputs still match their recorded digests, that a modified input document fails validation, and that `--check` reports a stale file without rewriting it.

**`test_examples.py`** runs each offline example script in a subprocess and asserts a zero exit and non-empty output, compiles each provider-backed script, runs the OpenAI planner example in process with deterministic provider doubles, and cross-checks `coverage.json` against the operator IDs the scripts actually name in their source.
It also asserts that the offline and provider-backed lists together account for every runnable script in the tree, so a new example cannot be added without being classified.

These three are the runnability check for [`examples/README.md`](../examples/README.md) and the drift check for the package READMEs.
A change to either that breaks a claim fails the library suite.

---

## 8. Built-Artifact Checks

`lib/tests/installed/` holds three modules that inspect a built or installed artifact rather than the source tree.
None of them is named `test_*`, so pytest never collects them directly; they are libraries with a command-line entry point.

| Module | Checks |
|---|---|
| `operator_skill_release_gate.py` | A core wheel and an adapter wheel together: distribution names and versions, the exact core pin in the adapter's requirements, the resource index, per-file SHA-256 digests, the byte bounds, UTF-8 decodability, and that no archive member is a symlink |
| `operator_skill_owner_checks.py` | The example pages inside a resource package, by extracting and executing their fenced code per declared environment |
| `operator_skill_disclosure.py` | Which resource files an import path actually opens, using an audit hook, so a loader cannot read more than it declares |

Each is driven two ways.
`unit/operator_skills/test_release_gate.py` and its neighbours import them and run them against synthetic wheels built in a `tmp_path`, including deliberately malformed ones, so the checks themselves are tested.
The same modules run by hand against real artifacts:

```bash
cd lib
python -m tests.installed.operator_skill_release_gate \
  --core-wheel dist/blue_data_ops-3.1.0-py3-none-any.whl \
  --mcp-wheel ../platform/ops-mcp/dist/blue_data_ops_mcp-1.0.0-py3-none-any.whl \
  --core-version 3.1.0 \
  --mcp-version 1.0.0 \
  $(python -c 'import json, pathlib
index = json.loads(pathlib.Path("src/blue_data_ops/operator_skills/_index.json").read_text())
for operator_id in sorted(index["packages"], key=str.encode):
    print("--expect-operator-id", operator_id)')
```

`--expect-operator-id` repeats once per resource package the wheel is expected to carry, in byte-sorted order, and the check fails on any difference in either direction — which is why the command reads the expected set out of the source index rather than hardcoding it.
Substitute the two wheel paths that `python -m build` produced.

Run this pre-publish check manually against the built artifacts.

---

## 9. Running the Suites

The library suite, from `lib/`, with the `dev` extra and `blue-data` installed:

```bash
cd lib
python -m pytest
```

One directory, one module, or one test:

```bash
cd lib
python -m pytest tests/unit/operators/
python -m pytest tests/unit/test_examples.py
python -m pytest tests/unit/operators/test_select.py::test_invoke_valid
```

Without the coverage report, when the missing-line table is noise:

```bash
cd lib
python -m pytest --no-cov
```

The adapter suite and the command suite, each from its own directory and its own environment:

```bash
cd platform/ops-mcp
python -m pytest
```

```bash
cd platform/ops-cli
python -m pytest
```

`requires-python = ">=3.11"` sets the floor and declares no ceiling, so run each suite on the interpreters the change is meant to support.
In practice that is 3.11 and 3.12.

---

## 10. What Is Not Covered

The suite does not cover the following areas.

- **Nothing is automated.**
  With no CI, a passing suite means someone ran it on one machine with one set of installed versions.
- **No live provider is ever called.**
  Three provider-backed examples are compiled only; the OpenAI planner example runs against deterministic provider doubles.
  No test asserts anything about a real model's output.
  A prompt change that degrades a real response is invisible to this suite.
- **No replay tier exists.**
  `pytest-recording` is a declared dependency with no cassettes behind it, so there is nothing between the deterministic stubs and a live call.
- **No performance or load coverage.**
  Timeout containment is tested; throughput, memory, and the cost of a large record bundle are not.
- **The `blue-data` integration is exercised through in-memory and temporary SQLite sources only.**
  Those are real `blue-data` sources rather than doubles, and the seam tests do run against them, but no test runs against a server-backed source.
- **Coverage is reported, never enforced.**
  No threshold exists in any package.

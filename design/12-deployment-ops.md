# blue-data-ops — Deployment / Ops

How the two distributions are versioned, built, installed, and operated, and which parts of that are done by hand.

## Overview

This repository ships two Python distributions and nothing else.
There is no container image, no service manifest, and no pipeline.
Both packages are installed into a Python process — a caller's process for the library, and one the operator starts for the MCP adapter, which serves streamable HTTP on a loopback address by default.

Two absences shape everything below, and both are stated once here rather than repeated in every section:

- **There is no CI.**
  The repository has no `.github/` directory and no CI configuration of any kind.
  Every check, build, and publish step is a command someone runs.
- **There are no shell scripts.**
  No `install.sh`, `build.sh`, `publish.sh`, or `deploy.sh` exists anywhere in the tree.
  The only scripts are the two Python maintenance scripts in `lib/scripts/`, described in [07-repo-organization.md](07-repo-organization.md).

---

## 1. Versioning

Three version axes run independently, and conflating them is the usual source of confusion.

| Axis | Where it lives | Moves when |
|---|---|---|
| Distribution version | `version` in each package's `pyproject.toml` | That package's own public surface or behavior changes |
| Operator card version | The `@MAJOR.MINOR.PATCH` half of an exact operator ID | One operator's behavior changes; the previous version stays resolvable |
| Adapter's core pin | `blue-data-ops==<version>` in the adapter's dependencies | The adapter is verified against a new core release |

Each distribution declares its own version and neither reads the other's.
There is no repository-wide version, and no `MAJOR.MINOR.PATCH` for the repository as a whole.

Operator card versions are the axis that matters most in practice.
A card is registered under `name@<MAJOR.MINOR.PATCH>`, registration is immutable — no overwrite and no deregister — and a version is therefore never reused.
That is what lets the history registry keep the 87 cards that earlier releases resolved while the active view offers the 33 a current caller should use.
[`lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md) is the source of truth for which boundary a given change crosses, and [10-data-model.md](10-data-model.md) covers the card record itself.

A change that touches only documentation moves none of the three.
A distribution version bump is a claim about code.

The repository carries no Git tags, so a release is identified by its commit and by the version in the `pyproject.toml` at that commit.

---

## 2. Distributions

| Package | Path | Version | Console script | Runtime dependencies |
|---|---|---|---|---|
| `blue-data-ops` | `lib/` | `3.0.0` | none | `blue-data>=0.1.0`, `pydantic>=2`, `jsonmerge==1.9.2`, `jsonpath-ng`, `tenacity` |
| `blue-data-ops-mcp` | `platform/mcp/` | `0.13.0` | none | `blue-data-ops==3.0.0`, `mcp==1.27.2`, `pydantic>=2.11,<3` |

Each package's own README is the source of truth for installing and using it: [`lib/README.md`](../lib/README.md) and [`platform/mcp/README.md`](../platform/mcp/README.md).

Neither `pyproject.toml` declares `[project.scripts]`, so installing either package adds no command to `PATH`.
The library is imported; the adapter is started from Python.
The absence of a CLI is a standing decision rather than an omission: the library is imported and the adapter is hosted, so a command-line entry point would be a third surface for the operator contract to drift across.

The adapter's pin on the core is exact, not a floor.
That is deliberate: the adapter's tool schemas are a projection of the core's attribute specs, and a core that changed a spec would change the wire contract without the adapter's version moving.
Upgrading the core therefore requires an adapter release, and the pair is verified together.

Both `[project]` blocks are minimal — `name`, `version`, `description`, `readme`, `requires-python`, and `dependencies`.
Neither declares a license, an author, a classifier, or a project URL.
A publishing workflow that needs those fields has to add them.

The core's optional extras:

| Extra | Pulls in | Needed for |
|---|---|---|
| `ml` | `numpy`, `scikit-learn` | `classify`, `cluster`, `sklearn_estimator` |
| `vector` | `numpy`, `sentence-transformers` | the three vector operators |
| `llm` | `litellm>=1.98,<2`, `tenacity`, `diskcache`, `jinja2` | `nl2llm`, `nl2sql`, `nl2bn`, and the `semantic_*` operators |
| `openai` | `openai>=2.54,<3` | `OpenAIPlanGenerator` |
| `dev` | `numpy`, `scikit-learn`, `tenacity`, `diskcache`, `jinja2`, `openai`, `pytest`, `pytest-asyncio`, `pytest-recording`, `pytest-cov`, `ruff`, `pyright`, `build`, `twine` | working on the package |

`dev` is not the union of the other four.
`sentence-transformers` is left out on purpose, so that a development environment cannot accidentally reach a real model download; the test suite substitutes a deterministic stub instead.
Installing `dev` therefore gives a working `ml` and `llm` path but exercises the vector path through that stub.
[11-testing-strategy.md](11-testing-strategy.md) covers how the substitution happens.

The adapter declares one extra, `dev`, holding `build`, `pyright`, `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, and `twine`.

---

## 3. Installing

There is no install script.
Two paths are supported, and [`docs/installation.md`](../docs/installation.md) is the page to send a user to.

A source checkout expects `blue-data` and `blue-data-ops` as siblings under one parent directory, because the core's `blue-data` dependency is resolved from that local path rather than from an index:

```bash
python -m venv blue-data-ops/lib/.venv
source blue-data-ops/lib/.venv/bin/activate
python -m pip install -e ./blue-data/lib
python -m pip install -e "./blue-data-ops/lib[dev]"
```

Against a configured artifact index, install the built distributions instead:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==3.0.0" \
  "blue-data-ops-mcp==0.13.0"
```

That index must also serve `blue-data>=0.1.0`.
`PIP_INDEX_URL` is named in the READMEs as the variable to set; no index URL is configured anywhere in this repository, and none should be committed.

---

## 4. Building

Both packages use the same backend, declared identically:

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"
```

Build each from its own directory, with the `dev` extra installed for `build`:

```bash
cd lib
python -m build

cd ../platform/mcp
python -m build
```

`[tool.setuptools.packages.find] where = ["src"]` is what makes the `src/` layout work, and it is why a wheel contains the package and nothing above it.

**Non-Python files in the wheel** are listed explicitly, because setuptools will not guess:

```toml
[tool.setuptools.package-data]
blue_data_ops = [
    "py.typed",
    "plan/_schemas/*.json",
    "operator_skills/_index.json",
    "operator_skills/*/*/*.json",
    "operator_skills/*/*/*.md",
]
```

Those five patterns are the reason a wheel-only install can still load a resource package and read the packaged plan schema.
Adding a resource directory without adding its pattern here produces a wheel that imports fine and fails at first read, which is exactly the failure the built-artifact checks in [11-testing-strategy.md](11-testing-strategy.md) exist to catch.
The adapter's `package-data` declares `py.typed` alone.

**Files in the source distribution but not the wheel** come from `lib/MANIFEST.in`: `COMPATIBILITY.md`, `OPERATORS.md`, three named test fixtures — two of which are the reference generator's sealed inputs — and `scripts/`.
A source checkout and an extracted source distribution therefore both carry the reference material and the generator; a wheel does not.
[`lib/README.md`](../lib/README.md) states that difference for users and tells a wheel-only reader to fetch the matching source distribution.
The adapter has no `MANIFEST.in`.

A wheel does expose its package README through distribution metadata, which is why [`lib/README.md`](../lib/README.md) links no file that only the source distribution carries.
A test enforces that.

---

## 5. Publishing

`twine` is a `dev` extra of both packages and is the intended upload tool.
Beyond that, publishing is unautomated: there is no publish script, no CI job, and no registry configured in the repository.

The pre-publish sequence, all of it manual:

1. Run both test suites on each supported interpreter, per [11-testing-strategy.md](11-testing-strategy.md).
2. Run `ruff format --check`, `ruff check`, and `pyright` in both package directories, per [08-coding-style.md](08-coding-style.md).
3. Run `cd lib && python scripts/generate_operator_reference.py --check`, so a stale `OPERATORS.md` stops the release instead of shipping.
4. Build both distributions with `python -m build`.
5. Run the built-artifact check over the two wheels together, which verifies the versions, the exact core pin, and every resource package digest.
6. Upload with `twine`, against whichever index the operator is publishing to.

Steps 3 and 5 are specific to this repository.
Neither is wired into `pytest`, so both are easy to skip, and both are worth the two minutes.

---

## 6. Running the MCP Server

The adapter has no entry-point command, so it is started from Python.
`serve()` builds the server and runs it:

```bash
python -c 'from blue_data_ops_mcp import serve; serve()'
```

Equivalently, when the server object is needed first:

```python
from blue_data_ops_mcp import create_server

server = create_server()
server.run(transport="streamable-http")
```

The defaults, from `create_server()`:

| Setting | Default | Note |
|---|---|---|
| Transport | `streamable-http` | Not stdio; the server is an HTTP listener |
| Host | `127.0.0.1` | Loopback. Binding elsewhere is an explicit argument |
| Port | `8000` | |
| Path | `/mcp` | |
| Session state | stateful | `stateless_http=False` |
| Response encoding | SSE rather than plain JSON | `json_response=False` |

Two tests in the adapter suite assert those settings and the transport `serve()` picks, so a default cannot change quietly.
Passing `operator_ids` replaces the default 33-tool selection with an exact pinned subset, and an empty tuple serves nothing.
[`platform/mcp/README.md`](../platform/mcp/README.md) is the source of truth for the adapter's setup, tool contract, and migration notes; [`docs/mcp.md`](../docs/mcp.md) is a synced copy of it.

Operationally this is a supervised process: no health endpoint, no readiness check, and no metrics path exist for a supervisor to poll.
It watches the process and the port.

---

## 7. Configuration

**Neither source tree reads an environment variable.**
There is no `os.environ` or `os.getenv` call anywhere in `lib/src/` or `platform/mcp/src/`.
Every knob is a key in the `properties` mapping passed to a call, which keeps configuration per invocation rather than per process and keeps the library from depending on ambient state.

The keys that matter operationally:

| Key | Effect |
|---|---|
| `execution.timeout_seconds` | A wrapper deadline on one `run()` call; must be a finite number greater than zero. The wrapper never retries, and a breach returns an `OPERATOR_TIMEOUT` record |
| `openai.model` | The model an LLM-backed operator requests |
| `llm.cache` | Enables the on-disk response cache; requires the `llm` extra's `diskcache` |
| `llm.cache_dir` | Where that cache lives, defaulting to `.llm_cache` in the working directory |
| `llm.max_parallel` | Bound on concurrent asynchronous provider calls |
| `llm.rate_limit` | A ceiling in calls per second; the client sleeps to hold the resulting minimum interval |

`llm.cache_dir` is the only path this package writes to on its own initiative, and only when `llm.cache` is set.
Its default, `.llm_cache`, is relative to the process working directory and is not covered by either `.gitignore` in this repository, so a run with caching enabled inside a checkout leaves an untracked directory.
Point it somewhere outside the tree, or add it to the ignore file, before enabling the cache during development.

**Credentials are never read by this package.**
An LLM-backed operator hands its request to LiteLLM, and the plan generator hands its request to the OpenAI SDK; each of those libraries reads its own provider variables, such as `OPENAI_API_KEY`, from the environment.
Nothing here reads, stores, logs, or forwards a key, and no credential should be placed in a `properties` mapping that is serialized into a plan record.

---

## 8. Observability

What exists is per-call and in-process.

| Signal | Where |
|---|---|
| Error records | `ExecMeta.errors` on every `run()` result: category, code, exact operator ID, stage, message, retryability, suggestion |
| Per-call logs and traces | `ExecMeta.logs` and `ExecMeta.traces` on the same result |
| Provider usage | `LLMClient.ledger`, one `UsageRecord` per call, with tokens, cost, latency, and whether the cache answered |
| Python logging | A module-level `logger` from `logging.getLogger(__name__)` in the modules that log, chiefly the registry-backed operators |

The library configures no handler and installs no formatter, which is correct for a library: the host application decides where records go.
A caller that wants operator logs configures the `blue_data_ops` logger itself.

Nothing else is instrumented.
There is no metrics endpoint, no OpenTelemetry dependency, no structured-log formatter, and no trace export.
Cost and latency exist because the LLM client records them per call, not because anything aggregates them.

---

## 9. What Is Not Automated

Collected in one place, because several of these read as oversights when they are current state.

- **No pipeline.**
  No `.github/`, no CI configuration, no verify, build, or publish stage.
  Nothing runs on a push.
- **No `CHANGELOG.md`.**
  Release history lives in the migration sections of [`lib/README.md`](../lib/README.md), in [`lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md), and in [`platform/mcp/README.md`](../platform/mcp/README.md), which carries migration notes for adapter releases back to `0.1.0`.
- **No Git tags.**
  A release is a commit plus the version in that commit's `pyproject.toml`.
- **No container image.**
  No `Dockerfile`, no compose file, no deployment manifest.
- **No install, build, publish, or deploy script.**
  The commands in sections 3, 4, and 5 are the process.
- **No dependency lock file.**
  Version constraints are the only pinning, and two of them are exact by design: `jsonmerge==1.9.2` in the core and `mcp==1.27.2` in the adapter.
- **No process supervision recipe.**
  The MCP server is started by the commands in section 6 and supervised by whatever the operator already uses.

None of this needs to change for the library, which is installed rather than deployed.
It would need to change for anything that runs the MCP adapter as a long-lived service, and that is the point at which the first item on this list stops being acceptable.

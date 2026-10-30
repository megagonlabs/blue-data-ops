# blue-data-ops — Deployment / Ops

How the three distributions are versioned, built, installed, and operated, and which parts of that are done by hand.

## Overview

This repository publishes three Python distributions.
It has no CI, container image, service manifest, or deployment pipeline.
Tests, builds, and publishing are run manually, sometimes through the scripts described below.
All three are installed into a Python process — a caller's process for the library, one the operator starts for the MCP adapter, which serves streamable HTTP on a loopback address by default, and a shell's for the `blue-ops` command.

Each distribution carries `scripts/{build,install,publish}.sh`.
They run the package build, editable install, and checked upload, with sibling-checkout resolution included where needed.
Nothing invokes them automatically, and no `deploy.sh` exists.
`lib/scripts/` also contains the three Python maintenance scripts described in [07-repo-organization.md](07-repo-organization.md).

---

## 1. Versioning

The repository uses three independent version axes.

| Axis | Where it lives | Moves when |
|---|---|---|
| Distribution version | `version` in each package's `pyproject.toml` | That package's own public surface or behavior changes |
| Operator card version | The `@MAJOR.MINOR.PATCH` half of an exact operator ID | One operator's behavior changes; the previous version stays resolvable |
| An interface package's core pin | `blue-data-ops==<version>` in the adapter's or the command's dependencies | That package is verified against a new core release |

Each distribution declares its own version and none reads another's.
There is no repository-wide version, and no `MAJOR.MINOR.PATCH` for the repository as a whole.

A card is registered under `name@<MAJOR.MINOR.PATCH>`, registration is immutable — no overwrite and no deregister — and a version is therefore never reused.
The history registry retains 87 cards from earlier releases, while the active view offers the 33 cards intended for current callers.
[`lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md) is the source of truth for which boundary a given change crosses, and [10-data-model.md](10-data-model.md) covers the card record itself.

A documentation-only change does not move any of the three versions.

The repository carries no Git tags, so a release is identified by its commit and by the version in the `pyproject.toml` at that commit.
[`../CHANGELOG.md`](../CHANGELOG.md) carries one entry per released version and names which of the three distributions moved.

---

## 2. Distributions

| Package | Path | Version | Console script | Runtime dependencies |
|---|---|---|---|---|
| `blue-data-ops` | `lib/` | `1.0.0` | none | `blue-data>=1.0.0`, `pydantic>=2`, `jsonmerge==1.9.2`, `jsonpath-ng`, `tenacity` |
| `blue-data-ops-mcp` | `platform/ops-mcp/` | `1.0.0` | `blue-data-ops-mcp` | `blue-data-ops==1.0.0`, `blue-data[server]>=1.0.0`, `mcp>=1.28.1,<2`, `pydantic>=2.11,<3` |
| `blue-data-ops-cli` | `platform/ops-cli/` | `1.0.0` | `blue-ops` | `blue-data-ops[ml,vector,llm]==1.0.0`, `click>=8.0`, `rich>=13.0` |

Each package's own README is the source of truth for installing and using it: [`lib/README.md`](../lib/README.md), [`platform/ops-mcp/README.md`](../platform/ops-mcp/README.md), and [`platform/ops-cli/README.md`](../platform/ops-cli/README.md).

The core declares no `[project.scripts]`, so installing the library alone adds no command to `PATH`.
Argument parsing and output formatting remain in the interface distributions, and a process that needs only the library installs neither interface.

Each interface package pins the core to an exact version.
The adapter's tool schemas project the core's attribute specs, and the command renders the same schemas.
A core specification change could otherwise alter either interface contract without moving its version.
Upgrading the core therefore requires an interface release, and each pair is verified together.

The three `[project]` blocks are minimal — `name`, `version`, `description`, `readme`, `requires-python`, and `dependencies`.
None declares a license expression, an author, a classifier, or a project URL. Each package has a `LICENSE` in its build root; its wheel carries that text and a `License-File: LICENSE` metadata field.
A publishing workflow that needs a license expression or the other metadata fields has to add them.

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
The command declares the same `dev` extra plus `openai`, which pulls the core's `openai` extra for the provider-backed planner behind `blue-ops pipeline add --planner openai`.

---

## 3. Installing

Two paths are supported, and [`docs/installation.md`](../docs/installation.md) is the page to send a user to.

A source checkout expects `blue-data` and `blue-data-ops` as siblings under one parent directory, because the core's `blue-data` dependency is resolved from that local path rather than from an index.
Each package's `scripts/install.sh` does that resolution: the library's installs `blue-data` from the sibling checkout and then the library, and both interface packages call the library's first, add the three extras their operators need, and then install themselves.

Create and activate either a standard virtual environment:

```bash
python3.12 -m venv blue-data-ops/lib/.venv
source blue-data-ops/lib/.venv/bin/activate
```

or a Conda environment:

```bash
conda create --name blue-data-ops python=3.12 pip
conda activate blue-data-ops
```

Then run the installer with either environment active:

```bash
./blue-data-ops/lib/scripts/install.sh
```

The same thing by hand, which is what to do when `blue-data` is somewhere `BLUE_DATA_PATH` would have to name:

```bash
python -m pip install -e ./blue-data/lib "blue-data>=1.0.0"
python -m pip install -e "./blue-data-ops/lib[dev]" "blue-data-ops==1.0.0"
```

Against a configured artifact index, install the built distributions instead:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==1.0.0" \
  "blue-data-ops-mcp==1.0.0" \
  "blue-data-ops-cli==1.0.0"
```

That index must also serve `blue-data>=1.0.0`.
`PIP_INDEX_URL` is named in the READMEs as the variable to set; no index URL is configured anywhere in this repository, and none should be committed.

---

## 4. Building

All three packages use the same backend, declared identically:

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"
```

Build each from its own directory, with the `dev` extra installed for `build`.
Each package's `scripts/build.sh` clears its own `build/` and `dist/` before running `python -m build` from the package root:

```bash
cd lib
./scripts/build.sh

cd ../platform/ops-mcp
./scripts/build.sh

cd ../ops-cli
./scripts/build.sh
```

The library wrapper checks every wheel member against the expected `.py`, `.json`, `.md` and `py.typed` files in the `src/` working tree, excluding `__pycache__`.
It rejects duplicates, noncanonical names, outside members and undeclared package files of any suffix, and compares expected bytes.
Package directory records must be parents of expected files; current dist-info directory records must be parents of actual metadata files.
All three checkers validate member names before exempting current metadata; adapter membership and directory rules otherwise stay the same.
The core publish wrapper reads pyproject metadata and selects the current pair, then runs the guard before Twine check or upload.
A direct `python -m build --wheel` neither cleans nor runs the guard and can still carry stale files; run the checker or use the release wrapper.
The guard compares with the working tree rather than Git HEAD. Dist-info contents, RECORD and entry points remain unvalidated; this adds no general sdist-contamination guarantee.
Cleanup leaves `*.egg-info` alone. Wheel lookup and the allowed metadata prefix assume a canonical version in `pyproject.toml`.

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
The adapter's `package-data` declares `py.typed` alone, and the command's declares `py.typed` and `profile_spec.json`, which is the configuration parameter list every `blue-ops profile` command reads.

**Files in the source distribution but not the wheel** come from `lib/MANIFEST.in`: `COMPATIBILITY.md`, `OPERATORS.md`, three named test fixtures — two of which are reference-generator inputs — and `scripts/`, with its Python tools and three shell scripts.
A source checkout and an extracted source distribution therefore both carry the reference material and the generator; a wheel does not.
[`lib/README.md`](../lib/README.md) states that difference for users and tells a wheel-only reader to fetch the matching source distribution.
Both interface packages have a `MANIFEST.in` for their shipped source files.

A wheel does expose its package README through distribution metadata, which is why [`lib/README.md`](../lib/README.md) links no file that only the source distribution carries.
A test enforces that.

---

## 5. Publishing

`twine` is a `dev` extra of every package and is the intended upload tool, wrapped by each one's `scripts/publish.sh`.
The repository has no publishing CI job or configured package registry.
Each publish script requires `TWINE_REPOSITORY_URL`, checks the current version's wheel and source distribution with `twine check`, and uploads only those two files.
The library script also runs the wheel guard described above before Twine check and upload.

The pre-publish sequence, all of it manual:

1. Run all three test suites on each supported interpreter, per [11-testing-strategy.md](11-testing-strategy.md).
2. Run `ruff format --check`, `ruff check`, and `pyright` in each package directory, per [08-coding-style.md](08-coding-style.md).
3. Run `cd lib && python scripts/generate_operator_reference.py --check`, so a stale `OPERATORS.md` stops the release instead of shipping.
4. Build each distribution with its `scripts/build.sh`.
5. Run the built-artifact check over the wheels together, which verifies the versions, the exact core pin, and every resource package digest.
6. Add a `CHANGELOG.md` entry naming each distribution whose version moved and what a caller has to do about it.
7. Set `TWINE_REPOSITORY_URL` to the intended index and run `scripts/publish.sh` from each package.

Steps 3 and 5 are specific to this repository and are not part of `pytest`.

---

## 6. Running the MCP Server

The adapter installs one console command, which builds the server and runs it on the loopback defaults:

```bash
blue-data-ops-mcp
```

`blue_data_ops_mcp.main` is the function behind it, and it is `serve()` with those defaults.
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
| Host | `127.0.0.1` | Loopback; environment or explicit argument may override |
| Port | `8010` | `BLUE_DATA_OPS_MCP_PORT` or explicit argument |
| Path | `/mcp` | |
| Session state | stateful | `stateless_http=False` |
| Response encoding | SSE rather than plain JSON | `json_response=False` |

Two tests in the adapter suite assert those settings and the transport `serve()` picks, so a default cannot change quietly.

The MCP adapter serves streamable HTTP; the rest of the Blue Data family speaks stdio.
Long CPU- and provider-bound calls run on worker threads, keeping the event loop responsive while multiple calls remain in flight.
Stateful HTTP sessions use the same cancellation boundary tested with the in-memory transport. With the tested Python MCP 1.30.0, local awaiter cancellation and client-side timeouts do not send `notifications/cancelled`. An explicit notification received after the handler enters `DeploymentRegistry.run()` removes a call still waiting for admission from the queue, and it does not execute. An immediate notification sent before the handler starts can be lost. Active work may finish and persist effects; a code 0 `Request cancelled` response is not proof of non-execution. Check backend effects before retrying a cancelled or timed-out write. Cancellation provides no atomic rollback. Whether a worker can be terminated depends on the product and worker implementation; this product does not promise it. There is no automatic retry.
A client-spawned stdio process would tie the server lifetime to one client and would not preserve the current cross-session concurrency model.
Changing transports would break existing deployments. The adapter has served streamable HTTP since `0.1.0`.

Passing `operator_ids` replaces the default 33-tool selection with an exact pinned subset, and an empty tuple serves nothing.
[`platform/ops-mcp/README.md`](../platform/ops-mcp/README.md) is the complete guide to the adapter's setup, tool contract, and migration notes; [`docs/mcp.md`](../docs/mcp.md) covers its usage within the documentation set.

Operationally this is a supervised process: no health endpoint, no readiness check, and no metrics path exist for a supervisor to poll.
A supervisor watches the process and the port.

---

## 7. Configuration

**Almost every knob is a key in the `properties` mapping passed to a call**, which keeps configuration per invocation rather than per process and keeps the library from depending on ambient state.
The adapter reads `BLUE_DATA_OPS_MCP_HOST`, `BLUE_DATA_OPS_MCP_PORT`,
`BLUE_DATA_OPS_MCP_KEY` and `BLUE_DATA_OPS_MCP_AUTH_DISABLED` through the shared HTTP policy.

The core reads exactly two, and they are the deliberate exception: `BLUE_DATA_LLM_PROVIDER` and `BLUE_DATA_LLM_ALLOWED_MODELS`, both in `llm/client.py`.
They decide which provider a call is dispatched to, and a caller cannot reach them — on the adapter, `properties` is a tool argument, so anything configurable there is configurable by whoever calls the tool.
The environment the process starts in is the one channel that is the deployment's alone.

The command is the one place that does read the environment, because a shell user has nowhere else to put a setting.
It resolves a value through four tiers — command option, environment variable, profile, built-in default — and then passes what it resolved into the same `properties` mapping.
Nothing about the library's contract changes; the resolution happens above it.
[`../platform/ops-cli/README.md`](../platform/ops-cli/README.md) lists the parameters.

The keys that matter operationally:

| Key | Effect |
|---|---|
| `execution.timeout_seconds` | A wrapper deadline on one `run()` call; must be a finite number greater than zero. The wrapper never retries, and a breach returns an `OPERATOR_TIMEOUT` record |
| `openai.model` | The model an LLM-backed operator requests, within the provider the deployment names. Refused with `model_not_allowed` when it resolves elsewhere |
| `llm.cache` | Enables the on-disk response cache; requires the `llm` extra's `diskcache` |
| `llm.cache_dir` | Where that cache lives, defaulting to `.llm_cache` in the working directory |
| `llm.max_parallel` | Bound on concurrent asynchronous provider calls |
| `llm.rate_limit` | A ceiling in calls per second; the client sleeps to hold the resulting minimum interval |

The two keys the deployment sets, rather than a caller:

| Variable | Effect |
|---|---|
| `BLUE_DATA_LLM_PROVIDER` | The provider every LLM-backed call is dispatched to, defaulting to `openai`. It is read from the environment the process starts in, which is the one channel a tool caller cannot reach, and it is checked against the provider library's own name list before each LLM-backed call rather than at process start, so a misspelled value lets the service start and pass a readiness check and then refuses its first LLM-backed request with `bad_provider` |
| `BLUE_DATA_LLM_ALLOWED_MODELS` | When set, the exact set of models a call property may ask for. It only ever narrows: a model outside it is refused, and listing a model never licenses a route the dispatch check would otherwise refuse |

A deployment reaching a provider other than OpenAI must set the first.
A model identifier containing a slash — the shape Fireworks and Together use — does not need listing, because a slash is not read as a provider prefix.

Two classes of key are refused rather than forwarded.
A property outside the generation set — `api_key`, `api_base`, `base_url`, `custom_llm_provider`, the Vertex and Bedrock selectors, and every other routing or identity field — raises `LLMError` with code `reserved_field`, because the endpoint and the key come from the environment the deployment starts in and a caller-chosen endpoint would send the prompt somewhere else and say nothing about it.
`model` is additionally held to the deployment's provider, and one that resolves elsewhere is refused with `model_not_allowed`.
A bare model name selects a provider too, so the check is on the outcome — what the provider library would actually dispatch to — as well as on the spelling.
A slash is not itself a provider prefix: an identifier such as `accounts/fireworks/models/llama-v3` names a model and is accepted, while `azure/my-deploy` is not, because the deployment names Azure and the property names the deployment.
A third code, `bad_provider`, is deployment misconfiguration rather than a caller error: it names `BLUE_DATA_LLM_PROVIDER` and the value it was given when that value is not a provider the library serves, so the misconfiguration is reported where it was made rather than deep inside the provider call.
A property that would substitute the provider's answer, `mock_response` or `mock_timeout`, is refused under the same code: a result carries what the provider answered, not what the caller sent.
Both are refused before the cache key is built, so nothing sent under one of those names is written to disk either.

`llm.cache_dir` is the only path this package writes to on its own initiative, and only when `llm.cache` is set.
Its default, `.llm_cache`, is relative to the process working directory and is not covered by either `.gitignore` in this repository, so a run with caching enabled inside a checkout leaves an untracked directory.
Point it somewhere outside the tree, or add it to the ignore file, before enabling the cache during development.

**Credentials are never read by this package.**
An LLM-backed operator hands its request to LiteLLM, and the plan generator hands its request to the OpenAI SDK; each of those libraries reads its own provider variables, such as `OPENAI_API_KEY`, from the environment.
**That is the only route a credential takes.**
A credential or an endpoint supplied in `properties` is now refused rather than forwarded, so a caller cannot choose either, and a deployment configures both by starting the process with them in its environment.
Nothing here reads, stores, logs, or forwards a key, and no credential belongs in a `properties` mapping, which is serialized into a plan record.

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

There is no metrics endpoint, no OpenTelemetry dependency, no structured-log formatter, and no trace export.
Cost and latency exist because the LLM client records them per call, not because anything aggregates them.

---

## 9. What Is Not Automated

The repository does not automate the following operations.

- **No pipeline.**
  No `.github/`, no CI configuration, no verify, build, or publish stage.
  Nothing runs on a push.
- **No Git tags.**
  A release is a commit plus the version in that commit's `pyproject.toml`.
- **No container image.**
  No `Dockerfile`, no compose file, no deployment manifest.
- **No deploy script.**
  `scripts/{build,install,publish}.sh` wrap the commands in sections 3, 4, and 5 and add nothing to them; nothing invokes them, and nothing deploys.
- **No dependency lock file.**
  Version constraints are the only pinning. Core requires `jsonmerge==1.9.2`, each adapter pins core exactly, and the MCP adapter bounds `mcp>=1.28.1,<2`.
- **No process supervision recipe.**
  The MCP server is started by the commands in section 6 and supervised by whatever the operator already uses.

The library is installed rather than deployed.
Long-running MCP deployments need process supervision and release automation beyond what this repository provides.

HTTP requires the shared API key by default on both streamable HTTP and SSE.
See the [HTTP bind, authentication and mounted lifespan contract](../docs/mcp.md#http-authentication-and-bind-settings)
for environment overrides, the explicit no-key opt-out and the SDK Host/Origin limits.

# blue-data-ops — Deployment / Ops

How the three distributions are versioned, built, installed, and operated, and which parts of that are done by hand.

## Overview

This repository ships three Python distributions and nothing else.
There is no container image, no service manifest, and no pipeline.
All three are installed into a Python process — a caller's process for the library, one the operator starts for the MCP adapter, which serves streamable HTTP on a loopback address by default, and a shell's for the `blue-ops` command.

One absence and one convention shape everything below, and both are stated once here rather than repeated in every section:

- **There is no CI.**
  The repository has no `.github/` directory and no CI configuration of any kind.
  Every check, build, and publish step is a command someone runs.
- **The shell scripts wrap those commands and automate nothing beyond them.**
  Each distribution carries `scripts/{build,install,publish}.sh`, which is the family's convention.
  They run `python -m build`, `pip install -e`, and `twine upload dist/*` with this repository's own sibling-checkout resolution folded in; nothing invokes them, and no `deploy.sh` exists.
  `lib/scripts/` also holds the two Python maintenance scripts described in [07-repo-organization.md](07-repo-organization.md).

---

## 1. Versioning

Three version axes run independently, and conflating them is the usual source of confusion.

| Axis | Where it lives | Moves when |
|---|---|---|
| Distribution version | `version` in each package's `pyproject.toml` | That package's own public surface or behavior changes |
| Operator card version | The `@MAJOR.MINOR.PATCH` half of an exact operator ID | One operator's behavior changes; the previous version stays resolvable |
| An interface package's core pin | `blue-data-ops==<version>` in the adapter's or the command's dependencies | That package is verified against a new core release |

Each distribution declares its own version and none reads another's.
There is no repository-wide version, and no `MAJOR.MINOR.PATCH` for the repository as a whole.

Operator card versions are the axis that matters most in practice.
A card is registered under `name@<MAJOR.MINOR.PATCH>`, registration is immutable — no overwrite and no deregister — and a version is therefore never reused.
That is what lets the history registry keep the 87 cards that earlier releases resolved while the active view offers the 33 a current caller should use.
[`lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md) is the source of truth for which boundary a given change crosses, and [10-data-model.md](10-data-model.md) covers the card record itself.

A change that touches only documentation moves none of the three.
A distribution version bump is a claim about code.

The repository carries no Git tags, so a release is identified by its commit and by the version in the `pyproject.toml` at that commit.
[`../CHANGELOG.md`](../CHANGELOG.md) carries one entry per released version and names which of the three distributions moved.

---

## 2. Distributions

| Package | Path | Version | Console script | Runtime dependencies |
|---|---|---|---|---|
| `blue-data-ops` | `lib/` | `3.1.0` | none | `blue-data>=0.1.0`, `pydantic>=2`, `jsonmerge==1.9.2`, `jsonpath-ng`, `tenacity` |
| `blue-data-ops-mcp` | `platform/ops-mcp/` | `1.0.0` | `blue-data-ops-mcp` | `blue-data-ops==3.1.0`, `mcp==1.27.2`, `pydantic>=2.11,<3` |
| `blue-data-ops-cli` | `platform/ops-cli/` | `1.0.0` | `blue-ops` | `blue-data-ops[ml,vector,llm]==3.1.0`, `click>=8.0`, `rich>=13.0` |

Each package's own README is the source of truth for installing and using it: [`lib/README.md`](../lib/README.md), [`platform/ops-mcp/README.md`](../platform/ops-mcp/README.md), and [`platform/ops-cli/README.md`](../platform/ops-cli/README.md).

The core declares no `[project.scripts]`, so installing the library alone adds no command to `PATH`.
That is the part of the earlier decision that has not moved: the library is imported, and neither argument parsing nor output formatting sits in front of it.
Each interface is its own distribution instead, so a process that wants four aggregates installs neither.

Each interface package's pin on the core is exact, not a floor.
That is deliberate: the adapter's tool schemas are a projection of the core's attribute specs, and a core that changed a spec would change the wire contract without the adapter's version moving.
The same holds for the command's rendering of an operator's attribute schema.
Upgrading the core therefore requires an interface release, and each pair is verified together.

The three `[project]` blocks are minimal — `name`, `version`, `description`, `readme`, `requires-python`, and `dependencies`.
None declares a license field, an author, a classifier, or a project URL, although the repository carries a `LICENSE` at its root. That root file also sits outside every package's build root, so a built wheel carries neither the licence text nor a licence identifier.
A publishing workflow that needs those metadata fields has to add them.

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

```bash
python -m venv blue-data-ops/lib/.venv
source blue-data-ops/lib/.venv/bin/activate
./blue-data-ops/lib/scripts/install.sh
```

The same thing by hand, which is what to do when `blue-data` is somewhere `BLUE_DATA_PATH` would have to name:

```bash
python -m pip install -e ./blue-data/lib
python -m pip install -e "./blue-data-ops/lib[dev]"
```

Against a configured artifact index, install the built distributions instead:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==3.1.0" \
  "blue-data-ops-mcp==1.0.0" \
  "blue-data-ops-cli==1.0.0"
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

Build each from its own directory, with the `dev` extra installed for `build`.
Each package's `scripts/build.sh` is this command and nothing else:

```bash
cd lib
python -m build

cd ../platform/ops-mcp
python -m build

cd ../ops-cli
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
The adapter's `package-data` declares `py.typed` alone, and the command's declares `py.typed` and `profile_spec.json`, which is the configuration parameter list every `blue-ops profile` command reads.

**Files in the source distribution but not the wheel** come from `lib/MANIFEST.in`: `COMPATIBILITY.md`, `OPERATORS.md`, three named test fixtures — two of which are the reference generator's sealed inputs — and `scripts/`, both the Python tools and the three shell scripts.
A source checkout and an extracted source distribution therefore both carry the reference material and the generator; a wheel does not.
[`lib/README.md`](../lib/README.md) states that difference for users and tells a wheel-only reader to fetch the matching source distribution.
Neither interface package has a `MANIFEST.in`.

A wheel does expose its package README through distribution metadata, which is why [`lib/README.md`](../lib/README.md) links no file that only the source distribution carries.
A test enforces that.

---

## 5. Publishing

`twine` is a `dev` extra of every package and is the intended upload tool, wrapped by each one's `scripts/publish.sh`.
Beyond that, publishing is unautomated: there is no CI job and no registry configured in the repository.

The pre-publish sequence, all of it manual:

1. Run all three test suites on each supported interpreter, per [11-testing-strategy.md](11-testing-strategy.md).
2. Run `ruff format --check`, `ruff check`, and `pyright` in each package directory, per [08-coding-style.md](08-coding-style.md).
3. Run `cd lib && python scripts/generate_operator_reference.py --check`, so a stale `OPERATORS.md` stops the release instead of shipping.
4. Build each distribution with `python -m build`, or `scripts/build.sh`.
5. Run the built-artifact check over the wheels together, which verifies the versions, the exact core pin, and every resource package digest.
6. Add a `CHANGELOG.md` entry naming each distribution whose version moved and what a caller has to do about it.
7. Upload with `twine`, or `scripts/publish.sh`, against whichever index the operator is publishing to.

Steps 3 and 5 are specific to this repository.
Neither is wired into `pytest`, so both are easy to skip, and both are worth the two minutes.

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
| Host | `127.0.0.1` | Loopback. Binding elsewhere is an explicit argument |
| Port | `8000` | |
| Path | `/mcp` | |
| Session state | stateful | `stateless_http=False` |
| Response encoding | SSE rather than plain JSON | `json_response=False` |

Two tests in the adapter suite assert those settings and the transport `serve()` picks, so a default cannot change quietly.

**The transport is the family's exception, and the reason is the shape of the work.**
The rest of the Blue Data family speaks stdio.
These tools bridge long CPU-bound and provider-bound calls onto worker threads, so a slow call does not hold the event loop and several calls stay in flight at once; the adapter suite proves both, along with protocol cancellation of a running call over a live session.
A client-spawned stdio subprocess fits that badly: it ties the server's lifetime to one client, gives concurrent work nowhere to live across sessions, and makes a long-running deployment restart per client.
Converting would break every existing deployment, and the adapter has served streamable HTTP since `0.1.0`.
That is the technical case; whether the family wants one server out of step with the rest is a decision above this repository.

Passing `operator_ids` replaces the default 33-tool selection with an exact pinned subset, and an empty tuple serves nothing.
[`platform/ops-mcp/README.md`](../platform/ops-mcp/README.md) is the source of truth for the adapter's setup, tool contract, and migration notes; [`docs/mcp.md`](../docs/mcp.md) is a synced copy of it.

Operationally this is a supervised process: no health endpoint, no readiness check, and no metrics path exist for a supervisor to poll.
It watches the process and the port.

---

## 7. Configuration

**Almost every knob is a key in the `properties` mapping passed to a call**, which keeps configuration per invocation rather than per process and keeps the library from depending on ambient state.
The adapter reads no environment variable at all.

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
**That is the only route a credential takes, and the only one there has ever been meant to be.**
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

Nothing else is instrumented.
There is no metrics endpoint, no OpenTelemetry dependency, no structured-log formatter, and no trace export.
Cost and latency exist because the LLM client records them per call, not because anything aggregates them.

---

## 9. What Is Not Automated

Collected in one place, because several of these read as oversights when they are current state.

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
  Version constraints are the only pinning, and two of them are exact by design: `jsonmerge==1.9.2` in the core and `mcp==1.27.2` in the adapter.
- **No process supervision recipe.**
  The MCP server is started by the commands in section 6 and supervised by whatever the operator already uses.

None of this needs to change for the library, which is installed rather than deployed.
It would need to change for anything that runs the MCP adapter as a long-lived service, and that is the point at which the first item on this list stops being acceptable.

# Architecture

How `blue-data-ops` is put together and how data moves through it, for a reader who wants to understand the system before using or changing it.
This is the user-facing subset of [`design/03-high-level-architecture.md`](../design/03-high-level-architecture.md) and [`design/04-detailed-architecture.md`](../design/04-detailed-architecture.md); those two carry the reasoning, the alternatives considered, and the internal detail this page leaves out.
For the names and signatures behind every box below, see [api-reference.md](api-reference.md).

---

## Overview

The repository holds two tiers.

- **`lib/`** is the core library, distributed as `blue-data-ops`. Everything the system can do lives here.
- **`platform/`** holds deployable adapters over `lib/`. Today that is an MCP server and a command line, distributed separately as `blue-data-ops-mcp` and `blue-data-ops-cli`.

The MCP adapter validates protocol containers, projects core results into JSON, and handles MCP transport.
The CLI parses inputs, uses the core library APIs, and renders results.

### The core library

```text
    Python caller             MCP client            CLI user
          │                       │                     │
          │                       ▼                     ▼
          │          ┌──────────────────────────┐ ┌──────────────┐
          │          │    blue_data_ops_mcp     │ │   blue-ops   │
          │          │  33 tools, one per each  │ │ command line │
          │          │  active operator         │ └──────┬───────┘
          │          └─────────────┬────────────┘        │
          ▼                        ▼                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                              blue_data_ops                              │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ plan/                                                             │  │
│  │   DataPipeline         a serializable node-and-entity graph       │  │
│  │   PipelineExecutor     preflight, then run in topological order   │  │
│  │   PipelinePlanner      discover, generate, select, compile        │  │
│  │   RulePlanGenerator    deterministic caller-supplied rules        │  │
│  │   OpenAIPlanGenerator  one non-streaming Responses call           │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                        │  resolves every step id through                │
│                        ▼                                                │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ operators/                                                        │  │
│  │   Operator             run / apply / invoke / validate            │  │
│  │   OperatorRegistry     register / resolve / find / list_cards     │  │
│  │   OperatorCard         a pinned id with its tags and guidance     │  │
│  │   33 operator classes  the built-in catalog                       │  │
│  │   OperatorEmbedding-   ranks cards through a caller-supplied      │  │
│  │     Index              embedder; no model ships with the package  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ operator_skills/       reviewed Markdown keyed to an exact id     │  │
│  │   OperatorSkillLoader  54 packages: 33 at @2.0.0, 21 at @3.0.0    │  │
│  │                                                                   │  │
│  │ tools/  Tool           the Blue function wrapper Operator extends │  │
│  │ utils/                 Blue type, signature, JSON and id helpers  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ data/  RegistrySeam             llm/  LLMClient                   │  │
│  │   the package's only              LiteLLM transport, caching,     │  │
│  │   blue-data import boundary       rate limiting, usage ledger     │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└──────────────────────┬───────────────────────────┬──────────────────────┘
                       │                           │
                       ▼                           ▼
           ┌──────────────────────┐    ┌──────────────────────┐
           │      blue-data       │    │       LiteLLM        │
           │     DataRegistry     │    │    model provider    │
           └──────────────────────┘    └──────────────────────┘
```

The package has two external dependency boundaries.
`data/` is the single `blue-data` import boundary, so every operator that needs a data registry reaches one through the same facade instead of holding its own coupling.
`llm/` is the single model-provider boundary, so the eight provider-backed operators — `nl2llm`, `nl2sql`, `nl2bn`, and the five `semantic_*` operators — share one transport, one cache, and one usage ledger.

| Module | Role |
|---|---|
| `operators/` | The `Operator` base class, the 33 built-in operator classes, the registry, operator cards, and both discovery paths |
| `operator_skills/` | Reviewed Markdown resources keyed to an exact operator ID, plus the loader that verifies their digests |
| `plan/` | `DataPipeline` as a portable graph record, the executor that runs one, and the planner that builds one |
| `data/` | `RegistrySeam` and the provider seam; the only place `blue_data` is imported |
| `llm/` | `LLMClient`, its usage ledger, and the provider seam for swapping how model calls are made |
| `tools/` | `Tool`, the Blue-compatible function wrapper `Operator` extends |
| `utils/` | The Blue type, signature, JSON, and identifier helpers the operator surface depends on |

`operators/` does not import `plan/`, and `data/` does not import `operators/`.
The dependency direction is one-way in both cases, which is what lets a caller use an operator without pulling in the planner, and use the registry seam without pulling in the operator catalog.

---

## Platform layer

| Component | Distribution | Transport | Status |
|---|---|---|---|
| Python library | `blue-data-ops` from `lib/` | in-process import | Implemented |
| MCP server | `blue-data-ops-mcp` from `platform/ops-mcp/` | streamable HTTP, loopback by default | Implemented |
| CLI | `blue-data-ops-cli` from `platform/ops-cli/` | the `blue-ops` command, in process | Implemented |

Both interface distributions pin core exactly, at `blue-data-ops==1.0.0`.
One environment therefore holds one matched set, which is how a tool's advertised operator version stays true.
The adapter serves 33 primary tools, one per active operator, each named `ops_` plus the operator's name, and holds no state between calls beyond the frozen deployment snapshot it built at startup.
The command holds its state on disk instead, under `~/.blue-ops`: profiles, the selected catalog, and stored pipelines.

Neither interface holds operator behavior.
That is the architecture decision the split exists for: the library is the contract, and an interface is a projection of `run()` that a caller reaches over a different boundary.

---

## The data model

Every operator consumes and produces the same shape.

```python
from typing import Any

Record = dict[str, Any]  # one JSON-like record
Data = list[Record]  # one group of records
DataBundle = list[Data]  # what an operator receives and returns
```

A single group is the common case, so most calls look like `[[record, record, ...]]`.
The extra nesting is what lets `join` and `intersect` read two inputs, and what lets an operator hand several groups to the next step.
An empty result is `[[]]`, one empty group, never `[]`.

Attributes are the per-call arguments an operator declares; properties are execution settings.
Both are plain `dict[str, Any]`.
An operator declares each attribute once as an `AttributeSpec`.
The declaration drives default materialization, validation, the MCP JSON schema, and the generated reference in [`lib/OPERATORS.md`](../lib/OPERATORS.md).

---

## Data flow: one operator call

`run()` is the canonical boundary.
Everything that can go wrong inside it comes back as data rather than as an exception.

```text
caller
  → Operator.run(input_data, attributes, properties)
      → read properties["execution.timeout_seconds"]
          → when set, run the body in one worker thread with that deadline
      → refresh the live attribute projection from the declared AttributeSpecs
      → materialize declared optional defaults over a copy of the attributes
      → _validate_input(...)  →  ValidationResult(ok, reason)
          → not ok: return [[]], {}, ExecMeta(errors=[INVALID_INPUT at VALIDATE])
      → _execute(...)  →  FunctionResult(output_data, output_attributes)
          → raised exception: [[]] plus EXECUTION_FAILED at EXECUTE
      → normalize: an all-empty bundle becomes [[]] with is_empty=True
  ← (output_data, output_attributes, ExecMeta)
```

`apply()` and `invoke()` skip that boundary.
`apply()` is the raw transform and lets exceptions through; `invoke()` runs boolean validation first and returns `None` when it fails.
Both are retained for callers written against the 1.x surface.
New code should use `run()`, because it is the only path that gives every call a fresh output-attributes mapping, a normalized empty result, and a structured error record instead of a traceback.

A timeout gets its own category rather than being folded into failure, so a caller can retry a deadline without retrying a rejected input.
The wrapper itself never retries.

---

## Data flow: resolving an operator

Resolution requires a pinned ID; discovery accepts looser queries and returns pinned cards.

```text
registry = active_registry()          # 33 cards: 12 at @2.0.0, 21 at @3.0.0

registry.find("filter", tags=["domain-relational"])   # loose  → ranked cards
    exact AND tag filter, then text scoring:
    name 10, any tag 8, when_to_invoke 6, description 5, each field once
    ties break on name, then descending version

registry.resolve("select@2.0.0")      # strict → exactly that operator
    a bare name raises ResolveError; there is no "latest" at resolution time
```

Every card `find()` returns is already pinned, so it is in the form `resolve()` accepts.
A registered `name@version` is immutable: no overwrite, no deregister, no silent upgrade.
That is what makes a saved pipeline reproducible — the IDs in the record name one implementation each, for as long as the registry that resolves them offers it.

Three registry views exist because three questions are different.

| View | Contains | Answers |
|---|---|---|
| `active_registry()` | 33 reviewed cards, twelve at `@2.0.0` and twenty-one at `@3.0.0` | What should I use now? |
| `versioned_registry()` | 87 retained historical cards | What did this ID mean before? |
| `default_registry()` | 33 raw cards at `1.0.0`, with per-name overrides | What did the 1.x compatibility surface look like? |

Raw cards carry empty `tags` and `when_to_invoke` and grant no planning authority, even when their ID text matches a supported one.
The 21 operators active at `@3.0.0` are outcome operators: same contract, plus shallow shape and elapsed-time measurements in `ExecMeta.traces`.

---

## Data flow: a pipeline

A `DataPipeline` is a record, not a running object.
It serializes, travels, and comes back; execution is a separate step that needs a registry.

```text
DataPipeline (a record)                 PipelineExecutor(registry)
  define_input("records")      ─┐
  define_operator("select@2.0.0", ...)  preflight(pipeline)
  define_output("selected")     ├──────→   resolve every node's exact id
  connect_nodes(...)            │          check graph shape and reachability
  set_plan_input / set_plan_output         check declared attributes
                               ─┘        ← PipelinePreflight(node_order, ids)

                                        execute(pipeline, input_data)
                                          walk node_order
                                          feed each node its predecessors' output
                                          call operator.run(...)
                                          record a NodeRun, set node status
                                          stop at the first node with errors
                                        ← PipelineRun(output_data, node_runs,
                                                      failed_node_id)
```

Preflight and execute raise `PipelineError` for a graph or an input that cannot be run at all.
An operator failure after preflight does not raise: it lands in `node_runs[*].exec_meta`, and `failed_node_id` names the node.
The split matters when you are driving this from a UI or an agent loop — a malformed graph is a caller bug, while a failed operator is a result you display.

Execution mutates node values and statuses on the supplied plan, so round-trip a copy when the original record has to stay unchanged.

---

## Data flow: planning

`PipelinePlanner` owns six stages and delegates exactly one.

```text
PipelinePlanner(registry, generator).plan(request)
  1. VALIDATION    copy and check the PlanningRequest and its bounds
  2. DISCOVERY     run each DiscoveryQuery against the registry
                     → DiscoverySnapshot(cards), all pinned
  3. DATA_CONTEXT  when request.data_scope is set, ask the provider for a
                     bounded DataContextSnapshot: entity and attribute names,
                     descriptions, declared types. No rows, ever
  4. GENERATION    generator.generate(request, discovery, data_context)
                     → Sequence[PlanDraft]        ← the one delegated stage
  5. SELECTION     selector picks one draft (RequireSinglePlan by default)
  6. COMPILATION   turn PlanSteps into a materialized DataPipeline
  7. PREFLIGHT     hand it to PipelineExecutor.preflight
  ← PlanningResult(request, discovery, candidates, selected, pipeline,
                   preflight, data_context)

run(request, input_data) = plan(request) + execute → PlannerRun
```

Generation is the only stage a caller replaces, and it is the only stage that may be nondeterministic.
`RulePlanGenerator` is deterministic and offline; `OpenAIPlanGenerator` makes one non-streaming Responses call.
Both hand back drafts that the planner then validates, compiles, and preflights itself, so a bad draft fails inside the package rather than at execution time.

Planning raises `PlanningError` instead of returning a partial result, because at that point no pipeline exists to carry the record.
Each error carries a stage and a stable code.
Provider failures map to codes such as `GENERATOR_TIMEOUT` and `GENERATOR_UNAVAILABLE`, and the records exclude response bodies, request payloads, credentials, and provider-specific exception text.

`allowed_operator_ids` is an authorization boundary rather than a filter.
Without a request allowlist, package built-ins are limited to the `active_registry()` selection; `OpenAIPlanGenerator` separately requires a nonempty `allowed_operator_ids` argument.
A generator cannot reach an operator discovery never returned.

---

## Data flow: an MCP tool call

The adapter freezes its tool set once, at construction.

```text
create_server(registry=None, operator_ids=None)
  freeze_deployment(...)
    for each selected id:
      get_card  →  resolve  →  check name, version, and implementation class
      package-owned ids must be same-registry built-ins
    reject a duplicate id, or two versions of one logical name
  ← DeploymentSnapshot, ordered by logical name

  register one tool per binding:
    name         "ops_" plus the logical operator name, e.g. "ops_select"
    description  the card's when_to_invoke, then its description
    _meta        operator_id, version, ordered tags
    signature    input_data (required), attributes, properties

client.call_tool("ops_select", {...})
  → handler runs operator.run(...) on a worker thread
  → project the result once: default=str for exotic leaves, reject NaN and Infinity
  ← structuredContent {output_data, output_attributes, exec_meta}
```

A recoverable, failed, timed-out, or successful-empty operator outcome is a successful MCP result with `isError` false; the detail is in `exec_meta`.
An unknown tool, malformed top-level arguments, or a projection failure sets `isError` true and adds no operator error record.
That split keeps operator semantics out of the transport layer.

MCP has no server-side tag query, so tag filtering is a client-side read of each tool's `_meta`.
[mcp.md](mcp.md) has the full contract.

---

## Where the seams are

Four things are designed to be replaced, and each has one injection point.

| To change | Supply | Reached through |
|---|---|---|
| The operator catalog | An `Operator` subclass registered in your own registry | `OperatorRegistry.register` |
| How discovery ranks cards | An `OperatorEmbedder` | `OperatorEmbeddingIndex.build` |
| How model calls are made | An already-built `LLMClient`, or an `LLMClientProvider` | `resolve_llm_client` |
| Which data registry an operator uses | An already-built `RegistrySeam`, or a `DataRegistryProvider` | `resolve_registry` |

[extending.md](extending.md) works through all four with running code.
Nothing else in the library is a plugin point: the operator lifecycle, the error vocabulary, the result envelope, and the registry's immutability are fixed.

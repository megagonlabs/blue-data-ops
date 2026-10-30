# blue-data-ops — High Level Architecture

The repository is divided into the components below, with each component's responsibility and
external interface identified.
See [04-detailed-architecture.md](04-detailed-architecture.md) for information flow and
[06-library.md](06-library.md) for the module inventory.

## Diagram

```
                              External Interfaces

  ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
  │    Python Library    │  │      MCP Server      │  │     blue-ops CLI     │
  │    (implemented)     │  │  (implemented, own   │  │  (implemented, own   │
  │ import blue_data_ops │  │    distribution)     │  │    distribution)     │
  └──────────┬───────────┘  └──────────┬───────────┘  └──────────┬───────────┘
             └───────────┬─────────────┴─────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          blue-data-ops core (lib/)                           │
│                                                                              │
│  plan/                                                                       │
│  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────────┐  │
│  │  PipelinePlanner   │─▶│   Plan Generator   │  │ Data Context Provider  │  │
│  │ discover · select  │  │   Rule / OpenAI    │  │  bounded · read-only   │  │
│  │ compile · preflight│  └────────────────────┘  └────────────────────────┘  │
│  └─────────┬──────────┘                                                      │
│            ▼                                                                 │
│  ┌────────────────────┐  ┌────────────────────┐                              │
│  │    DataPipeline    │─▶│  PipelineExecutor  │                              │
│  │   portable graph   │  │  preflight · run   │                              │
│  └────────────────────┘  └─────────┬──────────┘                              │
│                                    ▼                                         │
│  operators/                                                                  │
│  ┌────────────────────────┐  ┌────────────────────────────────────────────┐  │
│  │   Operator Registry    │─▶│            Operator Catalog                │  │
│  │ resolve — pinned only  │  │  33 active exact cards · 21 outcome        │  │
│  │ find — text and tags   │  │  variants · 87 historical cards            │  │
│  │ + Embedding Index      │  └────────────────────────────────────────────┘  │
│  └────────────────────────┘                                                  │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │               Operator Runtime   (Tool ─▶ Operator.run)                │  │
│  │   defaults ─▶ validate ─▶ execute ─▶ normalize ─▶ execution metadata   │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌──────────────────────┐  ┌──────────────────┐  ┌────────────────────────┐  │
│  │   operator_skills/   │  │       llm/       │  │         data/          │  │
│  │  54 exact packages   │  │    LLMClient     │  │      RegistrySeam      │  │
│  │  digest-verified     │  │  + client seam   │  │ + DataRegistryProvider │  │
│  └──────────────────────┘  └─────────┬────────┘  └───────────┬────────────┘  │
│                                      │                       │               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  utils/   type parsing · signatures · JSON merge and query · IDs       │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────┬───────────────────────┬───────────────┘
                                       ▼                       ▼
                        ┌──────────────────────────┐  ┌──────────────────────┐
                        │    LiteLLM providers     │  │      blue-data       │
                        │  OpenAI Responses API    │  │     DataRegistry     │
                        │  extras · lazy import    │  │  eager dependency    │
                        └──────────────────────────┘  └──────────────────────┘
```

## Component boundaries

Eight components live inside the core distribution and the MCP adapter is the ninth.
This table is the boundary list the rest of the design documents refer back to.

| Component | Path | Owns | Reached through | Never does |
|---|---|---|---|---|
| Operator Runtime | `operators/operator.py`, `operators/types.py`, `operators/_metadata.py`, `tools/` | the five-stage call boundary, the result and error types, the Blue metadata surface | `Operator.run()`, `Operator.apply()`, `Operator.invoke()` | resolve a name, touch the network, read a file |
| Operator Catalog | `operators/*_operator.py`, `operators/sklearn_estimator.py`, `operators/_*_outcome.py` | the 33 built-in implementations and the 21 outcome subclasses | the registry factories, or direct class construction | register itself; the catalog tuple is explicit, never a package scan |
| Operator Registry | `operators/registry.py`, `operators/_discovery.py`, `operators/embedding_discovery.py` | pinned identity, immutable registration, discovery scoring, the closed tag vocabulary, built-in provenance | `default_registry()`, `active_registry()`, `versioned_registry()`, `OperatorRegistry`, `OperatorEmbeddingIndex` | execute an operator, or answer "latest" from `resolve()` |
| Operator Skill Store | `operator_skills/` | 54 exact-version resource packages, the closed index, digest verification | `OperatorSkillLoader` | invoke an operator, cache, or disclose text on its own |
| Plan | `plan/` | portable pipeline records, graph validation, execution ordering, the planning stages, the planning error vocabulary | `DataPipeline`, `PipelineExecutor`, `PipelinePlanner`, `DataContextProvider` | mutate the registry, or retry and replan |
| Data Registry Seam | `data/` | the only `blue-data` import in the package, compatibility argument shapes, search-score normalization | `RegistrySeam`, `DataRegistryProvider`, `resolve_registry()` | import `operators`, `llm`, or `plan` |
| LLM Client | `llm/` | request templating, provider dispatch, retry, caching, rate limiting, per-call usage records | `LLMClient`, `LLMClientProvider`, `resolve_llm_client()` | import `operators`; choose a provider credential |
| Utilities | `utils/` | Blue-compatible type parsing, signature extraction, JSON merge and query, ID helpers, substitution | `blue_data_ops.utils` | import `operators`, `plan`, or `data` |
| MCP Adapter | `platform/ops-mcp/` | the frozen deployment snapshot, the wire projection, tool registration | `create_server()`, `serve()` | add behavior; every tool is a projection of `run()` |

### Dependency direction

The import graph is acyclic at the directory level.
Two edges define the main dependency boundaries.

`data/` imports no other package directory in `blue_data_ops`.
It defines its own local `Properties` alias rather than importing the one in `operators/types.py`, precisely so the edge stays one-way: operators import the seam, and the seam knows nothing about operators.

Nothing inside the package imports `plan/`.
The planner and executor sit above the operator surface and are removable from any caller's dependency footprint without touching an operator.

| Importer | Imports |
|---|---|
| `plan/` | `operators/`, `data/` |
| `operator_skills/` | `operators/` |
| `operators/` | `tools/`, `data/`, `llm/`, `utils/` |
| `tools/` | `operators/_metadata` |
| `utils/` | `llm/templating`, for `safe_substitute` |
| `llm/` | nothing internal |
| `data/` | nothing internal |

`tools/` and `operators/` appear to cross, and the cycle does not close: `Tool` reads its signature helpers from `operators/_metadata`, which imports only `operators/types` and `utils/`, neither of which reaches back to `operator.py`.

## Components

### External Interfaces

The repository implements the Python library, MCP server, and CLI.

**Python Library — implemented.**
`import blue_data_ops` is the primary interface and the one every other interface is built on.
The top-level package re-exports the operator classes, the base `Operator` and `Tool`, the result and error types, the registry seam, and `blue_data_ops.utils`.
`blue_data_ops.operators` is the fuller surface and adds the registry factories, `OperatorCard`, the embedding index, and the type aliases.

**MCP Server — implemented, separate distribution.**
`platform/ops-mcp/` ships as `blue-data-ops-mcp` with its own version and an exact pin on the core.
It registers the 33 active operators as primary tools over the canonical `run()` boundary and adds no behavior of its own.
[`../platform/ops-mcp/README.md`](../platform/ops-mcp/README.md) is its source of truth.

**CLI — implemented, separate distribution.**
`platform/ops-cli/` ships as `blue-data-ops-cli` with its own version and an exact pin on the core, and installs one console command, `blue-ops`.
It parses arguments, keeps profiles and their configuration, resolves a catalog, and prints results; every operator call it makes goes through the same canonical `run()` boundary the other two interfaces use.
The separate distribution keeps argument parsing, output formatting, and profile configuration out of the core.
[`../platform/ops-cli/README.md`](../platform/ops-cli/README.md) is its source of truth.
Scripts under `lib/scripts/` are the library's own maintenance and packaging tools, not installed commands.

**REST API — not built.**
There is no `platform/api/` directory and no HTTP framework in any dependency set.
A network interface over these operators is what the MCP adapter already is, over a protocol agents already speak.

### Operator Runtime

The abstract base every operator inherits, and the contract every caller sees.

- Declares an operator's attributes as frozen `AttributeSpec` class data, then projects them into the live Blue metadata view that `properties["attributes"]` and the generated signature expose.
- Runs the canonical boundary in five stages — default materialization, validation, execution, normalization, and metadata assembly — and contains a failure at each one as a typed `ErrorRecord` rather than letting it escape.
- Retains the raw Blue-compatible call shapes beside that boundary: `apply()` calls the transform directly, `invoke()` runs boolean validation first and returns `None` when it fails, and neither converts an exception into metadata.
- Applies an optional wrapper deadline from `properties["execution.timeout_seconds"]`, in a single-worker thread pool, with no retry.
- Carries the Blue `Tool` surface underneath: live properties, the signature dictionary, and the parameter and return accessors.

**`Operator`** — the abstract base. Subclasses implement `apply()` and may override `_execute()` to return output attributes alongside output data, `validate()` or `_validate_input()` to add checks, and `explain()` to describe a completed transform.

**`Tool`** — function plus live properties, validator, explainer, and signature metadata. It exists so an operator is recognizable to Blue-shaped tooling that reads `properties["tool_type"]`.

**Result and error types** — `FunctionResult`, `ValidationResult`, `ErrorRecord`, `ExecMeta`, and the three closed enums `ErrorCategory`, `ErrorStage`, and `ErrorCode`. All are `NamedTuple` or `str`-valued `Enum` members, so a caller can compare, unpack, and serialize them without importing a schema library.

### Operator Catalog

The 33 concrete implementations, plus the 21 outcome subclasses that layer measurement and output attributes onto them.

- One module per operator, each carrying its class and a module-level `DISCOVERY` constant holding that operator's invocation guidance and ordered tags.
- An outcome operator subclasses both `_OutcomeOperator` and its raw counterpart, so the `@3.0.0` card and the `@2.0.0` card share one transform and differ in what they report.
- The catalog is one explicit, name-ordered tuple in `registry.py`. Package export scanning never decides membership, and adding a module does not add an operator.
- `OperatorDiscoverOperator` is an operator-shaped facade over registry discovery. It carries no `DISCOVERY` record, which keeps it out of the built-in card catalog and out of the MCP inventory.

The per-operator attribute tables, tags, and documented outcomes are generated into [`../lib/OPERATORS.md`](../lib/OPERATORS.md).

### Operator Registry

Identity, discovery, and admission.
Three factories build different views over the same catalog, and the difference between them is what a caller is allowed to do with the result.

| Factory | Cards | Metadata | Intended use |
|---|---|---|---|
| `default_registry(**versions)` | 33 at `1.0.0`, with per-name version overrides | raw: empty `tags`, empty `when_to_invoke` | the retained v1 compatibility view |
| `active_registry()` | 33 exact — 12 at `@2.0.0`, 21 at `@3.0.0` | validated discovery metadata, marked reviewed | ordinary discovery and execution |
| `versioned_registry()` | 87 — 33 at `@1.0.0`, 33 at `@2.0.0`, 21 at `@3.0.0` | validated discovery metadata | migration code that needs retained history |

- `resolve(operator_id)` accepts only `name@<MAJOR.MINOR.PATCH>` and raises `ResolveError` on a malformed reference or a miss. A bare name is a `ResolveError`, not a lookup.
- `find(query, tags=...)` scores case-insensitively — name 10, any tag 8, `when_to_invoke` 6, description 5, each field at most once — after an exact AND tag filter, and returns already-pinned cards.
- `register()` stays permissive for caller-created operators: arbitrary tags, empty invocation text, no vocabulary validation. A registration is immutable, and there is no overwrite and no deregister.
- Built-in provenance is a private set on the registry instance rather than a field on the card. Nothing serializes it, no caller can pass it, and no planning record exports it.
- `upgrade_legacy_operator_id()` converts a bare name, an alias, or a legacy deployment path into a pinned ID — always as an explicit caller choice. Neither `resolve()` nor `DataPipeline.from_dict()` calls it.

**`OperatorEmbeddingIndex`** — an in-memory snapshot bound to one registry and one caller-supplied embedder. `build()` sends each card's name, invocation guidance, description, and ordered tags to the embedder in one batch; `find()` returns every tag-matching card in cosine order with no threshold and no limit. It raises `EmbeddingDiscoveryError` with a stable `reason` for an invalid vector, a failed callback, a mismatched registry, or a snapshot the registry has moved past.

### Operator Skill Store

Reviewed prose about an operator, addressed by the same exact ID the operator is.

- 54 packages under `operator_skills/<name>/<version>/`, each with a `manifest.json` naming its files and their SHA-256 digests.
- `_index.json` is a closed exact-path map from pinned ID to manifest path. One malformed row invalidates the whole index rather than being skipped, including entries whose own rows are valid.
- Every read is bounded before decoding: 4 KiB for the index and a manifest, 16 KiB for a resource, JSON depth 4.
- The reader refuses symlinks at every path segment, rejects absolute and traversing relative paths, and confirms the resolved file sits under the package root and is a regular file.
- A load returns the registry card, the requested level, the loaded kinds, the operator's live attribute schema, the declared input and output shapes, and the text.

Loading requires a package-owned built-in from the loader's own registry. A caller-created registration is not eligible, and the loader holds no cache, so two calls reread the index.

### Plan

Three layers, usable independently.

**`DataPipeline`** — a portable layered node and entity record. Nodes carry reciprocal `prev` and `next` lists, operator entities store only pinned `operator_id` values, and `to_dict()` is the serialization boundary. Runtime synchronization is an optional injected `sync_backend` defaulting to a no-op, which is why the plan package has no message-bus, connection, or stream dependency.

**`PipelineExecutor`** — validates a materialized graph, then runs it. `preflight()` checks node records, edge reciprocity, single declared input and output, acyclicity, reachability, and exact operator resolution without executing anything. `execute()` aggregates each node's predecessor outputs, calls `run()`, records status and value, and stops at the first structured operator failure.

**`PipelinePlanner`** — compiles a pipeline from a goal through discovery, data-context collection, generation, selection, compilation, and preflight. It owns every stage except generation, which is the caller's `PlanGenerator`. It plans once and stops: no retry, no replanning after a failed node, no remote dispatch, and no automatic choice among alternatives under the shipped selector.

**Plan generators** — `RulePlanGenerator` evaluates deterministic caller-supplied rules and needs no network. `RulePlanTemplate` builds a linear draft from exactly matched discovered metadata and caller attributes, and the shipped templates are `SELECT_THEN_AVERAGE_TEMPLATE` and `project_then_aggregate_template(name)` for `avg`, `sum`, `min`, and `max`. `OpenAIPlanGenerator` makes one non-streaming Responses request per call, behind an allowlist that is an authorization boundary and a disclosure opt-in that is separate from it.

**Data context** — `RegistryDataContextProvider` collects a bounded schema snapshot from three read-only registry list operations. It reads entity names, descriptions, and declared attribute types; it reads no relations and no rows, and it records `raw_rows: 0` in the snapshot's own provenance. Default limits are 32 entities, 64 attributes per entity, 512 total attributes, 512 description characters, and 131072 serialized bytes.

**Planning errors** — `PlanningError` subclasses `ValueError` and carries a `PlanningErrorRecord` with the same fields as an operator `ErrorRecord` apart from `operator_id`, which planning has no value for. Its `stage` is one of `VALIDATION`, `DISCOVERY`, `DATA_CONTEXT`, `GENERATION`, `SELECTION`, `COMPILATION`, or `PREFLIGHT`.

### Data Registry Seam

One facade over a `blue-data` `DataRegistry`, and the package's only import of that library.

- Absorbs the differences the operators would otherwise carry: a per-call `rebuild` flag `blue-data` does not accept, a `(query, source)` argument order that is reversed on the other side, a `protocol` parameter with no delegate-side counterpart, and two search result shapes with opposite score polarity.
- Normalizes search results to one flat record shape with an inverted score, so lower is better and list order is already consumer-ascending.
- `resolve_registry(properties, provider=None)` resolves an injected `RegistrySeam`, wraps an injected raw `DataRegistry`, or constructs one from `platform.name` and `data_registry.name` through a provider. An invalid injected value falls through to the construction keys rather than failing.
- `BlueDataRegistryProvider` is the default: a per-name cached in-memory registry with eager index rebuilds. A caller that wants different lifetimes injects its own `DataRegistryProvider`.

Its deliberate differences from Blue's reference behavior are recorded in [`../lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md).

### LLM Client

The provider seam the LLM-backed operators call through.

- `LLMClient.execute_api_call()` builds a templated request from call properties, dispatches through LiteLLM, and extracts the configured output path from an OpenAI-shaped response.
- Adapter overrides are a closed key set; an unknown `llm.*` key is an `LLMError` rather than a value forwarded to the provider. Four control keys — `cache`, `cache_dir`, `max_parallel`, `rate_limit` — are consumed by the client and never sent.
- The prefixed namespaces are closed sets. They admit the generation parameters of the provider call, and refuse everything else, including any field that chooses the provider, the endpoint, the project, tenant or region, supplies a credential, or substitutes the provider's answer. Either is an `LLMError` with code `reserved_field`, raised before the cache key is built. The endpoint and the key come from the environment the deployment starts in. `model` is additionally held to the deployment's provider, and one that resolves elsewhere is refused with `model_not_allowed`. A bare model name selects a provider too, so the check is on the outcome — what the provider library would actually dispatch to — as well as on the spelling. A slash is not itself a provider prefix: an identifier such as `accounts/fireworks/models/llama-v3` names a model and is accepted, while `azure/my-deploy` is not, because the deployment names Azure and the property names the deployment.
- Provides sync and async execution, bounded concurrency, disk caching, rate limiting, and retry with exponential backoff.
- Records one `UsageRecord` per call, cache hits included, with model, token counts, cost, end-to-end latency, and a cache-hit flag.
- The default lifetime is one client per invocation. `properties["llm_client"]` injects one; `CachingLLMClientProvider` reuses one per configuration, and the cache's lifetime belongs to whoever created the provider.

`tenacity` is imported at module import time here, which is why it is a core dependency rather than part of the `llm` extra. LiteLLM and `diskcache` are imported inside the functions that use them. The dollar renderer uses the standard library; Jinja2 remains declared in the compatibility bundle.

### Utilities

The Blue helper functions the operator surface depends on, under the same names and with the same behavior, without importing `blue`.

Type parsing and validation, annotation and signature extraction, the MCP type-shape conversion, JSON merge and JSONPath query and set, canonical ID helpers, and one-pass dollar substitution.
Helpers outside the operator closure are left out on purpose: most of Blue's JSON utilities, the base64 pair in `string_utils`, and the logging helpers.
The porting details that are easy to get wrong — which `typing` objects `string_to_python_type` returns, the falsy-default quirk in `extract_signature`, `merge_json` raising on a scalar base — are recorded in [`../lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md).

### MCP Adapter

The adapter projects `Operator.run()` and implements no operator behavior.

- `freeze_deployment()` validates and freezes one exact primary-only selection. The backing registry may be a superset; only the selected cards become tools.
- A package-owned selection must be a same-registry built-in resolving to the expected implementation class. Explicit caller registrations are accepted at `2.0.0` only, and a custom card cannot shadow a supported built-in logical name.
- Duplicate logical names in a selection fail rather than one winning.
- `make_run_handler()` wraps `Operator.run()`, moves it off the event loop with `asyncio.to_thread`, and validates the projected payload against the `RunResult` model.
- The wire conversion applies `default=str` once for exotic leaves and rejects non-finite floats. That rejection is an adapter error and becomes a tool error, never a synthetic operator `ErrorRecord`.
- Tool names add the adapter's `ops_` prefix to the logical name; `_meta` carries the exact `operator_id`, the version, and the ordered tags.

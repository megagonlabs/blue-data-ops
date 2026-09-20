# blue-data-ops — Overview

## Objective

An agentic platform needs data work it can name, version, plan over, and run without the platform runtime being present.
Blue's operator contract gives that work a shape: a list of record groups in, a list of record groups out, with a declared attribute schema in front of it.
The platform implementation of that contract is wired into the platform's own runtime: its service clients, its synchronization bus, its remote routing.
A consumer that wanted one aggregate took the deployment with it.
This package holds the operator surface on its own, and reproduces none of that runtime.
It installs as an ordinary Python library, resolves operators by exact version, executes them in process, and returns failures as data the caller inspects rather than exceptions the caller must catch.

## What It Does

- Runs 33 active operators across the eight families in the catalog: filter and shape, join and set, aggregate, text, machine learning, vector, LLM, and registry-backed database work.
- Resolves an operator by a pinned `name@<MAJOR.MINOR.PATCH>` identity from an immutable in-process registry, with no latest-version fallback at resolution time.
- Discovers candidates by deterministic text scoring and exact tag filtering over a closed six-axis tag vocabulary, or through a caller-supplied embedding index.
- Offers two call paths per operator: the raw `apply()` and `invoke()` shapes a v1 caller already used, and the canonical `run()` boundary that materializes declared defaults, validates, normalizes empty output, and returns structured execution metadata.
- Contains recoverable failures, hard failures, and timeouts inside that metadata as typed error records carrying a category, code, exact operator ID, stage, message, retryability flag, and optional suggestion.
- Builds, serializes, and executes `DataPipeline` graphs — nodes, reciprocal edge lists, and operator entities that store only pinned IDs — through an executor that preflights structure and resolution before any operator runs.
- Compiles a pipeline from a stated goal through `PipelinePlanner`: discovery, bounded data-context collection, candidate generation, selection, compilation, and preflight.
- Hands a plan generator a bounded read-only schema snapshot of one registered collection — entity names, descriptions, and declared attribute types, never rows.
- Ships 54 operator resource packages keyed by exact operator ID, each file digest-checked against its manifest before its text is returned.
- Keeps 87 historical cards resolvable — 33 at `@1.0.0`, 33 at `@2.0.0`, and 21 at `@3.0.0` — so migration code can reach the exact behavior it was written against.
- Exposes the same 33 active operators as MCP tools from a separate distribution, over the structured result envelope.
- Reaches the same operators, catalogs, and pipelines from a shell through the `blue-ops` command in a third distribution.
- Reaches `blue-data` through a single facade in a single package directory, so that dependency has one place to change.

The generated per-operator reference is [`../lib/OPERATORS.md`](../lib/OPERATORS.md).

## Design Philosophy

Identity is exact and immutable.
A version is part of an operator's name, a registration can never be overwritten or deregistered, and `resolve()` accepts nothing but a fully pinned ID.
The loose half of that contract lives in discovery, which takes fuzzy queries and returns cards that are already pinned, so a caller who searched still executes something it can name.

Failure reporting follows what is left to carry a record.
An operator call always produces a result triple, so invalid input, a broken transform, and a blown deadline all arrive inside `ExecMeta.errors` with the output normalized to `[[]]`.
Planning has no partial pipeline to attach a record to, so it raises `PlanningError` carrying the same structured record on the exception instead.
That asymmetry is deliberate, and planning is the only place in the package where a recoverable outcome is reported by raising.

Weight is opt-in.
The core declares five runtime dependencies.
NumPy, scikit-learn, sentence-transformers, LiteLLM, and the OpenAI SDK are extras, and each is imported inside the function that needs it, so a missing extra becomes an `EXECUTION_FAILED` record at call time rather than a broken package import.

Each external system gets one boundary.
`blue-data` is imported in `data/` and nowhere else, and the seam there absorbs the argument-order and search-score differences so no operator has to know about them.
LiteLLM sits behind `LLMClient`.
The one place that needs a provider's structured-output guarantee — the OpenAI plan generator — holds its own separate SDK seam, and that seam is the only import of the SDK in the package.

Authority is granted, never inferred.
Constructing a registry does not make its cards plannable.
The planner admits the reviewed active selection by default and an explicit allowlist otherwise, then the compiler rechecks card identity, provenance, and lifecycle against the live registry after the generator has already run.
A generator can be wrong, or hostile, without being able to introduce an operator the caller never allowed.

Interfaces stay outside the core.
The core distribution `blue-data-ops` declares no console entry point and no HTTP server; the MCP adapter and the `blue-ops` command are separate distributions, each with its own version and its own exact pin on the core.
That keeps the library installable in a process that wants a handful of aggregates and nothing else.

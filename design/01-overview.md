# blue-data-ops — Overview

## Objective

An agentic platform needs data work it can name, version, plan over, and run without the platform runtime being present.
Blue's operator contract gives that work a shape: a list of record groups in, a list of record groups out, with a declared attribute schema in front of it.
The platform implementation of that contract depends on the platform runtime, including its service clients, synchronization bus, and remote routing.
This package provides the operator surface without those runtime dependencies.
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

Operator IDs include an exact version.
Registrations cannot be overwritten or removed, and `resolve()` accepts only fully pinned IDs.
Discovery accepts fuzzy queries but returns pinned cards.

Operator calls report invalid input, transform failures, and timeouts in `ExecMeta.errors`, with output normalized to `[[]]`.
Planning raises `PlanningError` with the same structured record because no partial pipeline exists to carry it.
Planning is the only package surface that raises to report a recoverable outcome.

The core declares five runtime dependencies.
NumPy, scikit-learn, sentence-transformers, LiteLLM, and the OpenAI SDK are optional extras imported at the point of use.
A missing extra therefore produces an `EXECUTION_FAILED` record at call time instead of breaking package import.

External dependencies have dedicated boundaries.
`blue-data` is imported only in `data/`, whose seam handles argument-order and search-score differences.
LiteLLM sits behind `LLMClient`.
The OpenAI plan generator uses a separate SDK seam for structured output; it is the package's only OpenAI SDK import.

Registry membership alone does not make a card plannable.
The planner admits the active selection by default or an explicit allowlist, and the compiler rechecks card identity, provenance, and lifecycle against the live registry after generation.
A generator cannot introduce an operator that the caller did not allow.

The core distribution declares no console entry point or HTTP server.
The MCP adapter and `blue-ops` command are separate distributions with their own versions and exact core pins.
The library therefore remains installable without either interface's dependencies.

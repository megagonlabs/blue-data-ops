# blue-data-ops — Repo Organization

Where every file in the repository lives and why it lives there, one level deeper than the tree in the root [`README.md`](../README.md).

## Directory Tree

```text
blue-data-ops/
│
├── .gitignore                              # ignore rules for the whole repository: caches, build output, environments
├── CHANGELOG.md                            # one entry per released version, newest first
├── LICENSE                                 # BSD 3-Clause with a NOTICE clause, one copy for all three
├── README.md                               # entry point: one-line description, doc links, layout, quickstart, package table
├── ruff.toml                               # repository-root lint scope: extends lib/pyproject.toml so examples/ stays linted
│
├── design/                                 # why the system is shaped this way; written for contributors and maintainers
│   ├── 01-overview.md                      # objective, capabilities, design philosophy
│   ├── 02-scenarios.md                     # the ways the library is actually used, each with runnable code
│   ├── 03-high-level-architecture.md       # the components, their boundaries, and the allowed import directions
│   ├── 04-detailed-architecture.md         # per-component internals and control flow
│   ├── 05-software-stack.md                # language floor, runtime dependencies, optional extras
│   ├── 06-library.md                       # key classes and functions, one section per module
│   ├── 07-repo-organization.md             # this file: the tree and the reasoning behind it
│   ├── 08-coding-style.md                  # tooling, type hints, naming, imports, docstrings, comments, error handling
│   ├── 09-api-interface-spec.md            # the Python and MCP interface contracts
│   ├── 10-data-model.md                    # record, group, card, plan, and result shapes
│   ├── 11-testing-strategy.md              # test levels, doubles and stubs, and how to run each suite
│   ├── 12-deployment-ops.md                # versioning, packaging, install paths, and what is not automated
│   ├── 13-decision-log.md                  # cross-cutting and superseding architecture decisions
│   ├── design-process.md                   # guidance for maintaining the design documents
│   └── repo-organization-template.md       # conventions used by this repository's layout
│
├── docs/                                   # how to use it; written for users, and kept in step with current behavior
│   ├── README.md                           # doc index, grouped by what the reader is trying to do
│   ├── quickstart.md                       # shortest verified path from an empty environment to a result
│   ├── installation.md                     # the install methods this repository supports, with extras
│   ├── features.md                         # what the library can do, capability by capability
│   ├── guide.md                            # task-oriented walkthrough of the library
│   ├── api-reference.md                    # the public Python surface, module by module
│   ├── architecture.md                     # the user-facing subset of the design architecture documents
│   ├── extending.md                        # writing an operator, a registry provider, or a plan generator
│   ├── mcp.md                              # synced copy of the MCP adapter README
│   ├── cli.md                              # synced copy of the blue-ops README
│   └── api.md                              # placeholder: no REST API is built
│
├── examples/                               # runnable scripts, grouped by purpose
│   ├── README.md                           # per script: what it demonstrates, its run command, its requirements
│   ├── _sqlite_demo.py                     # shared SQLite registry helper; imported by scripts, not run on its own
│   ├── coverage.json                       # checked map from each script to the exact operator IDs it exercises
│   ├── quickstart/                         # the scripts to run first on a fresh install
│   ├── feature-demos/                      # one capability per script
│   └── integration-demos/                  # scripts that combine more than one subsystem
│                                           # each offline script has its captured stdout beside it as <script>.output.txt
│
├── lib/                                    # the core distribution, blue-data-ops
│   ├── COMPATIBILITY.md                    # source of truth for compatibility and migration boundaries
│   ├── MANIFEST.in                         # the extra files carried in the source distribution
│   ├── OPERATORS.md                        # generated per-operator reference; never hand-edited
│   ├── README.md                           # package README, and the long description in wheel metadata
│   ├── pyproject.toml                      # package metadata, dependencies, and every tool configuration
│   ├── .gitignore                          # package-local ignore rules for the environment and caches
│   │
│   ├── scripts/                            # packaging and maintenance scripts; not installed with the package
│   │   ├── build.sh                        # python -m build
│   │   ├── install.sh                      # editable install, resolving blue-data from its checkout first
│   │   ├── publish.sh                      # twine upload dist/*
│   │   ├── generate_operator_reference.py  # regenerates OPERATORS.md from the registry and generator fixtures
│   │   └── check_real_llm_install.py       # fails if litellm resolves to the test stub instead of a real install
│   │
│   ├── src/                                # src layout, so the package is never importable from the project root
│   │   └── blue_data_ops/                  # the importable package
│   │       ├── __init__.py                 # the public surface: operator classes, result types, registry seam, utils
│   │       ├── _deprecation.py             # the retained public warning category
│   │       ├── py.typed                    # PEP 561 marker: the package ships inline types
│   │       │
│   │       ├── operators/                  # implementations, the registry, and the shared vocabulary
│   │       │   ├── operator.py             # the Operator base: apply, invoke, validate, and the run() boundary
│   │       │   ├── registry.py             # OperatorRegistry, OperatorCard, and the three registry factories
│   │       │   ├── types.py                # record, attribute, result, and error types
│   │       │   ├── _discovery.py           # the closed six-axis tag model and its fail-fast validation
│   │       │   ├── embedding_discovery.py  # caller-supplied embedding index over the catalog
│   │       │   ├── _metadata.py            # attribute-spec projection and Blue signature enrichment
│   │       │   ├── _coercion.py            # shared lax value coercion
│   │       │   ├── _record_matching.py     # shared record comparison for the join and set operators
│   │       │   ├── _query_results.py       # normalization of the registry's query result shapes
│   │       │   ├── _outcomes.py            # the shared outcome-operator behavior
│   │       │   ├── <name>_operator.py      # one module per operator, such as select_operator.py
│   │       │   ├── sklearn_estimator.py    # the one operator module without the _operator suffix
│   │       │   ├── _<name>_outcome.py      # the outcome subclass for one operator active at @3.0.0
│   │       │   └── operator_discover_operator.py  # operator-discovery operator class; no registry card
│   │       │
│   │       ├── operator_skills/            # authored resources keyed by exact operator ID
│   │       │   ├── loader.py               # OperatorSkillLoader: digest-checked, size-bounded resource reads
│   │       │   ├── _index.json             # the closed index from exact operator ID to its manifest
│   │       │   └── <name>/<version>/       # one resource package: Operator.md, examples.md, manifest.json
│   │       │
│   │       ├── plan/                       # pipeline model, planning, execution
│   │       │   ├── pipeline.py             # DataPipeline, Plan, Node, Entity: the portable graph record
│   │       │   ├── planner.py              # PipelinePlanner, the generator protocol, and the rule templates
│   │       │   ├── executor.py             # PipelineExecutor and the preflight that runs before any operator
│   │       │   ├── context.py              # the bounded read-only data context and the planning error record
│   │       │   ├── openai_generator.py     # OpenAIPlanGenerator, the one direct provider SDK seam
│   │       │   ├── types.py                # node, entity, and status constants, plus the sync callback protocol
│   │       │   └── _schemas/               # packaged JSON schema resources, read through importlib.resources
│   │       │
│   │       ├── data/                       # the only place blue-data is imported
│   │       │   ├── provider.py             # DataRegistryProvider, BlueDataRegistryProvider, resolve_registry
│   │       │   └── registry_seam.py        # RegistrySeam: the compatibility facade over a blue-data registry
│   │       │
│   │       ├── llm/                        # provider-backed request support
│   │       │   ├── client.py               # LLMClient, usage records, retry, caching, rate limiting
│   │       │   ├── provider.py             # client resolution and the opt-in per-config client cache
│   │       │   ├── templating.py           # message construction and JSONPath output extraction
│   │       │   └── errors.py               # LLMError, for transport failures and rejected adapter config
│   │       │
│   │       ├── tools/                      # Blue tool compatibility
│   │       │   └── tool.py                 # Tool: function plus live properties, validation, signature metadata
│   │       │
│   │       └── utils/                      # Blue-compatible helpers that do not import blue
│   │           ├── type_utils.py           # string type parsing, dynamic Pydantic models, value-type validation
│   │           ├── tool_utils.py           # annotation and signature conversion
│   │           ├── json_utils.py           # JSON merge and JSONPath query and set
│   │           ├── uuid_utils.py           # UUID and canonical-ID helpers
│   │           └── string_utils.py         # Template and Jinja substitution
│   │
│   └── tests/                              # the library test suite; see 11-testing-strategy.md
│       ├── conftest.py                     # installs the sentence-transformers stub before any lazy model import
│       ├── unit/                           # one subdirectory per source package that has its own tests
│       ├── doubles/                        # in-memory doubles for the data seam, recording every call
│       ├── stubs/                          # deterministic stand-ins for the optional heavy dependencies
│       ├── fixtures/                       # JSON reference documents and reference-generator inputs
│       └── installed/                      # checks that run against a built wheel or an installed package
│
└── platform/                               # interface adapters, one publishable distribution per subdirectory
    ├── ops-cli/                            # the command line distribution, blue-data-ops-cli
    │   ├── README.md                       # source of truth for the command: install, tree, configuration, formats, exit codes
    │   ├── pyproject.toml                  # package metadata, the exact core pin, the blue-ops entry point, tool configuration
    │   ├── scripts/                        # build.sh, install.sh, publish.sh, as in every distribution
    │   ├── src/                            # same src layout as the core
    │   │   └── blue_data_ops_cli/          # the importable command package
    │   │       ├── __init__.py             # the package docstring; the command tree is reached through commands.py
    │   │       ├── commands.py             # the root group, the five components, and the shared root options
    │   │       ├── catalog.py              # blue-ops catalog: which registry view a command reads
    │   │       ├── operator.py             # blue-ops operator: list, search, inspect, run
    │   │       ├── resource.py             # blue-ops operator resource: the package that ships beside an operator
    │   │       ├── pipeline.py             # blue-ops pipeline: plan, store, inspect, run
    │   │       ├── profile.py              # blue-ops profile: profiles and their configuration
    │   │       ├── metadata.py             # blue-ops metadata: what is installed and what resolves
    │   │       ├── config.py               # option translation, the error taxonomy, and the library seams
    │   │       ├── configstore.py          # the profile store: INI under ~/.blue-ops, atomic writes, 0600
    │   │       ├── formats.py              # one renderer for table, json, and nl
    │   │       ├── records.py              # record-bundle and KEY=VALUE parsing
    │   │       ├── mask.py                 # one notion of a credential, for every channel that echoes text back
    │   │       ├── py.typed                # PEP 561 marker
    │   │       └── profile_spec.json       # the declared configuration parameters, their casts and defaults
    │   └── tests/unit/                     # command tests: surface, formats, errors, storage, masking, README
    └── ops-mcp/                            # the MCP distribution, blue-data-ops-mcp
        ├── README.md                       # source of truth for the adapter: install, embed, serve, tool contract
        ├── pyproject.toml                  # adapter metadata, the exact core pin, and tool configuration
        ├── scripts/                        # build.sh, install.sh, publish.sh, as in every distribution
        ├── src/                            # same src layout as the core
        │   └── blue_data_ops_mcp/          # the importable adapter package
        │       ├── __init__.py             # lazy public surface, so importing the package costs nothing
        │       ├── registration.py         # the operator selections and the tool registration that binds them
        │       ├── schema.py               # the wire projection: input and output schemas per tool
        │       ├── server.py               # server construction and the streamable HTTP transport
        │       └── py.typed                # PEP 561 marker
        └── tests/                          # adapter tests: registration, schema, invocation, protocol, portability
```

---

## Layout Rationale

### `README.md`, `CHANGELOG.md`, `LICENSE`, `.gitignore`, and `ruff.toml`

Five regular files sit at the root. `README.md`, `CHANGELOG.md`, and `LICENSE` are the ones a reader meets before choosing a direction; `.gitignore` and `ruff.toml` exist for tooling rather than for reading.
`CHANGELOG.md` carries one entry per released version, newest first, and names the three distributions a version moved.
`LICENSE` is a BSD 3-Clause licence with a fourth attribution and NOTICE clause, and it covers all three distributions from the root, which is how the rest of the family carries it. It is byte-identical to the copies `blue-data-kb-source` and `blue-data-llm-source` carry.
`README.md` states what the package is, links [`docs/`](../docs/README.md) and [`examples/README.md`](../examples/README.md), and carries a quickstart that runs on a clean checkout.
`.gitignore` covers the whole repository, and `lib/.gitignore` adds the package-local entries for the environment and caches that live under `lib/`.
Keeping both ignore files means a contributor can create `lib/.venv` without the root file having to know that packages exist.
`ruff.toml` carries no rules of its own: it extends [`lib/pyproject.toml`](../lib/pyproject.toml) and sets `src` so that `examples/`, which sits outside every package, is linted under the same configuration. [08-coding-style.md](08-coding-style.md) owns what the tools enforce.

### `design/`

Contributor-facing design rationale, numbered in reading order.
A document here explains the decisions behind the system rather than tracking every behavior change.
The numbering runs 01 through 13 with no gaps. [design-process.md](design-process.md) explains how to
maintain the set, and [repo-organization-template.md](repo-organization-template.md) summarizes the
layout conventions used here. [13-decision-log.md](13-decision-log.md) is reserved for decisions that
cross document boundaries or supersede an earlier architecture decision.

### `docs/`

`docs/` contains unnumbered user documentation indexed by [`docs/README.md`](../docs/README.md).
These pages must track current code behavior, which is the opposite update rule from `design/` — when the two disagree, the code and `docs/` are right and the design document is stale.
[`docs/mcp.md`](../docs/mcp.md) and [`docs/cli.md`](../docs/cli.md) mirror their adapter READMEs.
[`docs/api.md`](../docs/api.md) states that the repository provides no REST API.

### `examples/`

Runnable scripts live at the repository root rather than inside `lib/`; they are repository examples and do not ship in the library distribution.
The three subdirectories group by purpose: the first scripts to run, single-capability demonstrations, and scripts that combine more than one subsystem.
[`examples/README.md`](../examples/README.md) is the source of truth for which script sits where, what each one demonstrates, and which ones need an extra or a credential.
`_sqlite_demo.py` stays at the top of the tree with a leading underscore, marking it as shared setup rather than an example in its own right.
`coverage.json` maps each runnable script to the exact operator IDs it exercises.
Tests compare the map with the IDs referenced by each script.

### `lib/`

`lib/` contains the core distribution and all operator behavior.
The `src/` layout inside `lib/` keeps `blue_data_ops` from being importable just because a shell happens to be sitting in `lib/`.
Anything that imports it has either installed it or put `src` on the path deliberately, which is what `pythonpath` in [`lib/pyproject.toml`](../lib/pyproject.toml) does for the test suite.
Everything a wheel installs is under `lib/src/blue_data_ops/`.
`OPERATORS.md`, `COMPATIBILITY.md`, and `scripts/` sit beside `src/` under `lib/` and reach a user through the source distribution rather than the wheel, because they are reference and maintenance material rather than runtime code; `MANIFEST.in` is what puts them there.

`lib/scripts/` holds five scripts, all run by hand:

| Script | Purpose |
|---|---|
| `build.sh` | `python -m build` from `lib/`, writing the wheel and the source distribution into `lib/dist/` |
| `install.sh` | Installs `blue-data` from the sibling checkout, then this package editable with its `dev` extra; `BLUE_DATA_PATH` overrides where it looks |
| `publish.sh` | `twine upload dist/*` from `lib/` |
| `generate_operator_reference.py` | Regenerates `OPERATORS.md` from the active registry and generator fixtures; `--check` verifies the committed file is current without rewriting it |
| `check_real_llm_install.py` | Exits non-zero when `litellm` resolves to the test stub, so a provider-backed run cannot silently execute against a fake |

The three shell scripts are the family's convention and every distribution in this repository carries a copy, so a contributor moving between packages runs the same three commands.

### `platform/`

One subdirectory per external interface, each its own publishable distribution with its own version and its own exact dependency on the core.
Two exist: `ops-cli/` and `ops-mcp/`, named `<family>-<service>` so a directory name reads the same as the service it ships.
Neither contains operator behavior; every tool and every command is a projection of `Operator.run()`.
Keeping them outside `lib/` means installing the core alone does not install MCP or CLI dependencies.
A third interface arrives as a sibling directory here rather than as an extra on the core distribution.

### Module-to-architecture mapping

The components are named and bounded in [03-high-level-architecture.md](03-high-level-architecture.md); this table says which files implement each one.

| Module | Architecture component |
|---|---|
| `operators/operator.py`, `operators/types.py`, `operators/_metadata.py`, `tools/tool.py` | Operator Runtime — the call boundary, the result and error types, the Blue metadata surface |
| `operators/<name>_operator.py`, `operators/sklearn_estimator.py`, `operators/_<name>_outcome.py` | Operator Catalog — the built-in implementations and their outcome subclasses |
| `operators/registry.py`, `operators/_discovery.py`, `operators/embedding_discovery.py` | Operator Registry — pinned identity, immutable registration, discovery scoring, the tag vocabulary |
| `operator_skills/loader.py`, `operator_skills/_index.json`, `operator_skills/<name>/<version>/` | Operator Skill Store — the exact-version resource packages and their digest verification |
| `plan/pipeline.py`, `plan/types.py` | Plan — the portable pipeline record and its node, entity, and status vocabulary |
| `plan/planner.py`, `plan/context.py`, `plan/openai_generator.py`, `plan/_schemas/` | Plan — discovery, bounded data context, candidate generation, selection, compilation |
| `plan/executor.py` | Plan — preflight and ordered execution |
| `data/provider.py`, `data/registry_seam.py` | Data Registry Seam — the package's only `blue-data` import boundary |
| `llm/client.py`, `llm/provider.py`, `llm/templating.py`, `llm/errors.py` | LLM Client — templating, dispatch, retry, caching, rate limiting, usage records |
| `utils/` | Utilities — Blue-compatible type, signature, JSON, UUID, and string helpers |
| `platform/ops-mcp/src/blue_data_ops_mcp/registration.py` | MCP Adapter — the operator selections and tool registration |
| `platform/ops-mcp/src/blue_data_ops_mcp/schema.py` | MCP Adapter — the wire projection of attributes and results |
| `platform/ops-mcp/src/blue_data_ops_mcp/server.py` | MCP Adapter — server construction and transport |
| `platform/ops-cli/src/blue_data_ops_cli/commands.py` and the five component modules | CLI — the command tree and one module per component |
| `platform/ops-cli/src/blue_data_ops_cli/config.py`, `configstore.py` | CLI — option translation, the error taxonomy, and the profile store |
| `platform/ops-cli/src/blue_data_ops_cli/formats.py`, `records.py`, `mask.py` | CLI — rendering, input parsing, and credential masking |

### Naming inside `operators/`

The directory is flat on purpose, and the filename carries the role.

| Pattern | Holds |
|---|---|
| `<name>_operator.py` | One operator implementation, and for a registered operator its module-level `DISCOVERY` metadata |
| `_<name>_outcome.py` | The outcome subclass layered over that implementation for the operator's `@3.0.0` card |
| `_<shared concern>.py` | Behavior more than one operator needs, such as `_coercion.py` and `_record_matching.py` |
| `operator.py`, `types.py`, `_discovery.py` | The base class, the shared vocabulary, and the discovery spec. A module that defines an operator class from scratch imports all three. The 21 `_*_outcome.py` modules extend their `@2.0.0` counterpart instead, so they import `types.py` and the class they extend, and only three of them import `_discovery.py`. `operator_discover_operator.py` carries no registry card and declares no discovery record |

A reader who wants `select` opens `select_operator.py` without consulting an index, and the private prefix marks every module that is an implementation detail rather than part of the import surface.
`sklearn_estimator.py` is the one break in the pattern, kept because renaming a module is a change to a documented import path.

### `lib/tests/`

Tests live beside the package they cover, under `lib/tests/`, and each interface distribution carries its own suite with its own fixtures rather than importing the library's.

```text
lib/tests/
├── conftest.py            # loads the sentence-transformers stub before an operator reaches its lazy model import
├── unit/                  # one subdirectory per source package: operators, operator_skills, plan, data, llm, utils
│   ├── test_examples.py             # runs the offline example scripts and syntax-checks the provider-backed ones
│   ├── test_operator_reference.py   # asserts OPERATORS.md equals the generator's output
│   ├── test_readme_usage.py         # executes the marked code fences in the shipped READMEs
│   └── test_deprecation.py          # the retained warning category and the absence of the removed surfaces
├── doubles/               # in-memory doubles for the data seam that record every boundary call
├── stubs/                 # litellm and sentence-transformers stand-ins, resolved for both pytest and Pyright
├── fixtures/              # JSON reference documents, including reference-generator inputs
└── installed/             # wheel and installed-package checks, importable by tests and runnable by hand
```

`tests/unit/` mirrors the source layout so that finding the tests for a module is the same operation as finding the module. Six of the seven source packages have a matching directory; `tools/` has none, and the `Tool` surface is covered from the operator and portability suites instead.
Each mirrored subdirectory except `utils/` carries an `__init__.py`, which keeps the shared helper modules importable as `tests.unit.<package>.<helper>` and keeps identically-named test files in different directories from colliding.
`tests/doubles/`, `tests/stubs/`, `tests/fixtures/`, and `tests/installed/` hold no test functions; `testpaths = ["tests/unit"]` in [`lib/pyproject.toml`](../lib/pyproject.toml) is what keeps them out of collection while `pythonpath` keeps them importable.
That is as far as this document goes into the suite: [11-testing-strategy.md](11-testing-strategy.md) owns what each level checks and how to run it, and wins where the two overlap.

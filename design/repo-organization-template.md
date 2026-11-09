# Repository layout conventions

This repository contains one core Python distribution and two adapters. The complete tree and the
rationale for individual files are in [07-repo-organization.md](07-repo-organization.md). This page
records the layout conventions contributors should preserve when adding a package or interface.

```text
blue-data-ops/
├── README.md
├── LICENSE
├── design/                         # architecture and maintenance rationale
├── docs/                           # current user documentation
├── examples/                       # runnable programs and captured offline output
├── lib/                            # blue-data-ops core distribution
│   ├── pyproject.toml
│   ├── src/blue_data_ops/
│   └── tests/
└── platform/
    ├── ops-cli/                    # blue-data-ops-cli distribution
    │   ├── pyproject.toml
    │   ├── src/blue_data_ops_cli/
    │   └── tests/
    └── ops-mcp/                    # blue-data-ops-mcp distribution
        ├── pyproject.toml
        ├── src/blue_data_ops_mcp/
        └── tests/
```

## Conventions

- Business logic belongs in `lib/src/blue_data_ops/`. Adapters translate their external interface
  to the core library instead of implementing operator behavior themselves.
- Each distribution has its own `pyproject.toml`, source tree, tests, and release scripts. There is
  no root Python distribution.
- Python packages use the `src/` layout and include `py.typed` when they expose typed interfaces.
- Tests stay with the distribution they exercise. The library test tree mirrors the library source
  tree; adapter tests cover only that adapter and its boundary with the library.
- A new deployable interface belongs under `platform/<family>-<service>/` and uses a package name
  derived from its distribution name. Do not add a service directory until the service exists.
- User documentation in `docs/` describes current behavior. When an adapter page mirrors an adapter
  README, update both copies together.
- Design documents explain architecture and rationale. Cross-cutting or superseding decisions go in
  [13-decision-log.md](13-decision-log.md).

These conventions describe the current repository. A structural change should update this page and
[07-repo-organization.md](07-repo-organization.md) in the same change.

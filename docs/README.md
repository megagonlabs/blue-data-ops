# Documentation

## Start here

| Doc | Read this if you want to... |
|---|---|
| [quickstart.md](quickstart.md) | Get an operator, a pipeline, and the planner running in the next five minutes |
| [installation.md](installation.md) | Install the library, the MCP adapter, or the `blue-ops` command from a source checkout or a built wheel, with every optional extra |
| [features.md](features.md) | See what the library can do, at a glance, with a short example per feature |
| [examples/](../examples/README.md) | Run something — twelve whole programs, grouped into a first working result, one capability in depth, and two subsystems wired together |

## Using it

| Doc | Read this if you want to... |
|---|---|
| [guide.md](guide.md) | Work through the Python library task by task — execution, error handling, discovery, registry-backed tables, pipelines, planning, migration from 2.x |
| [api-reference.md](api-reference.md) | Look up an exact export, method signature, or result type |
| [mcp.md](mcp.md) | Serve the 33 operators as MCP tools to an MCP client |
| [cli.md](cli.md) | Run an operator, search the catalog, or run a stored pipeline from a shell, with `blue-ops` |
| [api.md](api.md) | REST API — not built; the page says where that boundary would go if it were |

## Building on it

| Doc | Read this if you want to... |
|---|---|
| [architecture.md](architecture.md) | Understand how the pieces fit together — the component diagram and the path data takes through `run()`, the executor, and the planner |
| [extending.md](extending.md) | Write your own operator, registry, plan generator, or embedder against the package seams |

## Authoritative references

These pages describe current behavior.
For overlapping topics, use the following authoritative files.

| File | Owns |
|---|---|
| [`lib/README.md`](../lib/README.md) | requirements, install, and minimal usage for the `blue-data-ops` package |
| [`lib/OPERATORS.md`](../lib/OPERATORS.md) | per-operator metadata, attribute schemas, accepted outcomes, and the tag taxonomy; generated from the registry, never hand-edited |
| [`lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md) | the 3.0 migration boundary and every deliberate difference from Blue's reference behavior |
| [`platform/ops-mcp/README.md`](../platform/ops-mcp/README.md) | the MCP adapter: install, embedding, serving, and tool shape |
| [`platform/ops-cli/README.md`](../platform/ops-cli/README.md) | the `blue-ops` command: install, the command tree, configuration, storage, formats, and exit codes |

[mcp.md](mcp.md) and [cli.md](cli.md) are synced copies of the last two and name their source at the top.
Everything else here is written for this directory.

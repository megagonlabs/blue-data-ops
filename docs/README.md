# Documentation

Landing page for all documentation in `blue-data-ops` — what to read depends on what you are doing.

## Start here

| Doc | Read this if you want to... |
|---|---|
| [quickstart.md](quickstart.md) | Get an operator, a pipeline, and the planner running in the next five minutes |
| [installation.md](installation.md) | Install the library or the MCP adapter from a source checkout or a built wheel, with every optional extra |
| [features.md](features.md) | See what the library can do, at a glance, with a short example per feature |
| [examples/](../examples/README.md) | Run something — eleven whole programs, grouped into a first working result, one capability in depth, and two subsystems wired together |

## Using it

| Doc | Read this if you want to... |
|---|---|
| [guide.md](guide.md) | Work through the Python library task by task — execution, error handling, discovery, registry-backed tables, pipelines, planning, migration from 2.x |
| [api-reference.md](api-reference.md) | Look up an exact export, method signature, or result type |
| [mcp.md](mcp.md) | Serve the 33 operators as MCP tools to Claude or another MCP client |
| [api.md](api.md) | REST API — not built; the page says where that boundary would go if it were |

## Building on it

| Doc | Read this if you want to... |
|---|---|
| [architecture.md](architecture.md) | Understand how the pieces fit together — the component diagram and the path data takes through `run()`, the executor, and the planner |
| [extending.md](extending.md) | Write your own operator, registry, plan generator, or embedder against the package seams |

## Source of truth

These pages track the behavior of the code as it stands, not the plan for it.
A page that has drifted from the code is a bug in the page.

Four files outside this directory own their subjects.
Where a page here repeats one of them, the file below wins.

| File | Owns |
|---|---|
| [`lib/README.md`](../lib/README.md) | requirements, install, and minimal usage for the `blue-data-ops` package |
| [`lib/OPERATORS.md`](../lib/OPERATORS.md) | per-operator metadata, attribute schemas, accepted outcomes, and the tag taxonomy; generated from the registry, never hand-edited |
| [`lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md) | the 3.0 migration boundary and every deliberate difference from Blue's reference behavior |
| [`platform/mcp/README.md`](../platform/mcp/README.md) | the MCP adapter: install, embedding, serving, and tool shape |

[mcp.md](mcp.md) is a synced copy of the last of those and names it at the top.
Everything else here is written for this directory.
A doc that exists but is missing from the tables above is a bug in [this index](README.md).

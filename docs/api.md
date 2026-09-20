# blue-data-ops REST API

**Not yet built.** There is no `platform/api/` directory in this repository, and no HTTP framework appears in any package's dependencies — see the interface table in [architecture.md](architecture.md#platform-layer).

A sketch of what a REST adapter over the operator surface would look like — resources, request and response bodies, and the error envelope — lives in [`design/09-api-interface-spec.md`](../design/09-api-interface-spec.md).
Treat it as design intent rather than a contract anything implements today.

The same operations are reachable now through:

- the [Python library](api-reference.md), by resolving an operator from a registry and calling `run()`;
- the [MCP server](mcp.md), for tool-calling clients; or
- the [`blue-ops` command](cli.md), from a shell or a script.

This page gets the real endpoint reference once `platform/api/` exists, following the pattern [mcp.md](mcp.md) already uses.

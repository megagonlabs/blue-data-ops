# blue-data-ops REST API

No REST API is currently implemented.
There is no `platform/api/` directory, and no package depends on an HTTP framework.
See the interface table in [architecture.md](architecture.md#platform-layer).

The design sketch for a REST adapter, including resources, request and response bodies, and the error envelope, is in [`design/09-api-interface-spec.md`](../design/09-api-interface-spec.md).
Treat it as design intent rather than a contract anything implements today.

The same operations are reachable now through:

- the [Python library](api-reference.md), by resolving an operator from a registry and calling `run()`;
- the [MCP server](mcp.md), for tool-calling clients; or
- the [`blue-ops` command](cli.md), from a shell or a script.

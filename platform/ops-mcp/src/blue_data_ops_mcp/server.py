"""The `blue-data-ops` MCP server: one FastMCP server carrying the operator catalog.

`create_server()` registers one tool per entry in `registration.ACTIVE_OPERATOR_IDS`, each
named `ops_` plus the core operator's logical name, and each returning the one structured
envelope in `schema.RunResult`. `serve()` and the `blue-data-ops-mcp` console command run
that server over stateful streamable HTTP, bound by default to loopback at `127.0.0.1:8000`
on path `/mcp`. Review network exposure before changing the host: a tool call carries
provider settings in its `properties` argument, so loopback is what keeps that reachable
only from the host the server runs on.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from blue_data_ops.operators import OperatorRegistry
from mcp.server.fastmcp import FastMCP

from blue_data_ops_mcp import __version__
from blue_data_ops_mcp.registration import freeze_deployment, register_snapshot

SERVER_NAME = "blue-data-ops"

# What a client reads during the handshake. The three things a caller otherwise gets wrong:
# that the arguments are two open objects rather than one argument per operator attribute,
# that a failed operator run is still a successful call, and that the registry-backed and
# provider-backed tools are configured through `properties` and not through `attributes`.
SERVER_INSTRUCTIONS = (
    "Blue Data Operators as MCP tools: record-level select, join, set, aggregate, text, "
    "vector, machine-learning, and LLM operators over one shared result envelope. Every tool "
    "name starts with ops_, takes input_data as a list of record groups plus an attributes "
    "object of operator arguments, and returns output_data, output_attributes, and exec_meta. "
    "An operator outcome that was rejected, failed, timed out, or came back empty is still a "
    "successful call, with the detail in exec_meta.errors; only an unknown tool or a malformed "
    "top-level argument is an MCP error. Backend configuration travels in the separate "
    "properties argument: the registry-backed tools return nothing without a data registry "
    "named there, and ops_classify, ops_cluster, and ops_sklearn_estimator take their "
    "estimator from properties.algorithm."
)


def create_server(
    *,
    registry: OperatorRegistry | None = None,
    operator_ids: Iterable[str] | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    path: str = "/mcp",
) -> FastMCP[Any]:
    snapshot = freeze_deployment(registry=registry, operator_ids=operator_ids)
    server: FastMCP[Any] = FastMCP(
        SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
        host=host,
        port=port,
        streamable_http_path=path,
        json_response=False,
        stateless_http=False,
    )
    # FastMCP takes no version argument, and the server it builds reports the MCP SDK's own
    # version when it has none of its own. Every release of this package would then tell a
    # client its SDK version, while 1.0.0 and 0.12.0 serve different tool sets.
    server._mcp_server.version = __version__  # pyright: ignore[reportPrivateUsage]
    register_snapshot(server, snapshot)
    return server


def serve(
    *,
    registry: OperatorRegistry | None = None,
    operator_ids: Iterable[str] | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    path: str = "/mcp",
) -> None:
    server = create_server(
        registry=registry,
        operator_ids=operator_ids,
        host=host,
        port=port,
        path=path,
    )
    server.run(transport="streamable-http")


def main() -> None:
    """Console entry point for `blue-data-ops-mcp`: serve the default selection."""
    serve()


if __name__ == "__main__":
    main()

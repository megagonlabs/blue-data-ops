"""MCP tools over guarded HTTP, or the SDK's in-process and stdio transports.

HTTP defaults to 127.0.0.1:8010/mcp. The shared blue-data guards require an API
key and reject browser-simple modifying requests on both HTTP transports.
Provider configuration belongs to the deployment; authenticated tool callers
can use it and may incur costs.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from blue_data.registry.data_registry import (  # pyright: ignore[reportMissingTypeStubs]
    DataRegistry,
)
from blue_data_ops.data.registry_seam import RegistrySeam
from blue_data_ops.operators import OperatorRegistry
from mcp.server.fastmcp import FastMCP

from blue_data_ops_mcp import __version__
from blue_data_ops_mcp._http import GuardedFastMCP, resolve_http_bind
from blue_data_ops_mcp.data_registry import DeploymentRegistry
from blue_data_ops_mcp.registration import freeze_deployment, register_snapshot

SERVER_NAME = "blue-data-ops"

SERVER_INSTRUCTIONS = (
    "Blue Data Operators as MCP tools over one shared result envelope. Every tool name "
    "starts with ops_, takes input_data as a list of record groups plus an attributes "
    "object, and returns output_data, output_attributes and exec_meta. Operator errors "
    "remain successful MCP calls; inspect exec_meta.errors. Registry tools use one "
    "deployment-owned registry configured by the host or BLUE_DATA_REGISTRY_STORE / "
    "BLUE_DATA_SOURCES_CONFIG. Caller registry objects and naming keys cannot select it. "
    "Source loading may connect, enrich and sync metadata; create/insert tools can persist "
    "writes even after failure or timeout. Registry calls are serialized per server. "
    "Initial construction is unbounded and execution.timeout_seconds does not cover it; "
    "a hung build or unbounded call stalls this server's registry lane. Configure backend "
    "timeouts and a per-call execution.timeout_seconds for the later operator wait. "
    "An operator timeout returns to the caller but holds this server's registry lane until "
    "the worker finishes; later registry calls then run normally. Late non-daemon workers "
    "may delay process exit. Cancellation does not stop running workers. "
    "Other tools and servers continue; a registry shared across servers has no cross-server "
    "serialization. Stock SQL tools generate only and have no SQL executor; execution needs "
    "a host-configured read-only capability. Estimator tools use properties.algorithm."
)


def create_server(
    *,
    registry: OperatorRegistry | None = None,
    data_registry: RegistrySeam | DataRegistry | None = None,
    operator_ids: Iterable[str] | None = None,
    host: str | None = None,
    port: int | None = None,
    path: str = "/mcp",
) -> FastMCP[Any]:
    host, port = resolve_http_bind(host, port)
    snapshot = freeze_deployment(registry=registry, operator_ids=operator_ids)
    server: FastMCP[Any] = GuardedFastMCP(
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
    register_snapshot(server, snapshot, deployment=DeploymentRegistry(data_registry))
    return server


def serve(
    *,
    registry: OperatorRegistry | None = None,
    data_registry: RegistrySeam | DataRegistry | None = None,
    operator_ids: Iterable[str] | None = None,
    host: str | None = None,
    port: int | None = None,
    path: str = "/mcp",
) -> None:
    server = create_server(
        registry=registry,
        data_registry=data_registry,
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

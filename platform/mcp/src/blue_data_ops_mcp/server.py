from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from blue_data_ops.operators import OperatorRegistry
from mcp.server.fastmcp import FastMCP

from blue_data_ops_mcp.registration import freeze_deployment, register_snapshot


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
        "blue-data-ops",
        host=host,
        port=port,
        streamable_http_path=path,
        json_response=False,
        stateless_http=False,
    )
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

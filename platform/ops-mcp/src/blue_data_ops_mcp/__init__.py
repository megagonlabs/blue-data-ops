from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from blue_data_ops_mcp.registration import (
        ACTIVE_OPERATOR_IDS,
        TOOL_PREFIX,
        V2_OPERATOR_IDS,
    )
    from blue_data_ops_mcp.server import create_server, main, serve

# A literal rather than a read of distribution metadata: the server reports this in the MCP
# handshake, and a source checkout that was never installed has no metadata to read.
__version__ = "1.0.0"

__all__ = [
    "ACTIVE_OPERATOR_IDS",
    "TOOL_PREFIX",
    "V2_OPERATOR_IDS",
    "__version__",
    "create_server",
    "main",
    "serve",
]


def __getattr__(name: str) -> Any:
    if name in {"ACTIVE_OPERATOR_IDS", "TOOL_PREFIX", "V2_OPERATOR_IDS"}:
        from blue_data_ops_mcp.registration import (
            ACTIVE_OPERATOR_IDS,
            TOOL_PREFIX,
            V2_OPERATOR_IDS,
        )

        return {
            "ACTIVE_OPERATOR_IDS": ACTIVE_OPERATOR_IDS,
            "TOOL_PREFIX": TOOL_PREFIX,
            "V2_OPERATOR_IDS": V2_OPERATOR_IDS,
        }[name]
    if name in {"create_server", "main", "serve"}:
        from blue_data_ops_mcp.server import create_server, main, serve

        return {"create_server": create_server, "main": main, "serve": serve}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

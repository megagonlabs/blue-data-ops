from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from blue_data_ops_mcp.registration import ACTIVE_OPERATOR_IDS, V2_OPERATOR_IDS
    from blue_data_ops_mcp.server import create_server, serve

__all__ = ["ACTIVE_OPERATOR_IDS", "V2_OPERATOR_IDS", "create_server", "serve"]


def __getattr__(name: str) -> Any:
    if name in {"ACTIVE_OPERATOR_IDS", "V2_OPERATOR_IDS"}:
        from blue_data_ops_mcp.registration import ACTIVE_OPERATOR_IDS, V2_OPERATOR_IDS

        return {
            "ACTIVE_OPERATOR_IDS": ACTIVE_OPERATOR_IDS,
            "V2_OPERATOR_IDS": V2_OPERATOR_IDS,
        }[name]
    if name in {"create_server", "serve"}:
        from blue_data_ops_mcp.server import create_server, serve

        return {"create_server": create_server, "serve": serve}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

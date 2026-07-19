from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from blue_data_ops_mcp.registration import DEFAULT_OPERATOR_IDS
    from blue_data_ops_mcp.server import create_server, serve

__all__ = ["DEFAULT_OPERATOR_IDS", "create_server", "serve"]


def __getattr__(name: str) -> Any:
    if name == "DEFAULT_OPERATOR_IDS":
        from blue_data_ops_mcp.registration import DEFAULT_OPERATOR_IDS

        return DEFAULT_OPERATOR_IDS
    if name in {"create_server", "serve"}:
        from blue_data_ops_mcp.server import create_server, serve

        return {"create_server": create_server, "serve": serve}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

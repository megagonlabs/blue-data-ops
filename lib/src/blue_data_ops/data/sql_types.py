from __future__ import annotations

from typing import Any, cast


def sql_source_base() -> Any:
    from blue_data.source.sql.sql_source import SQLSource  # pyright: ignore[reportMissingTypeStubs]

    return SQLSource


def is_data_registry(value: Any) -> bool:
    from blue_data.registry.data_registry import DataRegistry  # pyright: ignore[reportMissingTypeStubs]

    return isinstance(value, cast(Any, DataRegistry))

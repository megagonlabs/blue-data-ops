from __future__ import annotations

import sqlite3
from pathlib import Path

from blue_data.registry.data_registry import DataRegistry  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.json.memory_json_source import (  # pyright: ignore[reportMissingTypeStubs]
    MemoryJSONSource,
)
from blue_data.source.sql.sqlite.sqlite_sql_source import (  # pyright: ignore[reportMissingTypeStubs]
    SQLiteDBSource,
)

from blue_data_ops import RegistrySeam

ORDERS = (
    (1, "east", 42.0),
    (2, "west", 125.0),
    (3, "east", 215.0),
    (4, "north", 78.0),
    (5, "south", 160.0),
    (6, "west", 93.0),
    (7, "north", 310.0),
    (8, "south", 54.0),
    (9, "east", 187.0),
    (10, "west", 240.0),
)


def build_demo_registry(directory: str) -> RegistrySeam:
    """Create and index the ten-row SQLite database used by the examples."""

    database_path = Path(directory) / "shop.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, region TEXT, total REAL)")
        connection.executemany("INSERT INTO orders VALUES (?, ?, ?)", ORDERS)

    source = SQLiteDBSource(
        "demo_sqlite",
        properties={"connection": {"database_directory": directory}},
    )
    registry = DataRegistry(store=MemoryJSONSource(), rebuild=False)
    registry.register_source(source)
    registry.sync_source(source.name, recursive=True)
    return RegistrySeam(registry)

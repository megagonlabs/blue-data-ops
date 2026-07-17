"""Executable checks for the README usage examples."""

from __future__ import annotations

from typing import Any

import pytest

blue_data = pytest.importorskip("blue_data")

from blue_data_ops import CreateDatabaseOperator, SelectOperator, resolve_registry  # noqa: E402


def test_readme_select_example() -> None:
    op = SelectOperator()
    data = [[{"name": "a", "score": 3}, {"name": "b", "score": 9}]]
    out = op.invoke(data, {"operand_key": "score", "operand": ">", "operand_val": 5})
    assert out == [[{"name": "b", "score": 9}]]
    assert "operand_key" in op.attributes
    assert op.validate(data, {}) is False


def test_readme_registry_example() -> None:
    class _Source:
        def __init__(self) -> None:
            self.name = "my_source"
            self.properties: dict[str, Any] = {"connection": {"protocol": "memory"}}
            self.databases: list[str] = []

        def create_database(self, database: str, **_kw: Any) -> dict[str, str]:
            self.databases.append(database)
            return {"status": "success"}

        def fetch_databases(self) -> list[str]:
            return list(self.databases)

        def fetch_metadata(self) -> dict[str, Any]:
            return {}

        def fetch_database_metadata(self, database: str) -> dict[str, Any]:
            return {}

        def fetch_database_collections(self, database: str) -> list[str]:
            return []

    seam = resolve_registry({"platform.name": "readme_p", "data_registry.name": "readme_r"})
    assert seam is not None
    seam.register_source(_Source())  # pyright: ignore[reportArgumentType] — structural stub

    result = CreateDatabaseOperator().invoke(
        [[]], {"source": "my_source", "database": "main"}, {"data_registry": seam}
    )
    assert result == [[]]
    assert seam.get_record("main", "database", "/source/my_source") is not None

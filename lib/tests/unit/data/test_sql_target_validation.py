from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from blue_data.registry.data_registry import DataRegistry  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.json.memory_json_source import MemoryJSONSource  # pyright: ignore[reportMissingTypeStubs]
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource  # pyright: ignore[reportMissingTypeStubs]

from blue_data_ops.data.errors import RegistryFailure, RegistryReason
from blue_data_ops.data.registry_seam import RegistrySeam, diagnose_generation_target
from blue_data_ops.llm import LLMError
from blue_data_ops.llm.sql_execution import ReadOnlySQLExecutor


def test_inherited_native_registry_projection_also_validates(tmp_path: Path) -> None:
    class Registry(DataRegistry):
        pass

    (tmp_path / "shop.db").touch()
    registry: Any = Registry(store=MemoryJSONSource(), rebuild=False)
    registry.register_source(
        SQLiteDBSource("local", properties={"connection": {"database_directory": str(tmp_path)}})
    )
    registry.register_source_database("local", "shop")
    registry.register_source_database_collection("local", "shop", "public")
    with pytest.raises(RegistryFailure) as caught:
        diagnose_generation_target(RegistrySeam(registry), "local", "missing", "public")
    assert caught.value.reason is RegistryReason.DATABASE_ABSENT
    executor = ReadOnlySQLExecutor(registry, frozenset({("local", "missing", "public")}))
    with pytest.raises(RegistryFailure) as caught:
        executor.get_schema(("local", "missing", "public"))
    assert caught.value.reason is RegistryReason.DATABASE_ABSENT


def test_custom_seam_keeps_its_own_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Seam(RegistrySeam):
        pass

    (tmp_path / "shop.db").touch()
    registry: Any = DataRegistry(store=MemoryJSONSource(), rebuild=False)
    registry.register_source(
        SQLiteDBSource("local", properties={"connection": {"database_directory": str(tmp_path)}})
    )
    registry.register_source_database("local", "shop")
    registry.register_source_database_collection("local", "shop", "public")
    reads: list[bool] = []

    def denied(*args: Any) -> Any:
        reads.append(True)
        raise AssertionError("custom seam catalog must not be read")

    monkeypatch.setattr(registry, "list_source_databases", denied)
    diagnose_generation_target(Seam(registry), "local", "missing", "public")
    assert reads == []


@pytest.mark.parametrize("custom_schema", [False, True])
def test_executor_projection_failures_keep_fixed_schema_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, custom_schema: bool
) -> None:
    registry: Any = DataRegistry(store=MemoryJSONSource(), rebuild=False)
    registry.register_source(
        SQLiteDBSource("local", properties={"connection": {"database_directory": str(tmp_path)}})
    )
    registry.register_source_database("local", "shop")
    registry.register_source_database_collection("local", "shop", "public")

    def failed(*args: Any, **kwargs: Any) -> Any:
        raise RegistryFailure(RegistryReason.SOURCE_UNAVAILABLE)

    method = "get_data_source_schema" if custom_schema else "list_collection_entities"
    monkeypatch.setattr(registry, method, failed)
    executor = ReadOnlySQLExecutor(registry, frozenset({("local", "shop", "public")}))
    with pytest.raises(LLMError) as caught:
        executor.get_schema(("local", "shop", "public"))
    assert caught.value.code == "sql_execution_failed"


def test_executor_preflight_and_source_identity_precede_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry: Any = DataRegistry(store=MemoryJSONSource(), rebuild=False)
    source = SQLiteDBSource(
        "local", properties={"connection": {"database_directory": str(tmp_path)}}
    )
    registry.register_source(source)
    executor = ReadOnlySQLExecutor(registry, frozenset({("local", "shop", "public")}))
    calls: list[bool] = []

    def denied(*args: Any) -> Any:
        calls.append(True)
        raise AssertionError("catalog read before authorization")

    monkeypatch.setattr(registry, "list_source_databases", denied)
    executor.preflight(("local", "shop", "public"))
    with pytest.raises(LLMError) as caught:
        executor.get_schema(("local", "missing", "public"))
    assert caught.value.code == "sql_target_denied"
    registry.sources["local"] = SQLiteDBSource("local")
    with pytest.raises(LLMError) as caught:
        executor.get_schema(("local", "shop", "public"))
    assert caught.value.code == "sql_target_denied"
    assert calls == []

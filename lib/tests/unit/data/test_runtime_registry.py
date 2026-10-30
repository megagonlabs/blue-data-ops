from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any, Protocol, cast

import pytest
from blue_data.registry.data_registry import DataRegistry
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource

import blue_data_ops.operators.operator as operator_runtime
from blue_data_ops.data import RegistrySeam
from blue_data_ops.data.config import build_environment_registry, registry_backend
from blue_data_ops.data.errors import REGISTRY_DIAGNOSTICS, RegistryFailure, RegistryReason
from blue_data_ops.data.registry_seam import _diagnose_source  # pyright: ignore[reportPrivateUsage]
from blue_data_ops.llm.errors import LLMError
from blue_data_ops.operators.types import ErrorRecord


class _Builder(Protocol):
    def __call__(self, **kwargs: str) -> object: ...


class _BuilderPatch(Protocol):
    def setattr(self, target: object, name: str, value: _Builder) -> None: ...


class _Patch(Protocol):
    def setattr(self, target: object, name: str, value: Callable[..., Any]) -> None: ...


_execution_error = cast(
    Callable[[str, BaseException], ErrorRecord], vars(operator_runtime)["_execution_error"]
)


@pytest.mark.parametrize("selector", ["unknown", " memory", "memory "])
def test_bad_selector_fails_before_construction(monkeypatch: pytest.MonkeyPatch, selector: str):
    monkeypatch.setenv("BLUE_DATA_REGISTRY_STORE", selector)
    with pytest.raises(RegistryFailure):
        build_environment_registry()


@pytest.mark.parametrize("content", ["{}", "[]", '{"sources":{}}', '{"sources":[null]}', "invalid"])
def test_invalid_source_document_before_any_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str
):
    import blue_data.config as config

    path = tmp_path / "sources.json"
    path.write_text(content)
    monkeypatch.setenv("BLUE_DATA_SOURCES_CONFIG", str(path))
    cast(_Patch, monkeypatch).setattr(
        config, "build_store", lambda: pytest.fail("constructed before validation")
    )
    with pytest.raises(RegistryFailure):
        build_environment_registry()


def test_missing_and_nonfile_sources_fail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    for path in (tmp_path / "absent", tmp_path, " "):
        monkeypatch.setenv("BLUE_DATA_SOURCES_CONFIG", str(path))
        with pytest.raises(RegistryFailure):
            build_environment_registry()


def test_configuration_intent_and_empty_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    assert build_environment_registry(require_configuration=True) is None
    monkeypatch.setenv("BLUE_DATA_REGISTRY_VECTOR_DIM", "4")
    assert build_environment_registry(require_configuration=True) is None
    assert isinstance(build_environment_registry(), RegistrySeam)
    monkeypatch.setenv("BLUE_DATA_REGISTRY_STORE", "MEMORY")
    assert registry_backend() == "memory"
    assert isinstance(build_environment_registry(require_configuration=True), RegistrySeam)
    monkeypatch.delenv("BLUE_DATA_REGISTRY_STORE")
    path = tmp_path / "empty.json"
    path.write_text('{"sources":[]}')
    monkeypatch.setenv("BLUE_DATA_SOURCES_CONFIG", str(path))
    assert isinstance(build_environment_registry(require_configuration=True), RegistrySeam)


def test_shared_builder_four_arguments_and_scoped_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    import blue_data.config as config
    import blue_data.registry.data_registry as module

    calls: list[dict[str, str]] = []
    for name in ("build_store", "build_enricher", "build_hybrid_config", "get_vector_dim"):
        cast(Callable[[object, str, Callable[[str], str]], None], monkeypatch.setattr)(
            config, name, lambda name=name: name
        )
    cast(_BuilderPatch, monkeypatch).setattr(
        module, "DataRegistry", lambda **kwargs: calls.append(kwargs) or object()
    )
    barrier = Barrier(2)

    def load(_: object) -> None:
        logging.getLogger("blue_data.config").warning("synthetic backend detail")
        barrier.wait(timeout=5)

    cast(_Patch, monkeypatch).setattr(config, "load_sources", load)
    caplog.set_level(logging.INFO)
    before = list(logging.getLogger("blue_data.config").filters)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            cast(Callable[[Callable[[int], RegistrySeam | None], range], Any], executor.map)(
                lambda _: build_environment_registry(), range(2)
            )
        )
    assert len(results) == 2
    assert (
        calls
        == [
            dict(
                store="build_store",
                metadata_enricher="build_enricher",
                hybrid_config="build_hybrid_config",
                vector_dim="get_vector_dim",
            )
        ]
        * 2
    )
    assert "synthetic backend detail" not in caplog.text
    assert logging.getLogger("blue_data.config").filters == before
    logging.getLogger("blue_data.config").warning("outside build")
    assert "outside build" in caplog.text


def test_absent_malformed_unavailable_and_lazy_source_states(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    registry = DataRegistry(name="source_states")
    seam = RegistrySeam(registry)
    assert seam.connect_source("absent") is None
    with pytest.raises(RegistryFailure) as absent:
        _diagnose_source(seam, "absent")
    assert absent.value.reason is RegistryReason.SOURCE_NOT_REGISTERED
    cast(Any, registry).register_record("malformed", "source", "/", properties={})
    assert seam.connect_source("malformed") is None
    with pytest.raises(RegistryFailure) as malformed:
        _diagnose_source(seam, "malformed")
    assert malformed.value.reason is RegistryReason.SOURCE_UNAVAILABLE
    source = SQLiteDBSource(
        "sqlite", properties={"connection": {"database_directory": str(tmp_path)}}
    )
    registry.register_source(source)
    registry.sources.clear()
    assert registry.get_source("sqlite") is None
    assert isinstance(seam.connect_source("sqlite"), SQLiteDBSource)
    cast(Any, registry).register_record(
        "down",
        "source",
        "/",
        properties={
            "_class": "unused.Class",
            "status": "unavailable",
            "error": "synthetic backend detail",
        },
    )
    cast(Callable[[object, str, Callable[[str], Any]], None], monkeypatch.setattr)(
        registry, "connect_source", lambda name: pytest.fail("unavailable source restored")
    )
    with pytest.raises(RegistryFailure) as unavailable:
        _diagnose_source(seam, "down")
    assert unavailable.value.reason is RegistryReason.SOURCE_UNAVAILABLE
    assert "synthetic backend detail" not in str(unavailable.value)


def test_metadata_failure_is_backend_failure_and_custom_seams_work(monkeypatch: pytest.MonkeyPatch):
    registry = DataRegistry(name="broken_metadata")
    cast(Callable[[object, str, Callable[[str], Any]], None], monkeypatch.setattr)(
        registry,
        "get_source_record",
        lambda _: (_ for _ in ()).throw(PermissionError("synthetic backend detail")),
    )
    seam = RegistrySeam(registry)
    assert seam.connect_source("x") is None
    with pytest.raises(PermissionError) as failure:
        _diagnose_source(seam, "x")
    error = _execution_error("probe@2.0.0", failure.value)
    assert error.message == "operator execution failed"
    assert error.retryable is False
    assert "synthetic backend detail" not in repr(error)

    class Custom(RegistrySeam):
        def __init__(self):
            pass

        def get_data_source_schema(self, *args: str | None, **kwargs: str | None) -> dict[str, Any]:
            return {"custom": True}

    assert Custom().get_data_source_schema("x", "db", "public") == {"custom": True}


@pytest.mark.parametrize(
    "exception,reason",
    [
        (sqlite3.IntegrityError("detail"), RegistryReason.CONSTRAINT_FAILED),
        (sqlite3.OperationalError("detail"), RegistryReason.QUERY_FAILED),
        (ValueError("detail"), RegistryReason.BACKEND_FAILED),
    ],
)
def test_owned_wrapper_preserves_sqlite_guidance_without_backend_text(
    exception: Exception, reason: RegistryReason
):
    import blue_data_ops.operators.create_database_operator as create_database

    _CreateDatabaseFailure = cast(
        type[RegistryFailure], vars(create_database)["_CreateDatabaseFailure"]
    )

    error = _execution_error("create_database@2.0.0", _CreateDatabaseFailure(exception))
    assert (error.message, error.suggestion) == REGISTRY_DIAGNOSTICS[reason]
    assert "detail" not in repr(error)


def test_fixed_llm_contract_and_foreign_lookalikes():
    mappings = {
        "reserved_field": (
            "operator template and transport controls are reserved",
            (
                "Remove caller template, extraction and transport controls; use a "
                "host-configured operator."
            ),
        ),
        "sql_policy_invalid": (
            "invalid SQL execution policy",
            (
                "Use a boolean execute_query and omit validate_query_prefixes or use a "
                "one-item SELECT list; remove caller execution capabilities and registry "
                "selectors when requesting execution."
            ),
        ),
        "sql_execution_unavailable": (
            "read-only SQL execution is not configured",
            (
                "Request generation only, or ask the deployment owner to configure a "
                "supported read-only SQL executor."
            ),
        ),
        "sql_target_denied": (
            "SQL target is outside the configured execution scope",
            "Use a target approved by the deployment owner, or request generation only.",
        ),
        "sql_query_rejected": (
            "generated SQL does not satisfy the read-only query contract",
            (
                "Request one SELECT statement as a nonempty string; execution also "
                "requires the database read-only guard."
            ),
        ),
        "sql_execution_failed": (
            "read-only SQL execution failed",
            (
                "Ask the deployment owner to check the approved target and read-only "
                "database configuration."
            ),
        ),
    }
    for code, expected in mappings.items():
        error = _execution_error("probe@2.0.0", LLMError("synthetic backend detail", code=code))
        assert (error.message, error.suggestion) == expected

    class Foreign(Exception):
        code = "sql_target_denied"

    foreign = Foreign("synthetic backend detail")
    foreign.__cause__ = LLMError("detail", code="sql_target_denied")
    assert _execution_error("probe@2.0.0", foreign).message == "operator execution failed"


def test_missing_registry_raw_compatibility_and_bn_outcome_reason():
    import blue_data_ops.operators._nl2bn_outcome as bn_outcome
    from blue_data_ops.operators._nl2bn_outcome import NL2BNOutcomeOperator

    _MissingRegistryError = cast(type[RegistryFailure], vars(bn_outcome)["_MissingRegistryError"])
    from blue_data_ops.operators.nl2bn_operator import NL2BNOperator
    from blue_data_ops.operators.nl2sql_operator import NL2SQLOperator

    assert _MissingRegistryError().reason is RegistryReason.NOT_CONFIGURED
    attributes = {
        "source": "none",
        "database": "db",
        "collection": "public",
        "protocol": "sqlite",
        "protocol_variant": "pgmpy",
        "question": "query",
    }
    assert NL2SQLOperator().apply([[]], attributes) == [[]]
    assert NL2BNOperator().apply([[]], attributes) == [[]]
    result = NL2BNOutcomeOperator().run([[]], attributes)
    assert result[2].errors[0].message == "data registry is not configured"

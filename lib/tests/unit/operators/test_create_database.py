"""Behavior and registry-boundary tests for `create_database`."""

from __future__ import annotations

from typing import Any

import pytest

blue_data = pytest.importorskip("blue_data")

from blue_data_ops.data import (  # noqa: E402
    BlueDataRegistryProvider,
    RegistrySeam,
    resolve_registry,
)
from blue_data_ops.operators.create_database_operator import CreateDatabaseOperator  # noqa: E402
from tests.doubles.data import RegistrySeamDouble  # noqa: E402

INPUT: list[list[dict[str, Any]]] = [[{"name": "db_from_input", "x": 1}]]
MINIMAL: dict[str, Any] = {"source": "src", "database": "db"}


class _RecordingSeam(RegistrySeamDouble, RegistrySeam):
    """The recording double, typed as a RegistrySeam so injection resolves it."""


class _RaisingSeam(_RecordingSeam):
    def create_source_database(self, *args: Any, **kwargs: Any) -> None:
        super().create_source_database(*args, **kwargs)
        raise RuntimeError("registry down")


@pytest.fixture
def op() -> CreateDatabaseOperator:
    return CreateDatabaseOperator()


@pytest.fixture
def seam() -> _RecordingSeam:
    return _RecordingSeam()


def _props(seam: RegistrySeam) -> dict[str, Any]:
    return {"data_registry": seam}


# --- No registry: pass-through with zero calls ---
@pytest.mark.parametrize("properties", [None, {}, {"unrelated": 1}])
def test_no_registry_passes_through(
    op: CreateDatabaseOperator, properties: dict[str, Any] | None
) -> None:
    assert op.apply(INPUT, dict(MINIMAL), properties) == INPUT


# --- Minimal attributes: exactly one facade create call ---
def test_minimal_create_call(op: CreateDatabaseOperator, seam: _RecordingSeam) -> None:
    out = op.apply(INPUT, dict(MINIMAL), _props(seam))
    assert out == INPUT  # pass-through
    assert seam.calls_to("create_source_database") == [
        {
            "source": "src",
            "database": "db",
            "properties": {},
            "overwrite": False,
            "rebuild": True,
            "recursive": False,
        }
    ]
    assert seam.calls_to("set_source_database_description") == []
    assert seam.calls_to("set_record_data") == []


# --- Full attributes: all three calls with exact keyword arguments ---
def test_full_attrs_all_calls(op: CreateDatabaseOperator, seam: _RecordingSeam) -> None:
    attrs: dict[str, Any] = {
        **MINIMAL,
        "description": "a db",
        "created_by": "ops",
        "overwrite": True,
        "properties": "p",
    }
    op.apply(INPUT, attrs, _props(seam))
    assert seam.calls_to("create_source_database")[0]["overwrite"] is True
    assert seam.calls_to("create_source_database")[0]["properties"] == "p"
    assert seam.calls_to("set_source_database_description") == [
        {"source": "src", "database": "db", "description": "a db", "rebuild": True}
    ]
    assert seam.calls_to("set_record_data") == [
        {
            "name": "db",
            "type": "database",
            "scope": "/source/src",
            "key": "created_by",
            "value": "ops",
            "rebuild": True,
        }
    ]


# --- Registry error: pass-through with no further calls ---
def test_registry_error_swallowed(op: CreateDatabaseOperator) -> None:
    seam = _RaisingSeam()
    out = op.apply(INPUT, {**MINIMAL, "description": "d"}, _props(seam))
    assert out == INPUT
    assert len(seam.calls_to("create_source_database")) == 1
    assert seam.calls_to("set_source_database_description") == []  # aborted by the raise


# --- Resolution failures PROPAGATE (resolution precedes the guarded block) ---
def test_resolver_failure_propagates(
    op: CreateDatabaseOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    import blue_data_ops.operators.create_database_operator as module

    def _boom(properties: Any) -> Any:
        raise RuntimeError("resolver down")

    monkeypatch.setattr(module, "resolve_registry", _boom)
    with pytest.raises(RuntimeError, match="resolver down"):
        op.apply(INPUT, dict(MINIMAL), {"data_registry.name": "r", "platform.name": "p"})


# --- Provider integration with a memory registry ---
def test_provider_path_creates_record(op: CreateDatabaseOperator) -> None:
    class _Source:
        def __init__(self) -> None:
            self.name = "isrc"
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

    provider = BlueDataRegistryProvider()
    props: dict[str, Any] = {"platform.name": "it_p", "data_registry.name": "it_r"}
    seam = resolve_registry(props, provider=provider)
    assert isinstance(seam, RegistrySeam)
    seam.register_source(_Source())  # pyright: ignore[reportArgumentType] — structural stub

    out = op.apply(INPUT, {"source": "isrc", "database": "idb"}, {"data_registry": seam})
    assert out == INPUT
    assert seam.get_record("idb", "database", "/source/isrc") is not None


# --- Validator (total) ---
@pytest.mark.parametrize(
    "attrs,expected",
    [
        (MINIMAL, True),
        ({"database": "db"}, False),
        ({"source": "", "database": "db"}, False),
        ({"source": "   ", "database": "db"}, False),
        ({"source": "src"}, False),
        ({"source": "src", "database": "  "}, False),
        ({**MINIMAL, "properties": {"a": 1}}, False),  # declared str; mapping fails
        ({**MINIMAL, "description": "d", "created_by": "c", "overwrite": True}, True),
    ],
    ids=[
        "valid",
        "no-source",
        "empty-source",
        "blank-source",
        "no-db",
        "blank-db",
        "mapping-properties-invalid",
        "all-optionals",
    ],
)
def test_validator(op: CreateDatabaseOperator, attrs: dict[str, Any], expected: bool) -> None:
    assert op.validate(INPUT, dict(attrs)) is expected


# --- Explainer (custom; name from the FIRST INPUT RECORD) ---
def test_explainer_reads_first_record_name(op: CreateDatabaseOperator) -> None:
    exp = op.explain(INPUT, INPUT, {**MINIMAL, "overwrite": True})
    assert exp["explanation"] == (
        "Create database operator overwrote database 'db_from_input' in source 'src'."
    )
    assert exp["input_data"] == INPUT


@pytest.mark.parametrize("empty", [[], [[]], [[{"other": 1}]]])
def test_explainer_guards(op: CreateDatabaseOperator, empty: list[list[dict[str, Any]]]) -> None:
    exp = op.explain(empty, empty, dict(MINIMAL))
    assert "database ''" in exp["explanation"]
    assert "created" in exp["explanation"]


# --- Full interface schema ---
def test_interface(op: CreateDatabaseOperator) -> None:
    assert op.name == "create_database"
    assert op.description == (
        "Creates databases in data sources using the data registry. If the database already "
        "exists, it will be overwritten if overwrite is True."
    )
    expected: dict[str, tuple[str, str, bool, Any]] = {
        "source": ("str", "Name of the data source where the database will be created", True, ""),
        "database": ("str", "Name of the database to be created", True, ""),
        "description": ("str", "Description of the database to be created", False, ""),
        "properties": ("str", "Properties of the database to be created", False, {}),
        "created_by": ("str", "Creator of the database", False, ""),
        "overwrite": ("bool", "Whether to overwrite the existing database", False, False),
    }
    assert set(op.attributes) == set(expected)
    for attr_name, (attr_type, attr_desc, required, default) in expected.items():
        spec = op.attributes[attr_name]
        assert spec.type == attr_type
        assert spec.description == attr_desc
        assert spec.required is required
        assert spec.default == default

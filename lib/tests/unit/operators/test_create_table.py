"""Behavior and registry-boundary tests for `create_table`."""

from __future__ import annotations

from typing import Any

import pytest

blue_data = pytest.importorskip("blue_data")

from blue_data_ops.data import RegistrySeam  # noqa: E402
from blue_data_ops.operators.create_table_operator import CreateTableOperator  # noqa: E402
from tests.doubles.data import RegistrySeamDouble  # noqa: E402

INPUT: list[list[dict[str, Any]]] = [[{"name": "table_from_input"}]]
COLUMNS: list[dict[str, Any]] = [{"name": "id", "type": "INTEGER"}, {"name": "label"}]


def minimal() -> dict[str, Any]:
    return {"source": "src", "database": "db", "table": "t", "columns": list(COLUMNS)}


class _RecordingSeam(RegistrySeamDouble, RegistrySeam):
    """The recording double, typed as a RegistrySeam so injection resolves it."""


class _RaisingSeam(_RecordingSeam):
    def create_source_database_collection_entity(self, *args: Any, **kwargs: Any) -> None:
        super().create_source_database_collection_entity(*args, **kwargs)
        raise RuntimeError("registry down")


class _ProbeRaisingSeam(_RecordingSeam):
    def get_source_properties(self, source: str) -> dict[str, Any]:
        super().get_source_properties(source)
        raise RuntimeError("probe failed")


@pytest.fixture
def op() -> CreateTableOperator:
    return CreateTableOperator()


def _props(seam: RegistrySeam) -> dict[str, Any]:
    return {"data_registry": seam}


# --- No registry: pass-through with zero calls ---
@pytest.mark.parametrize("properties", [None, {}])
def test_no_registry_passes_through(
    op: CreateTableOperator, properties: dict[str, Any] | None
) -> None:
    assert op.apply(INPUT, minimal(), properties) == INPUT


# --- Minimal attributes: probe followed by one facade create call ---
def test_minimal_create_call(op: CreateTableOperator) -> None:
    seam = _RecordingSeam()
    out = op.apply(INPUT, minimal(), _props(seam))
    assert out == INPUT
    assert seam.calls_to("get_source_properties") == [{"source": "src"}]
    create_calls = seam.calls_to("create_source_database_collection_entity")
    assert create_calls == [
        {
            "source": "src",
            "database": "db",
            "collection": "public",
            "entity": "t",
            "properties": {},
            "creation_properties": {"cols_definition": COLUMNS},
            "overwrite": False,
            "rebuild": True,
            "recursive": False,
        }
    ]


# --- SQLite collection coercion ---
def test_sqlite_source_forces_public_collection(op: CreateTableOperator) -> None:
    seam = _RecordingSeam(source_properties={"connection": {"protocol": "sqlite"}})
    op.apply(INPUT, {**minimal(), "collection": "custom"}, _props(seam))
    call = seam.calls_to("create_source_database_collection_entity")[0]
    assert call["collection"] == "public"  # forced despite the caller's 'custom'


def test_non_sqlite_source_keeps_collection(op: CreateTableOperator) -> None:
    seam = _RecordingSeam(source_properties={"connection": {"protocol": "postgres"}})
    op.apply(INPUT, {**minimal(), "collection": "custom"}, _props(seam))
    call = seam.calls_to("create_source_database_collection_entity")[0]
    assert call["collection"] == "custom"


# --- Probe errors do not prevent creation ---
def test_probe_error_ignored(op: CreateTableOperator) -> None:
    seam = _ProbeRaisingSeam()
    out = op.apply(INPUT, {**minimal(), "collection": "custom"}, _props(seam))
    assert out == INPUT
    call = seam.calls_to("create_source_database_collection_entity")[0]
    assert call["collection"] == "custom"  # probe failed; caller's collection kept


# --- Caller-misc aliasing contract ---
def test_misc_aliasing_mutates_caller_dict(op: CreateTableOperator) -> None:
    seam = _RecordingSeam()
    misc: dict[str, Any] = {"primary_key": ["id"]}
    attrs = {**minimal(), "misc": misc}
    op.apply(INPUT, attrs, _props(seam))
    # creation_properties aliases misc, so cols_definition is visible to the caller.
    assert misc["cols_definition"] == COLUMNS
    call = seam.calls_to("create_source_database_collection_entity")[0]
    assert call["creation_properties"] is misc


# --- Conditional description and creator metadata ---
def test_description_and_created_by(op: CreateTableOperator) -> None:
    seam = _RecordingSeam()
    attrs = {**minimal(), "description": "a table", "created_by": "ops"}
    op.apply(INPUT, attrs, _props(seam))
    assert seam.calls_to("set_source_database_collection_entity_description") == [
        {
            "source": "src",
            "database": "db",
            "collection": "public",
            "entity": "t",
            "description": "a table",
            "rebuild": True,
        }
    ]
    assert seam.calls_to("set_record_data") == [
        {
            "name": "t",
            "type": "entity",
            "scope": "/source/src/database/db/collection/public",
            "key": "created_by",
            "value": "ops",
            "rebuild": True,
        }
    ]


# --- Create errors are converted to pass-through results ---
def test_create_error_swallowed(op: CreateTableOperator) -> None:
    seam = _RaisingSeam()
    out = op.apply(INPUT, {**minimal(), "description": "d"}, _props(seam))
    assert out == INPUT
    assert seam.calls_to("set_source_database_collection_entity_description") == []


# --- Resolution failures PROPAGATE (resolution precedes the guarded block) ---
def test_resolver_failure_propagates(
    op: CreateTableOperator, monkeypatch: pytest.MonkeyPatch
) -> None:
    import blue_data_ops.operators.create_table_operator as module

    def _boom(properties: Any) -> Any:
        raise RuntimeError("resolver down")

    monkeypatch.setattr(module, "resolve_registry", _boom)
    with pytest.raises(RuntimeError, match="resolver down"):
        op.apply(INPUT, minimal(), {"data_registry.name": "r", "platform.name": "p"})


# --- Validator business rules ---
VALIDATOR_CASES: list[tuple[dict[str, Any], bool]] = [
    ({}, True),
    ({"source": "  "}, False),
    ({"database": ""}, False),
    ({"collection": " "}, False),
    ({"table": ""}, False),
    ({"columns": []}, False),
    ({"columns": "not-a-list"}, False),
    ({"columns": ["not-a-dict"]}, False),
    ({"columns": [{"type": "INTEGER"}]}, False),  # missing name
    ({"columns": [{"name": ""}]}, False),  # falsy name
    ({"columns": [{"name": "id", "type": 3}]}, False),  # non-str type
    ({"columns": [{"name": "id", "misc": 3}]}, False),  # non-str misc
    ({"misc": {"primary_key": "id"}}, False),  # not a list
    ({"misc": {"primary_key": ["nope"]}}, False),  # not in columns
    ({"misc": {"primary_key": ["id"]}}, True),
    ({"misc": {"foreign_keys": [{}]}}, False),  # missing required fields
    (
        {
            "misc": {
                "foreign_keys": [
                    {
                        "foreign_keys_source_columns": ["id"],
                        "foreign_keys_target_table": "other",
                        "foreign_keys_target_columns": ["oid"],
                    }
                ]
            }
        },
        True,
    ),
    (
        {
            "misc": {
                "foreign_keys": [
                    {
                        "foreign_keys_source_columns": ["nope"],
                        "foreign_keys_target_table": "other",
                        "foreign_keys_target_columns": ["oid"],
                    }
                ]
            }
        },
        False,
    ),
    ({"properties": {"a": 1}}, False),  # declared str; mapping fails
]


@pytest.mark.parametrize(
    "mutation,expected",
    VALIDATOR_CASES,
    ids=[
        "valid",
        "blank-source",
        "empty-db",
        "blank-collection",
        "empty-table",
        "empty-columns",
        "columns-not-list",
        "column-not-dict",
        "column-no-name",
        "column-falsy-name",
        "column-type-not-str",
        "column-misc-not-str",
        "pk-not-list",
        "pk-unknown-column",
        "pk-valid",
        "fk-missing-fields",
        "fk-valid",
        "fk-unknown-source-column",
        "mapping-properties-invalid",
    ],
)
def test_validator(op: CreateTableOperator, mutation: dict[str, Any], expected: bool) -> None:
    attrs = {**minimal(), **mutation}
    assert op.validate(INPUT, attrs) is expected


# --- Explainer (custom; name from the FIRST INPUT RECORD) ---
def test_explainer(op: CreateTableOperator) -> None:
    exp = op.explain(INPUT, INPUT, minimal())
    assert exp["explanation"] == (
        "Create table operator created table 'table_from_input' in database 'db' "
        "collection 'public' of source 'src'."
    )


# --- Full interface schema ---
def test_interface(op: CreateTableOperator) -> None:
    assert op.name == "create_table"
    expected: dict[str, tuple[str, str, bool, Any]] = {
        "source": (
            "str",
            "Name of the data source where the table will be created",
            True,
            "default_source",
        ),
        "database": (
            "str",
            "Name of the database where the table will be created",
            True,
            "default",
        ),
        "collection": (
            "str",
            "Name of the collection where the table will be created. For SQLite sources, "
            "defaults to 'public' if not specified",
            False,
            "public",
        ),
        "table": ("str", "Name of the table to be created", True, ""),
        "description": ("str", "Description of the table to be created", False, ""),
        "properties": ("str", "Properties of the table to be created", False, {}),
        # Columns intentionally reuse the public properties wording.
        "columns": ("list", "Properties of the table to be created", True, []),
        # The trailing space is part of the public description contract.
        "misc": ("dict", "Miscellaneous keys such as primary and foreign keys ", False, {}),
        "created_by": ("str", "Creator of the table", False, ""),
        "overwrite": ("bool", "Whether to overwrite the existing table", False, False),
    }
    assert set(op.attributes) == set(expected)
    for attr_name, (attr_type, attr_desc, required, default) in expected.items():
        spec = op.attributes[attr_name]
        assert spec.type == attr_type
        assert spec.description == attr_desc
        assert spec.required is required
        assert spec.default == default

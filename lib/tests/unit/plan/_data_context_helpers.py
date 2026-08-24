"""Registry doubles and record builders for the data-context tests.

`RegistryDouble` answers only the three read-only list operations the provider is
allowed to use and raises on every other seam attribute, so an added registry read
fails the suite instead of quietly widening the boundary. Its records carry the noise
fields a real blue-data record carries — `created_by`, `icon`, `contents`, per-record
`properties` — which is what makes the non-leakage assertions meaningful.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from blue_data_ops.plan.context import (
    DataContextSnapshot,
    DataScope,
    RegistryDataContextProvider,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

ORDERS_SOURCE = "demo_sqlite"
ORDERS_DATABASE = "shop"
ORDERS_COLLECTION = "public"
ORDERS_DESCRIPTION = "Sample customer purchase orders with totals and currencies"

OPAQUE_SOURCE = "opaque_catalog"
OPAQUE_DATABASE = "warehouse"
OPAQUE_COLLECTION = "curated"

ALLOWED_REGISTRY_METHODS = (
    "get_source_properties",
    "list_collection_entities",
    "list_entity_attributes",
)


def as_document(snapshot: DataContextSnapshot) -> dict[str, Any]:
    """`to_dict()` widened to Any so a test can walk nested JSON without a cast per hop."""

    return cast("dict[str, Any]", snapshot.to_dict())


def load_fixture(name: str) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads((FIXTURES / name).read_text()))


def entity_record(
    name: str,
    scope: DataScope,
    description: str | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "name": name,
        "type": "entity",
        "scope": (
            f"/source/{scope.source}/database/{scope.database}/collection/{scope.collection}"
        ),
        "description": "" if description is None else description,
        "created_by": "registry-operator@example.invalid",
        "properties": {"row_count": 4, "sample_values": [{"order_id": 1, "total": 80.0}]},
        "icon": "table",
        "contents": {},
    }
    record.update(overrides)
    return record


def attribute_record(name: str, declared_type: Any, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "name": name,
        "type": "attribute",
        "scope": "/source/s/database/d/collection/c/entity/e",
        "description": "",
        "created_by": None,
        "properties": {
            "name": name,
            "info": {"type": declared_type, "values": ["sample-value-must-not-leak"]},
            "description": "",
        },
        "icon": None,
        "contents": {},
    }
    record.update(overrides)
    return record


class RegistryDouble:
    """A call-recording stand-in exposing only the three allowed read operations."""

    def __init__(
        self,
        *,
        source_properties: Any = None,
        entities: list[Any] | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        # Mirrors SQLiteDBSource at the pinned blue-data 1b796fe: a protocol plus a
        # connection detail the projection must drop.
        default_properties = {
            "connection": {
                "protocol": "sql/sqlite",
                "database_directory": "/private/must-not-leak",
            }
        }
        self.source_properties: Any = (
            default_properties if source_properties is None else source_properties
        )
        self.entities: Any = [] if entities is None else entities
        self.attributes: dict[str, Any] = {} if attributes is None else attributes

    def get_source_properties(self, source: str) -> Any:
        self.calls.append(("get_source_properties", (source,)))
        return self.source_properties

    def list_collection_entities(self, source: str, database: str, collection: str) -> Any:
        self.calls.append(("list_collection_entities", (source, database, collection)))
        return self.entities

    def list_entity_attributes(
        self,
        source: str,
        database: str,
        collection: str,
        entity: str,
    ) -> Any:
        self.calls.append(("list_entity_attributes", (source, database, collection, entity)))
        return self.attributes.get(entity, [])

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"data context provider reached disallowed registry method {name!r}")

    @property
    def called_methods(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.calls)


def provider(double: RegistryDouble, **limits: int) -> RegistryDataContextProvider:
    return RegistryDataContextProvider(cast(Any, double), **limits)


def orders_scope(entities: tuple[str, ...] = ("orders",)) -> DataScope:
    return DataScope(ORDERS_SOURCE, ORDERS_DATABASE, ORDERS_COLLECTION, entities)


def opaque_scope(entities: tuple[str, ...] = ()) -> DataScope:
    return DataScope(OPAQUE_SOURCE, OPAQUE_DATABASE, OPAQUE_COLLECTION, entities)


def orders_double(reverse: bool = False) -> RegistryDouble:
    scope = orders_scope()
    columns = [
        ("order_id", "INTEGER"),
        ("customer_id", "INTEGER"),
        ("total", "REAL"),
        ("currency", "TEXT"),
    ]
    if reverse:
        columns.reverse()
    return RegistryDouble(
        entities=[entity_record("orders", scope, ORDERS_DESCRIPTION)],
        attributes={"orders": [attribute_record(name, kind) for name, kind in columns]},
    )


def opaque_double(reverse: bool = False) -> RegistryDouble:
    scope = opaque_scope()
    entities = [
        entity_record("t_017", scope, "Customer purchase orders with totals and currencies"),
        entity_record("t_042", scope, "Warehouse inventory counts and storage locations"),
    ]
    if reverse:
        entities.reverse()
    columns = [("c_01", "INTEGER"), ("c_02", "REAL")]
    if reverse:
        columns.reverse()
    return RegistryDouble(
        entities=entities,
        attributes={
            "t_017": [attribute_record(name, kind) for name, kind in columns],
            "t_042": [attribute_record(name, kind) for name, kind in columns],
        },
    )
